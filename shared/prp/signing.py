"""PRP v0.1 message signing: canonical JSON, Ed25519 sign/verify, replay guard.

Signed string (doc 03 §3):

    "PRP/0.1\n" + METHOD + "\n" + path + "\n" + timestamp + "\n" + nonce + "\n" + canonical_json(body)

The wire body MUST be exactly ``canonical_json(body)``. Receivers verify the raw
bytes they received, before parsing them into models, and reject a body that is
not already canonical. That rules out parser differentials (duplicate keys,
alternate number spellings) between what was signed and what gets acted on.

Responses are signed the same way, binding the request's method and path.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from shared.prp.keys import b64u_decode, b64u_encode

PRP_VERSION = "0.1"
SIG_PREFIX = "v1="
MAX_SKEW_S = 300
NONCE_TTL_S = 600

H_KEY_ID = "PRP-Key-Id"
H_TIMESTAMP = "PRP-Timestamp"
H_NONCE = "PRP-Nonce"
H_SIGNATURE = "PRP-Signature"


class PRPAuthError(Exception):
    """Signature-layer rejection. `code` is a PRP error code (doc 03 §7)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message or code


# --------------------------------------------------------------------------- #
# Canonical JSON
# --------------------------------------------------------------------------- #


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("floats are not allowed in PRP bodies; use integer minor units")
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError("PRP object keys must be strings")
            _reject_floats(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _reject_floats(v)


def canonical_json(body: Any) -> bytes:
    """UTF-8, sorted keys, no insignificant whitespace, no floats. `None` -> b""."""
    if body is None:
        return b""
    _reject_floats(body)
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _float_forbidden(text: str) -> Any:
    raise ValueError(f"float literal {text!r} not allowed")


def parse_canonical(raw: bytes) -> Any:
    """Parse a verified body. Rejects floats, duplicate keys and non-canonical bytes."""
    if raw == b"":
        return None
    try:
        obj = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_float=_float_forbidden,
            parse_constant=_float_forbidden,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PRPAuthError("BAD_SIGNATURE", f"body is not valid PRP JSON: {exc}") from exc
    if canonical_json(obj) != raw:
        raise PRPAuthError("BAD_SIGNATURE", "body is not in canonical form")
    return obj


# --------------------------------------------------------------------------- #
# Signing
# --------------------------------------------------------------------------- #


def signing_input(method: str, path: str, timestamp: int, nonce: str, body_bytes: bytes) -> bytes:
    head = f"PRP/{PRP_VERSION}\n{method.upper()}\n{path}\n{timestamp}\n{nonce}\n"
    return head.encode("utf-8") + body_bytes


@dataclass(frozen=True)
class SignedMessage:
    headers: dict[str, str]
    body: bytes  # send exactly these bytes


def sign(
    private_key: Ed25519PrivateKey,
    key_id: str,
    method: str,
    path: str,
    body: Any = None,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> SignedMessage:
    ts = int(time.time()) if timestamp is None else timestamp
    nn = nonce or str(uuid.uuid4())
    body_bytes = canonical_json(body)
    sig = private_key.sign(signing_input(method, path, ts, nn, body_bytes))
    headers = {
        H_KEY_ID: key_id,
        H_TIMESTAMP: str(ts),
        H_NONCE: nn,
        H_SIGNATURE: SIG_PREFIX + b64u_encode(sig),
    }
    if body_bytes:
        headers["Content-Type"] = "application/json"
    return SignedMessage(headers=headers, body=body_bytes)


# --------------------------------------------------------------------------- #
# Replay guard
# --------------------------------------------------------------------------- #


class NonceStore(Protocol):
    def seen(self, key_id: str, nonce: str, now: int) -> bool: ...
    def remember(self, key_id: str, nonce: str, now: int) -> bool:
        """Record the nonce; return False if it was already present (race-safe)."""
        ...


class MemoryNonceStore:
    """Process-local nonce cache with a TTL. Fine for one worker and for tests."""

    def __init__(self, ttl_s: int = NONCE_TTL_S) -> None:
        self._ttl = ttl_s
        self._seen: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def _evict(self, now: int) -> None:
        cutoff = now - self._ttl
        for k in [k for k, t in self._seen.items() if t < cutoff]:
            del self._seen[k]

    def seen(self, key_id: str, nonce: str, now: int) -> bool:
        with self._lock:
            self._evict(now)
            return (key_id, nonce) in self._seen

    def remember(self, key_id: str, nonce: str, now: int) -> bool:
        with self._lock:
            self._evict(now)
            if (key_id, nonce) in self._seen:
                return False
            self._seen[(key_id, nonce)] = now
            return True


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Verified:
    key_id: str
    timestamp: int
    nonce: str
    body: Any  # parsed canonical JSON (dict/list/None); not yet a model
    raw: bytes  # exact signed bytes, for storage as evidence


def _header(headers: Mapping[str, str], name: str) -> str:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    raise PRPAuthError("BAD_SIGNATURE", f"missing header {name}")


def verify(
    headers: Mapping[str, str],
    method: str,
    path: str,
    raw_body: bytes,
    resolve_key: Callable[[str], Ed25519PublicKey | None],
    nonces: NonceStore,
    *,
    now: int | None = None,
    max_skew_s: int = MAX_SKEW_S,
) -> Verified:
    """Verify a PRP-signed message. Raises PRPAuthError; never parses into models.

    Order: unknown key -> clock skew -> replayed nonce -> bad signature -> record nonce.
    The nonce is recorded only after the signature checks out, so forged requests
    cannot burn legitimate nonces.
    """
    t_now = int(time.time()) if now is None else now
    key_id = _header(headers, H_KEY_ID)
    ts_text = _header(headers, H_TIMESTAMP)
    nonce = _header(headers, H_NONCE)
    sig_text = _header(headers, H_SIGNATURE)

    public_key = resolve_key(key_id)
    if public_key is None:
        raise PRPAuthError("UNKNOWN_KEY", f"unknown key id {key_id!r}")

    if not ts_text.isdigit():
        raise PRPAuthError("CLOCK_SKEW", "timestamp is not unix seconds")
    ts = int(ts_text)
    if abs(t_now - ts) > max_skew_s:
        raise PRPAuthError("CLOCK_SKEW", f"skew {t_now - ts}s exceeds {max_skew_s}s")

    if not nonce or len(nonce) > 128:
        raise PRPAuthError("BAD_SIGNATURE", "invalid nonce")
    if nonces.seen(key_id, nonce, t_now):
        raise PRPAuthError("REPLAYED_NONCE", "nonce already used")

    if not sig_text.startswith(SIG_PREFIX):
        raise PRPAuthError("BAD_SIGNATURE", "unsupported signature version")
    try:
        sig = b64u_decode(sig_text[len(SIG_PREFIX):])
        public_key.verify(sig, signing_input(method, path, ts, nonce, raw_body))
    except (InvalidSignature, ValueError) as exc:
        raise PRPAuthError("BAD_SIGNATURE", "signature does not verify") from exc

    body = parse_canonical(raw_body)

    if not nonces.remember(key_id, nonce, t_now):
        raise PRPAuthError("REPLAYED_NONCE", "nonce already used")

    return Verified(key_id=key_id, timestamp=ts, nonce=nonce, body=body, raw=raw_body)
