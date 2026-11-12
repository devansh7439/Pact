"""S3 · Save sandbox cards whose name triggers a decline (doc 09; doc 04 §4).

    python scripts/spike/03_vault_cards.py

Vaults test card 4012 8888 8888 1881 once per trigger name, plus one clean card,
for the customer from S2 (or a new one). Aliases match the demo (doc 04 "demo trick").
Pass when: every card gets a vault_id. Whether the trigger survives vaulting is
checked by S5 (05_decline.py).

If a setup token comes back needing payer action (3DS), its approve link is
printed: approve it, then rerun with `finish ALIAS`.
"""

from __future__ import annotations

import _common as c

CARDS = {
    "card-if": "CCREJECT-IF",            # 5120 INSUFFICIENT_FUNDS  -> S1
    "card-sf": "CCREJECT-SF",            # 9500 SUSPECTED_FRAUD     -> S2
    "card-refused": "CCREJECT-REFUSED",  # 0500 DO_NOT_HONOR        -> S3
    "card-ec": "CCREJECT-EC",            # 5400 EXPIRED_CARD        -> S4
    "card-clean": "Maya Sandbox",        # approves                 -> S4 / S4b
}


def vault_card(pp: c.PayPal, alias: str, name: str) -> None:
    st = c.load_state()
    body: dict = {"payment_source": {"card": {
        "number": c.TEST_CARD,
        "expiry": c.TEST_EXPIRY,
        "security_code": c.TEST_CVV,
        "name": name,
        "experience_context": {
            "return_url": f"{c.public_url()}/paypal/return?vault=card",
            "cancel_url": f"{c.public_url()}/paypal/return?vault=card&cancel=1",
        },
    }}}
    if st.get("customer_id"):
        body["customer"] = {"id": st["customer_id"]}
    status, tok = pp.call(f"setup token (card {alias})", "POST", "/v3/vault/setup-tokens", body,
                          request_id=c.request_id("spike", "s3", "setup", alias, str(int(c.time.time()))))
    if status >= 300:
        c.note("S3", f"FAIL setup token {alias}: HTTP {status}")
        return
    cust = (tok.get("customer") or {}).get("id")
    if cust and not st.get("customer_id"):
        c.save_state(customer_id=cust)
    c.save_state(s3_setup={alias: tok["id"]})
    approve = c.link(tok, "approve", "payer-action")
    if tok.get("status") not in (None, "APPROVED", "VAULTED") and approve:
        print(f"{alias}: needs approval -> {approve}\n  then: python scripts/spike/03_vault_cards.py finish {alias}")
        return
    finish(pp, alias)


def finish(pp: c.PayPal, alias: str) -> None:
    setup = c.load_state().get("s3_setup", {}).get(alias)
    if not setup:
        c.usage(f"no setup token for {alias}")
    status, pt = pp.call(f"payment token (card {alias})", "POST", "/v3/vault/payment-tokens",
                         {"payment_source": {"token": {"id": setup, "type": "SETUP_TOKEN"}}},
                         request_id=c.request_id("spike", "s3", "token", setup))
    if status >= 300:
        c.note("S3", f"FAIL payment token {alias}: HTTP {status}")
        return
    c.save_state(vault={alias: pt["id"]})
    c.note("S3", f"PASS {alias} ({CARDS.get(alias)}) -> vault_id {pt['id']}")


def main() -> None:
    pp = c.PayPal("S3")
    a = c.args()
    if a[:1] == ["finish"] and len(a) > 1:
        finish(pp, a[1])
    elif not a:
        for alias, name in CARDS.items():
            vault_card(pp, alias, name)
    else:
        c.usage(__doc__)


if __name__ == "__main__":
    main()
