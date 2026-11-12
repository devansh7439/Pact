"""Ed25519 keypairs for PRP: generation, (de)serialisation, fingerprints.

Each party holds its own private key; only public keys cross the wire, as
base64url(raw 32 bytes). Key ids look like ``agt_7f3c...#k1`` — signer id plus
a version suffix so keys can rotate.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_to_b64(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return b64u_encode(raw)


def private_from_b64(text: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(b64u_decode(text))


def public_to_b64(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64u_encode(raw)


def public_from_b64(text: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(b64u_decode(text))


def fingerprint(key: Ed25519PublicKey) -> str:
    """Short, stable id for display: first 16 hex chars of sha256(raw public key)."""
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def key_id(signer_id: str, version: int = 1) -> str:
    return f"{signer_id}#k{version}"


def _main(argv: list[str]) -> int:
    """`python -m shared.prp.keys generate` -> prints a private key and its public key."""
    if argv[:1] != ["generate"]:
        print("usage: python -m shared.prp.keys generate")
        return 2
    priv = generate()
    print(f"private (base64url, keep secret): {private_to_b64(priv)}")
    print(f"public  (base64url):              {public_to_b64(priv.public_key())}")
    print(f"fingerprint:                      {fingerprint(priv.public_key())}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
