"""Shared plumbing for the PayPal feasibility spike (doc 09). Plain httpx, no framework.

- Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (and friends) from the env or `.env`.
- With no credentials, every script prints "SKIPPED: no credentials" and exits 0.
- Every call is appended to scripts/spike/RESULTS.md with secrets redacted.
- Ids worth keeping between scripts (customer id, vault ids, order ids) live in
  scripts/spike/state.json. These are sandbox ids, but keep the file out of git.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = HERE / "RESULTS.md"
STATE = HERE / "state.json"
BASE = "https://api-m.sandbox.paypal.com"
LOG_MARKER = "<!-- spike-log: scripts append below this line -->"

# Test card from PayPal's card-testing page (doc 04 §4). Not a real card.
TEST_CARD = "4012888888881881"
TEST_EXPIRY = "2030-12"
TEST_CVV = "123"


# --------------------------------------------------------------------------- #
# env & state
# --------------------------------------------------------------------------- #


def load_env() -> None:
    """Minimal .env reader: KEY=VALUE lines, `#` comments; real env wins."""
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def require_credentials() -> tuple[str, str]:
    load_env()
    cid, secret = os.environ.get("PAYPAL_CLIENT_ID", ""), os.environ.get("PAYPAL_CLIENT_SECRET", "")
    if not (cid and secret):
        print("SKIPPED: no credentials (set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env)")
        raise SystemExit(0)
    if os.environ.get("PAYPAL_ENV", "sandbox") != "sandbox":
        print("REFUSING: the spike only runs against the sandbox (PAYPAL_ENV=sandbox)")
        raise SystemExit(2)
    return cid, secret


def public_url() -> str:
    return os.environ.get("MERCHANT_PUBLIC_URL", "http://localhost:8100").rstrip("/")


def load_state() -> dict[str, Any]:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(**updates: Any) -> dict[str, Any]:
    s = load_state()
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    STATE.write_text(json.dumps(s, indent=2, sort_keys=True), encoding="utf-8")
    return s


def request_id(*parts: str) -> str:
    """Deterministic PayPal-Request-Id (same inputs -> same id), as the build does."""
    return "_".join(parts) if parts else str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# redaction & logging
# --------------------------------------------------------------------------- #

_SECRET_KEYS = {"access_token", "client_secret", "security_code", "password", "refresh_token", "id_token"}
_HEADER_SECRETS = {"authorization", "paypal-auth-assertion"}


def _mask_card(num: str) -> str:
    digits = re.sub(r"\D", "", num)
    return f"{digits[:4]}{'*' * max(0, len(digits) - 8)}{digits[-4:]}" if len(digits) >= 8 else "****"


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = k.lower()
            if lk in _SECRET_KEYS:
                out[k] = "[REDACTED]"
            elif lk == "number" and isinstance(v, str):
                out[k] = _mask_card(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def redact_headers(h: dict[str, str]) -> dict[str, str]:
    return {k: ("[REDACTED]" if k.lower() in _HEADER_SECRETS else v) for k, v in h.items()}


def _ensure_results() -> None:
    if not RESULTS.exists():
        RESULTS.write_text(f"# Spike results\n\n{LOG_MARKER}\n", encoding="utf-8")


def log_call(step: str, title: str, method: str, url: str, headers: dict[str, str], body: Any,
             status: int, resp_headers: dict[str, str], resp_body: Any) -> None:
    _ensure_results()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    debug_id = resp_headers.get("paypal-debug-id", "")
    block = (
        f"\n### {step} · {title} · {ts}\n\n"
        f"`{method} {url.replace(BASE, '')}` → **{status}**"
        f"{f' · debug id `{debug_id}`' if debug_id else ''}\n\n"
        "<details><summary>request / response (redacted)</summary>\n\n"
        f"```json\n{json.dumps({'headers': redact_headers(headers), 'body': redact(body)}, indent=2)}\n```\n\n"
        f"```json\n{json.dumps(redact(resp_body), indent=2)}\n```\n\n</details>\n"
    )
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(block)


def note(step: str, text: str) -> None:
    """Append a plain observation (e.g. a pass/fail verdict) to the log."""
    _ensure_results()
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(f"\n> **{step}** — {text}\n")
    print(f"[{step}] {text}")


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #


class PayPal:
    def __init__(self, step: str) -> None:
        self.step = step
        self._cid, self._secret = require_credentials()
        self._http = httpx.Client(base_url=BASE, timeout=30.0)
        self._token: str | None = None
        self._token_exp = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = self._http.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
                            auth=(self._cid, self._secret), headers={"Accept": "application/json"})
        body = _json(r)
        log_call(self.step, "OAuth token", "POST", str(r.request.url),
                 {"Authorization": "Basic [REDACTED]"}, {"grant_type": "client_credentials"},
                 r.status_code, dict(r.headers), body)
        r.raise_for_status()
        self._token = body["access_token"]
        self._token_exp = time.time() + int(body.get("expires_in", 300))
        return self._token

    def call(self, title: str, method: str, path: str, body: Any = None, *,
             request_id: str | None = None, extra_headers: dict[str, str] | None = None,
             params: dict[str, str] | None = None) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        headers.update(extra_headers or {})
        r = self._http.request(method, path, json=body, headers=headers, params=params)
        resp = _json(r)
        log_call(self.step, title, method, str(r.request.url), headers, copy.deepcopy(body),
                 r.status_code, dict(r.headers), resp)
        print(f"{method} {path} -> {r.status_code}")
        return r.status_code, resp


def _json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return {"_raw": r.text[:2000]}


def link(resp: Any, *rels: str) -> str | None:
    for l in (resp or {}).get("links", []) if isinstance(resp, dict) else []:
        if l.get("rel") in rels:
            return l.get("href")
    return None


def capture_summary(order: dict[str, Any]) -> dict[str, Any]:
    """Pull status + processor_response out of an order, whichever shape it has."""
    caps = [c for pu in order.get("purchase_units", []) for c in pu.get("payments", {}).get("captures", [])]
    c = caps[0] if caps else {}
    return {
        "order_id": order.get("id"),
        "order_status": order.get("status"),
        "capture_id": c.get("id"),
        "capture_status": c.get("status"),
        "processor_response": c.get("processor_response"),
        "issue": next((d.get("issue") for d in order.get("details", [])), None) if "details" in order else None,
    }


def usage(doc: str) -> None:
    print(doc.strip())
    raise SystemExit(2)


def args() -> list[str]:
    return sys.argv[1:]
