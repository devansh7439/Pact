"""Heuristic injection scanner for untrusted `display.text` (doc 06 §4, defence 4).

Flags only. The result is shown as a security event in both consoles. It never
changes a guard decision, because the guard never reads the text.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|instructions?|rules?|mandate)\b", re.I | re.S)),
    ("role_marker", re.compile(r"(^|\n|\s)(system|assistant|developer)\s*:", re.I)),
    ("mandate_override", re.compile(r"\bmandate\b.{0,30}\b(updated|changed|overrid\w*|now)\b|\bbudget\b.{0,20}\bis now\b", re.I | re.S)),
    ("payment_command", re.compile(r"\b(you must|you should|agent,?)\s*(now\s+)?(pay|accept|approve|use|charge|send)\b|\bpay with any\b", re.I)),
    ("secret_request", re.compile(r"\b(api[_ -]?key|private key|password|token|vault[_ ]?id)\b", re.I)),
]
_URL = re.compile(r"\bhttps?://[^\s<>\"')]+", re.I)


def scan(text: str, allowed_domains: tuple[str, ...] = ()) -> list[str]:
    """Return sorted flag names found in `text`. Empty list = nothing suspicious."""
    flags = {name for name, pat in _PATTERNS if pat.search(text or "")}
    for url in _URL.findall(text or ""):
        host = (urlparse(url).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in allowed_domains):
            flags.add("foreign_url")
    return sorted(flags)
