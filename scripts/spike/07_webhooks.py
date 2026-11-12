"""S7 · Webhooks + signature verification (doc 09; doc 04 §5).

    python scripts/spike/07_webhooks.py register https://<tunnel>/paypal/webhooks
    python scripts/spike/07_webhooks.py listen [--port 8100]
        (in another shell: cloudflared/ngrok -> this port; then rerun 04_charge_vaulted.py wallet)
    python scripts/spike/07_webhooks.py verify scripts/spike/webhooks/<event-id>.json

`listen` runs a tiny stdlib HTTP server on /paypal/webhooks. It saves each event
(body + the five paypal-* headers) under scripts/spike/webhooks/ and calls
verify-webhook-signature right away.

Pass when: verification_status == SUCCESS for PAYMENT.CAPTURE.COMPLETED (and
DECLINED if PayPal emits it). Never weaken verification to make simulator
events pass; use real sandbox transactions.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import _common as c

EVENTS = [
    "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DECLINED", "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.REFUNDED", "CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED",
    "VAULT.PAYMENT-TOKEN.CREATED",
]
HEADERS = ["paypal-transmission-id", "paypal-transmission-time", "paypal-transmission-sig",
           "paypal-cert-url", "paypal-auth-algo"]
SAVE_DIR = c.HERE / "webhooks"


def _flag(a: list[str], name: str, default: str) -> str:
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def webhook_id() -> str:
    wid = os.environ.get("PAYPAL_WEBHOOK_ID") or c.load_state().get("webhook_id")
    if not wid:
        c.usage("no webhook id: run `register` or set PAYPAL_WEBHOOK_ID")
    return wid


def register(pp: c.PayPal, url: str) -> None:
    body = {"url": url, "event_types": [{"name": n} for n in EVENTS]}
    status, wh = pp.call("register webhook", "POST", "/v1/notifications/webhooks", body)
    if status >= 300:
        c.note("S7", f"FAIL register webhook: HTTP {status} {wh.get('name') if isinstance(wh, dict) else ''}")
        return
    c.save_state(webhook_id=wh["id"])
    c.note("S7", f"registered webhook {wh['id']} -> {url}. Put it in PAYPAL_WEBHOOK_ID.")


def verify(pp: c.PayPal, headers: dict[str, str], event: dict) -> str:
    body = {
        "auth_algo": headers.get("paypal-auth-algo"),
        "cert_url": headers.get("paypal-cert-url"),
        "transmission_id": headers.get("paypal-transmission-id"),
        "transmission_sig": headers.get("paypal-transmission-sig"),
        "transmission_time": headers.get("paypal-transmission-time"),
        "webhook_id": webhook_id(),
        "webhook_event": event,
    }
    status, res = pp.call(f"verify {event.get('event_type')}", "POST",
                          "/v1/notifications/verify-webhook-signature", body)
    vs = res.get("verification_status") if isinstance(res, dict) else None
    ok = status < 300 and vs == "SUCCESS"
    c.note("S7", f"{'PASS' if ok else 'FAIL'} {event.get('event_type')} {event.get('id')}: verification_status={vs}")
    return vs or ""


def verify_file(pp: c.PayPal, path: str) -> None:
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    verify(pp, saved["headers"], saved["event"])


def listen(pp: c.PayPal, port: int) -> None:
    SAVE_DIR.mkdir(exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if not self.path.startswith("/paypal/webhooks"):
                self.send_response(404)
                self.end_headers()
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {h: self.headers.get(h, "") for h in HEADERS}
            try:
                event = json.loads(raw)
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            (SAVE_DIR / f"{event.get('id', 'unknown')}.json").write_text(
                json.dumps({"headers": headers, "event": event}, indent=2), encoding="utf-8")
            status = verify(pp, headers, event)
            # Mirror production: unverified events are stored but answered 400.
            self.send_response(200 if status == "SUCCESS" else 400)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            print("webhook:", fmt % args)

    print(f"listening on http://0.0.0.0:{port}/paypal/webhooks — Ctrl+C to stop")
    try:
        HTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


def main() -> None:
    pp = c.PayPal("S7")
    a = c.args()
    if a[:1] == ["register"] and len(a) > 1:
        register(pp, a[1])
    elif a[:1] == ["listen"]:
        listen(pp, int(_flag(a, "--port", "8100")))
    elif a[:1] == ["verify"] and len(a) > 1:
        verify_file(pp, a[1])
    else:
        c.usage(__doc__)


if __name__ == "__main__":
    main()
