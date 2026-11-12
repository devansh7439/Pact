"""S6 · Recovery with an alternate source + idempotency (doc 09).

    python scripts/spike/06_recover_alternate.py

After S5's decline, pays the same $32.00 with the saved PayPal wallet, using a
PayPal-Request-Id derived from a fake (offer_id, option_id) exactly as the
merchant's accept path does (doc 03 §5). Then sends the identical request again.

Pass when: the first call COMPLETES and the repeat returns the same order id
(no second order, no second capture).
"""

from __future__ import annotations

import importlib

import _common as c

charge_mod = importlib.import_module("04_charge_vaulted")


def main() -> None:
    pp = c.PayPal("S6")
    st = c.load_state()
    vid = st.get("vault", {}).get("paypal-wallet")
    if not vid:
        c.usage("no paypal-wallet vault_id — run 02_vault_paypal.py first")
    fake_offer = st.get("s6_fake_offer") or f"off_SPIKE{int(c.time.time())}"
    c.save_state(s6_fake_offer=fake_offer)
    rid = c.request_id("acc", fake_offer, "opt_alt")

    first = charge_mod.charge(pp, "S6", "alternate funding (wallet)", charge_mod.wallet_source(vid), rid)
    second = charge_mod.charge(pp, "S6", "alternate funding REPLAY (same request id)", charge_mod.wallet_source(vid), rid)

    ok = (first.get("capture_status") == "COMPLETED"
          and first.get("order_id") and first.get("order_id") == second.get("order_id"))
    c.note("S6", f"{'PASS' if ok else 'FAIL'} request id {rid}: first={first.get('order_id')}/"
                 f"{first.get('capture_status')} replay={second.get('order_id')}/{second.get('capture_status')} "
                 f"(replay http {second.get('http')})")


if __name__ == "__main__":
    main()
