"""S5 / S5b · Decline on a saved card (doc 09).

    python scripts/spike/05_decline.py                 # S5: charge card-if (CCREJECT-IF)
    python scripts/spike/05_decline.py --alias card-sf # other triggers: card-sf, card-refused, card-ec
    python scripts/spike/05_decline.py mock            # S5b: negative testing on the clean card

S5 passes when the capture is DECLINED with processor_response.response_code 5120
(or the trigger's code). S5b passes when PayPal returns 422 INSTRUMENT_DECLINED
under `PayPal-Mock-Response` (negative testing must be enabled on the sandbox
business account; doc 04 §2 step 4).
"""

from __future__ import annotations

import importlib
import json

import _common as c

charge_mod = importlib.import_module("04_charge_vaulted")

EXPECTED = {"card-if": "5120", "card-sf": "9500", "card-refused": "0500", "card-ec": "5400"}


def _flag(a: list[str], name: str, default: str) -> str:
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def s5(pp: c.PayPal, alias: str, encoding: str) -> None:
    vid = c.load_state().get("vault", {}).get(alias)
    if not vid:
        c.usage(f"no vault_id for {alias!r} — run 03_vault_cards.py first")
    s = charge_mod.charge(pp, "S5", f"declining card {alias}", charge_mod.card_source(vid, encoding),
                          c.request_id("spike", "s5", alias, str(int(c.time.time()))))
    code = (s.get("processor_response") or {}).get("response_code")
    want = EXPECTED.get(alias)
    ok = s.get("capture_status") == "DECLINED" and (want is None or code == want)
    c.save_state(s5={alias: {"order_id": s.get("order_id"), "response_code": code, "issue": s.get("issue")}})
    c.note("S5", f"{'PASS' if ok else 'FAIL'} {alias}: capture_status={s.get('capture_status')} "
                 f"response_code={code} (want {want}) issue={s.get('issue')} http={s.get('http')}")


def s5b(pp: c.PayPal, encoding: str) -> None:
    vid = c.load_state().get("vault", {}).get("card-clean")
    if not vid:
        c.usage("no vault_id for card-clean — run 03_vault_cards.py first")
    mock = {"PayPal-Mock-Response": json.dumps({"mock_application_codes": "INSTRUMENT_DECLINED"})}
    s = charge_mod.charge(pp, "S5b", "negative-testing decline", charge_mod.card_source(vid, encoding),
                          c.request_id("spike", "s5b", str(int(c.time.time()))), extra_headers=mock)
    ok = s.get("http") == 422 and s.get("issue") == "INSTRUMENT_DECLINED"
    c.note("S5b", f"{'PASS' if ok else 'FAIL'} mock decline: http={s.get('http')} issue={s.get('issue')}")


def main() -> None:
    pp = c.PayPal("S5")
    a = c.args()
    enc = _flag(a, "--encoding", "A")
    if a[:1] == ["mock"]:
        s5b(pp, enc)
    elif not a or a[0].startswith("--"):
        s5(pp, _flag(a, "--alias", "card-if"), enc)
    else:
        c.usage(__doc__)


if __name__ == "__main__":
    main()
