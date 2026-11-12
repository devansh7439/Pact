"""Signed PRP calls from the buyer agent to a merchant (doc 03).

Every request is signed with the agent's Ed25519 key. Every response is
verified against the merchant's registered public key before its body is
parsed. A response that fails verification comes back with
`signature_ok=False` and `body=None`, and the guard then REJECTs it (G1).

This module is the only way the buyer agent talks to a merchant, and the
money-moving calls (`checkout`, `accept`) are only reached through the guard
(see recovery.py).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from shared.prp import keys, signing
from shared.prp.signing import MemoryNonceStore, NonceStore, PRPAuthError

TIMEOUT_S = 20.0


@dataclass(frozen=True)
class PRPResponse:
    status: int
    body: Any  # parsed canonical JSON if signature_ok, else None
    raw: bytes  # exact bytes received, for evidence storage
    signature_ok: bool
    signature_error: str | None = None  # PRP error code if verification failed

    @property
    def is_offer(self) -> bool:
        return self.status == 402 and self.signature_ok and isinstance(self.body, dict) and "offer_id" in self.body


@dataclass
class MerchantKey:
    key_id: str
    public_key: Ed25519PublicKey


class PRPClient:
    def __init__(
        self,
        base_url: str,
        private_key: Ed25519PrivateKey,
        key_id: str,
        merchant_key: MerchantKey | None = None,
        *,
        http: httpx.AsyncClient | None = None,
        nonces: NonceStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._priv = private_key
        self.key_id = key_id
        self.merchant_key = merchant_key
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT_S)
        self._nonces = nonces or MemoryNonceStore()
        self._clock = clock

    async def aclose(self) -> None:
        await self._http.aclose()

    def _resolve(self, kid: str) -> Ed25519PublicKey | None:
        mk = self.merchant_key
        return mk.public_key if mk and mk.key_id == kid else None

    async def _call(
        self, method: str, path: str, body: Any = None, *, resolve: Callable[[str], Ed25519PublicKey | None] | None = None
    ) -> PRPResponse:
        now = int(self._clock())
        msg = signing.sign(self._priv, self.key_id, method, path, body, timestamp=now)
        resp = await self._http.request(method, self.base_url + path, content=msg.body, headers=msg.headers)
        raw = resp.content
        try:
            v = signing.verify(
                resp.headers, method, path, raw, resolve or self._resolve, self._nonces, now=int(self._clock())
            )
        except PRPAuthError as e:
            return PRPResponse(resp.status_code, None, raw, False, e.code)
        return PRPResponse(resp.status_code, v.body, raw, True)

    # -- endpoints --------------------------------------------------------- #

    async def register(self, body: dict[str, Any]) -> PRPResponse:
        """POST /agent/v1/register. The merchant's key arrives in this response
        (trust on first use): the response must verify under the key it carries,
        and that key is then pinned for every later call."""
        captured: dict[str, MerchantKey] = {}

        def tofu(kid: str) -> Ed25519PublicKey | None:
            return captured["k"].public_key if "k" in captured and captured["k"].key_id == kid else None

        now = int(self._clock())
        path = "/agent/v1/register"
        msg = signing.sign(self._priv, self.key_id, "POST", path, body, timestamp=now)
        resp = await self._http.post(self.base_url + path, content=msg.body, headers=msg.headers)
        raw = resp.content
        if resp.status_code != 201:
            # Error bodies carry no key. Verify against a key we already pinned if we
            # have one; otherwise surface the status as an unverified error rather
            # than masking it as BAD_SIGNATURE.
            if self.merchant_key is not None:
                try:
                    v = signing.verify(resp.headers, "POST", path, raw, self._resolve, self._nonces,
                                       now=int(self._clock()))
                    return PRPResponse(resp.status_code, v.body, raw, True)
                except PRPAuthError as e:
                    return PRPResponse(resp.status_code, None, raw, False, e.code)
            return PRPResponse(resp.status_code, None, raw, False, "UNVERIFIED_ERROR")
        try:
            unverified = signing.parse_canonical(raw)
            captured["k"] = MerchantKey(
                unverified["merchant_key_id"], keys.public_from_b64(unverified["merchant_public_key"])
            )
            v = signing.verify(resp.headers, "POST", path, raw, tofu, self._nonces, now=int(self._clock()))
        except (PRPAuthError, KeyError, TypeError, ValueError) as e:
            code = e.code if isinstance(e, PRPAuthError) else "BAD_SIGNATURE"
            return PRPResponse(resp.status_code, None, raw, False, code)
        self.merchant_key = captured["k"]
        return PRPResponse(resp.status_code, v.body, raw, True)

    async def checkout(self, body: dict[str, Any]) -> PRPResponse:
        return await self._call("POST", "/agent/v1/checkout", body)

    async def get_offer(self, offer_id: str) -> PRPResponse:
        return await self._call("GET", f"/agent/v1/offers/{offer_id}")

    async def accept(self, offer_id: str, acceptance: dict[str, Any]) -> PRPResponse:
        return await self._call("POST", f"/agent/v1/offers/{offer_id}/accept", acceptance)

    async def decline(self, offer_id: str) -> PRPResponse:
        return await self._call("POST", f"/agent/v1/offers/{offer_id}/decline", {"prp_version": "0.1", "offer_id": offer_id})

    async def get_intent(self, intent_id: str) -> PRPResponse:
        return await self._call("GET", f"/agent/v1/intents/{intent_id}")
