"""S4 / S4b · Charge a saved source with no redirect (doc 09; doc 04 §3.1, §3.4).

    python scripts/spike/04_charge_vaulted.py wallet
    python scripts/spike/04_charge_vaulted.py card card-clean --encoding A
    python scripts/spike/04_charge_vaulted.py card card-clean --encoding B
    python scripts/spike/04_charge_vaulted.py all          # wallet + clean card under A and B

Encodings for cards (payment_source.card.stored_credential):
    A = CUSTOMER / ONE_TIME / SUBSEQUENT     (agent as the customer's delegate)
    B = MERCHANT / UNSCHEDULED / SUBSEQUENT  (merchant charge under consent)
    none = omit stored_credential

Pass when: COMPLETED with no payer interaction. If the order comes back
APPROVED/CREATED instead of COMPLETED, the script captures it and records that
the source needs an explicit capture (doc 04 §3.1 "spike item").
"""

from __future__ import annotations

from typing import Any

import _common as c

ENCODINGS: dict[str, dict[str, str] | None] = {
    "A": {"payment_initiator": "CUSTOMER", "payment_type": "ONE_TIME", "usage": "SUBSEQUENT"},
    "B": {"payment_initiator": "MERCHANT", "payment_type": "UNSCHEDULED", "usage": "SUBSEQUENT"},
    "none": None,
}


def _flag(a: list[str], name: str, default: str) -> str:
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def order_body(source: dict[str, Any], ref: str, value: str = "32.00") -> dict[str, Any]:
    return {
        "intent": "CAPTURE",
        "purchase_units": [{"reference_id": ref, "custom_id": ref,
                            "amount": {"currency_code": "USD", "value": value}}],
        "payment_source": source,
    }


def wallet_source(vault_id: str) -> dict[str, Any]:
    return {"paypal": {"vault_id": vault_id}}


def card_source(vault_id: str, encoding: str) -> dict[str, Any]:
    card: dict[str, Any] = {"vault_id": vault_id}
    sc = ENCODINGS[encoding]
    if sc:
        card["stored_credential"] = dict(sc)
    return {"card": card}


def charge(pp: c.PayPal, step: str, label: str, source: dict[str, Any], rid: str,
           extra_headers: dict[str, str] | None = None, value: str = "32.00") -> dict[str, Any]:
    """Create (and if needed capture) an order. Returns capture_summary + http status."""
    status, order = pp.call(f"order {label}", "POST", "/v2/checkout/orders",
                            order_body(source, f"pi_spike_{rid}", value), request_id=rid,
                            extra_headers=extra_headers)
    s = c.capture_summary(order if isinstance(order, dict) else {})
    s["http"] = status
    if status < 300 and order.get("status") in ("APPROVED", "CREATED") and not s["capture_status"]:
        if order.get("status") == "CREATED" and c.link(order, "payer-action", "approve"):
            s["needs_payer"] = True  # redirect required: this is a FAIL for S4
            return s
        cstatus, cap = pp.call(f"capture {label}", "POST", f"/v2/checkout/orders/{order['id']}/capture", {},
                               request_id=f"{rid}_cap", extra_headers=extra_headers)
        s = c.capture_summary(cap if isinstance(cap, dict) else {})
        s["http"] = cstatus
        s["explicit_capture"] = True
    if status >= 300 and isinstance(order, dict):
        s["issue"] = next((d.get("issue") for d in order.get("details", [])), order.get("name"))
    return s


def _vault(alias: str) -> str:
    vid = c.load_state().get("vault", {}).get(alias)
    if not vid:
        c.usage(f"no vault_id for {alias!r} in state.json — run 02/03 first")
    return vid


def run_wallet(pp: c.PayPal) -> None:
    s = charge(pp, "S4", "wallet vault_id", wallet_source(_vault("paypal-wallet")),
               c.request_id("spike", "s4", "wallet", str(int(c.time.time()))))
    ok = s.get("capture_status") == "COMPLETED" and not s.get("needs_payer")
    c.note("S4", f"{'PASS' if ok else 'FAIL'} wallet: {s}")


def run_card(pp: c.PayPal, alias: str, encoding: str) -> None:
    s = charge(pp, "S4b" if encoding != "none" else "S4", f"card {alias} enc={encoding}",
               card_source(_vault(alias), encoding),
               c.request_id("spike", "s4", alias, encoding, str(int(c.time.time()))))
    ok = s.get("capture_status") == "COMPLETED" and not s.get("needs_payer")
    c.note("S4b" if encoding != "none" else "S4", f"{'PASS' if ok else 'FAIL'} card {alias} encoding {encoding}: {s}")


def main() -> None:
    pp = c.PayPal("S4")
    a = c.args()
    if a[:1] == ["wallet"]:
        run_wallet(pp)
    elif a[:1] == ["card"] and len(a) > 1:
        run_card(pp, a[1], _flag(a, "--encoding", "A"))
    elif a[:1] == ["all"]:
        run_wallet(pp)
        for enc in ("A", "B"):
            run_card(pp, "card-clean", enc)
    else:
        c.usage(__doc__)


if __name__ == "__main__":
    main()
