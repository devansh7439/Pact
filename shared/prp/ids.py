"""Prefixed, time-ordered ids: `new_id("off")` -> "off_01JD4K8Q3ZP6M2X9T4VBN7C5RA".

26 Crockford-base32 chars (48-bit ms timestamp + 80 random bits), ULID-style,
matching the `^<prefix>_[0-9A-Za-z]{10,40}$` patterns in schemas/.
"""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _b32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str, *, now_ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    return f"{prefix}_{_b32(ms, 10)}{_b32(secrets.randbits(80), 16)}"
