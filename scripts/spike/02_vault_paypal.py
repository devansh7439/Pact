"""S2 · Save a PayPal wallet (doc 09; doc 04 §3.3). Also the wallet half of S4b.

    python scripts/spike/02_vault_paypal.py create [--usage-pattern IMMEDIATE]
    (approve as Maya; screenshot PayPal's consent text for the write-up)
    python scripts/spike/02_vault_paypal.py finish [SETUP_TOKEN_ID]
    python scripts/spike/02_vault_paypal.py list

Pass when: a vault_id is returned and appears in GET /v3/vault/payment-tokens?customer_id=.

S4b (wallet): rerun `create` with an unscheduled pattern, e.g.
`--usage-pattern UNSCHEDULED_POSTPAID`, and record which patterns PayPal accepts.
The exact enum values are VERIFY-IN-SPIKE (doc 04 §3.4); a 422 here is a result.
"""

from __future__ import annotations

import _common as c


def _flag(a: list[str], name: str, default: str) -> str:
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def create(pp: c.PayPal, usage_pattern: str) -> None:
    st = c.load_state()
    body: dict = {"payment_source": {"paypal": {
        "description": "Kettle & Crumb — let your agent pay with PayPal (sandbox)",
        "usage_type": "MERCHANT",
        "usage_pattern": usage_pattern,
        "customer_type": "CONSUMER",
        "permit_multiple_payment_tokens": True,
        "experience_context": {
            "brand_name": "Kettle & Crumb (sandbox)",
            "shipping_preference": "NO_SHIPPING",
            "return_url": f"{c.public_url()}/paypal/return?vault=1",
            "cancel_url": f"{c.public_url()}/paypal/return?vault=1&cancel=1",
        },
    }}}
    if st.get("customer_id"):
        body["customer"] = {"id": st["customer_id"]}
    status, tok = pp.call(f"setup token (paypal, {usage_pattern})", "POST", "/v3/vault/setup-tokens", body,
                          request_id=c.request_id("spike", "s2", "setup", usage_pattern, str(int(c.time.time()))))
    if status >= 300:
        c.note("S2", f"FAIL setup token with usage_pattern={usage_pattern}: HTTP {status}")
        return
    cust = (tok.get("customer") or {}).get("id")
    c.save_state(s2_setup_token=tok["id"], s2_usage_pattern=usage_pattern, **({"customer_id": cust} if cust else {}))
    print(f"\nApprove as Maya (screenshot the consent text): {c.link(tok, 'approve', 'payer-action')}")
    print(f"Then run: python scripts/spike/02_vault_paypal.py finish {tok['id']}")


def finish(pp: c.PayPal, setup_token: str | None) -> None:
    st = c.load_state()
    setup_token = setup_token or st.get("s2_setup_token")
    if not setup_token:
        c.usage("no setup token: run `create` first")
    body = {"payment_source": {"token": {"id": setup_token, "type": "SETUP_TOKEN"}}}
    status, pt = pp.call("payment token from setup token", "POST", "/v3/vault/payment-tokens", body,
                         request_id=c.request_id("spike", "s2", "token", setup_token))
    if status >= 300:
        c.note("S2", f"FAIL payment token: HTTP {status}")
        return
    cust = (pt.get("customer") or {}).get("id") or st.get("customer_id")
    c.save_state(customer_id=cust, vault={"paypal-wallet": pt["id"]})
    c.note("S2", f"vault_id {pt['id']} for customer {cust} (usage_pattern={st.get('s2_usage_pattern')})")
    list_tokens(pp)


def list_tokens(pp: c.PayPal) -> None:
    cust = c.load_state().get("customer_id")
    if not cust:
        c.usage("no customer_id in state.json yet")
    status, lst = pp.call("list payment tokens", "GET", "/v3/vault/payment-tokens", params={"customer_id": cust})
    ids = [t.get("id") for t in (lst or {}).get("payment_tokens", [])]
    wallet = c.load_state().get("vault", {}).get("paypal-wallet")
    ok = status < 300 and wallet in ids
    c.note("S2", f"{'PASS' if ok else 'CHECK'} list for {cust}: {ids}")


def main() -> None:
    pp = c.PayPal("S2")
    a = c.args()
    if a[:1] == ["create"]:
        create(pp, _flag(a, "--usage-pattern", "IMMEDIATE"))
    elif a[:1] == ["finish"]:
        finish(pp, a[1] if len(a) > 1 and not a[1].startswith("--") else None)
    elif a[:1] == ["list"]:
        list_tokens(pp)
    else:
        c.usage(__doc__)


if __name__ == "__main__":
    main()
