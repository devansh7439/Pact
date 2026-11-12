"""S1 · Auth + basic order (doc 09).

    python scripts/spike/01_auth_order.py create        # prints the approve link
    (approve as Maya in the browser)
    python scripts/spike/01_auth_order.py capture [ORDER_ID]

Pass when: capture COMPLETED (processor_response is only present for card payments).
"""

from __future__ import annotations

import _common as c


def create(pp: c.PayPal) -> None:
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": "pi_spike_s1",
            "custom_id": "pi_spike_s1",
            "amount": {"currency_code": "USD", "value": "32.00"},
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "Kettle & Crumb (sandbox)",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "return_url": f"{c.public_url()}/paypal/return",
            "cancel_url": f"{c.public_url()}/paypal/return?cancel=1",
        }}},
    }
    status, order = pp.call("create order (payer approval)", "POST", "/v2/checkout/orders", body,
                            request_id=c.request_id("spike", "s1", "create", str(int(c.time.time()))))
    if status >= 300:
        c.note("S1", f"FAIL create order: HTTP {status}")
        return
    c.save_state(s1_order_id=order["id"])
    print(f"\nApprove as Maya: {c.link(order, 'payer-action', 'approve')}")
    print(f"Then run: python scripts/spike/01_auth_order.py capture {order['id']}")


def capture(pp: c.PayPal, order_id: str | None) -> None:
    order_id = order_id or c.load_state().get("s1_order_id")
    if not order_id:
        c.usage("no order id: run `create` first or pass ORDER_ID")
    status, order = pp.call("capture order", "POST", f"/v2/checkout/orders/{order_id}/capture", {},
                            request_id=c.request_id("spike", "s1", "capture", order_id))
    s = c.capture_summary(order)
    ok = status < 300 and s["capture_status"] == "COMPLETED"
    c.note("S1", f"{'PASS' if ok else 'FAIL'} capture: {s}")


def main() -> None:
    pp = c.PayPal("S1")
    a = c.args()
    if a[:1] == ["create"]:
        create(pp)
    elif a[:1] == ["capture"]:
        capture(pp, a[1] if len(a) > 1 else None)
    else:
        c.usage(__doc__)


if __name__ == "__main__":
    main()
