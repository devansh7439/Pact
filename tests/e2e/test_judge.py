"""Judge mode end to end: seed exactly as scripts/seed.py does, then run every
scenario a judge can click, against both real services (fixture PayPal)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from buyer_agent.app import create_app as create_buyer
from buyer_agent.db import BuyerDB
from merchant.app import create_app as create_merchant
from merchant.config import Settings
from merchant.db import Database
from merchant.paypal import FixturePayPal
from merchant.service import MerchantService
from scripts.seed import MAYA_MANDATE, seed
from shared.prp import keys

MERCHANT = "http://merchant.test"


@pytest.fixture
def judge(tmp_path):
    cfg = Settings(_env_file=None, merchant_db_path=tmp_path / "m.db", judge_mode=True,
                   holdout_rate=0.0, llm_api_key="", paypal_client_id="")
    svc = MerchantService(cfg, Database(cfg.merchant_db_path), FixturePayPal(),
                          predict=lambda events: [0.9 for _ in events])
    merchant_app = create_merchant(svc, cfg=cfg)
    to_merchant = httpx.AsyncClient(transport=httpx.ASGITransport(app=merchant_app), base_url=MERCHANT)
    buyer_key = keys.private_to_b64(keys.generate())     # fixed, like BUYER_SIGNING_KEY in prod
    buyer = TestClient(create_buyer(db=BuyerDB(tmp_path / "b.db"), http=to_merchant,
                                    signing_key_b64=buyer_key))
    merchant_app.state.judge.buyer = buyer
    merchant = TestClient(merchant_app)
    seed(merchant, buyer, merchant_base_url=MERCHANT)
    merchant.buyer_key = buyer_key
    return merchant, buyer, svc


def outcome(svc, intent_id):
    row = svc.db.one("SELECT outcome FROM outcomes WHERE intent_id=?", (intent_id,))
    return row["outcome"] if row else None


def test_seed_registered_and_approved_maya(judge):
    merchant, buyer, svc = judge
    reg = svc.db.one("SELECT status FROM agent_registrations")
    assert reg["status"] == "ACTIVE"
    assert svc.db.one("SELECT mandate_id FROM registered_mandates")["mandate_id"] == MAYA_MANDATE["mandate_id"]
    assert merchant.get("/console/controls").json()["mode"] == "autonomous"


@pytest.mark.parametrize("scenario,expected", [
    ("S1", "RECOVERED"), ("S2", None), ("S3", None), ("S4", None), ("S6", None)])
def test_each_scenario_runs_and_links(judge, scenario, expected):
    merchant, _buyer, svc = judge
    r = merchant.post(f"/judge/scenarios/{scenario}/run")
    assert r.status_code == 200, r.text
    intent_id = r.json()["intent_id"]
    assert intent_id
    assert outcome(svc, intent_id) == expected
    linked = merchant.get(f"/judge/linked/{intent_id}").json()
    assert linked["merchant"]["decisions"], "every scenario declines and is decided"
    assert linked["timeline"]
    if r.json()["channel"] == "agent":
        assert linked["buyer"] and linked["buyer"]["guard_decisions"]


def test_s4_drops_and_s6_sends_arjun_a_link(judge):
    merchant, _buyer, svc = judge
    s4 = merchant.post("/judge/scenarios/S4/run").json()
    assert s4["result"]["action"] == "DROP"
    s6 = merchant.post("/judge/scenarios/S6/run").json()
    assert s6["result"]["action"] == "CHECKOUT_LINK" and s6["result"]["approve_url"]
    inbox = merchant.get("/store/customers/cus_arjun_demo/inbox").json()
    assert inbox and inbox[0]["approve_url"] == s6["result"]["approve_url"]
    assert "$48.00" in inbox[0]["message_text"]


def test_reset_clears_both_sides_and_scenarios_rerun(judge):
    merchant, buyer, svc = judge
    first = merchant.post("/judge/scenarios/S1/run").json()["intent_id"]
    assert merchant.post("/judge/reset").json()["ok"] is True
    assert svc.db.one("SELECT COUNT(*) n FROM payment_intents")["n"] == 0
    assert buyer.get("/buyer/purchases").json() == []
    again = merchant.post("/judge/scenarios/S1/run").json()["intent_id"]
    assert again != first and outcome(svc, again) == "RECOVERED"


def test_reseed_after_buyer_cold_start(judge, tmp_path):
    """Render free tier: the buyer wakes with an empty DB (same key) while the merchant
    still has Maya ACTIVE. Seeding again must work (pact-f3's deploy blocker)."""
    merchant, _old_buyer, svc = judge
    assert svc.db.one("SELECT status FROM agent_registrations")["status"] == "ACTIVE"
    to_merchant = httpx.AsyncClient(transport=httpx.ASGITransport(app=merchant.app),
                                    base_url=MERCHANT)
    fresh = TestClient(create_buyer(db=BuyerDB(tmp_path / "fresh.db"), http=to_merchant,
                                    signing_key_b64=merchant.buyer_key))
    merchant.app.state.judge.buyer = fresh
    seed(merchant, fresh, merchant_base_url=MERCHANT)
    r = merchant.post("/judge/scenarios/S1/run")
    assert r.status_code == 200 and outcome(svc, r.json()["intent_id"]) == "RECOVERED"


def test_seed_twice_is_idempotent(judge):
    merchant, buyer, _svc = judge
    seed(merchant, buyer, merchant_base_url=MERCHANT)       # second run must not fail
    assert merchant.post("/judge/scenarios/S1/run").status_code == 200


def test_judge_runs_are_exempt_from_the_holdout(judge):
    """pact-f3: at HOLDOUT_RATE 0.10, ~1 in 10 S1 clicks were held out and 'failed'.
    Scripted runs are exempt (and say so in the audit); real traffic is not."""
    merchant, _buyer, svc = judge
    merchant.post("/console/controls", json={"holdout_rate": "0.5"})
    for _ in range(10):
        r = merchant.post("/judge/scenarios/S1/run").json()
        assert outcome(svc, r["intent_id"]) == "RECOVERED"
        holdout_row = svc.db.one("SELECT payload_json FROM audit_trail WHERE intent_id=? AND stage='HOLDOUT'",
                                 (r["intent_id"],))["payload_json"]
        assert '"exempt":"judge_scripted"' in holdout_row
        merchant.post("/judge/reset")
    from merchant.db import get_control
    assert get_control(svc.db, "judge_scripted_customer", "") == ""   # flag cleared after runs


def test_judge_runs_do_not_count_in_holdout_lift(judge):
    """pact-e4: exempt runs must not inflate the 'acted' arm of the lift."""
    merchant, _buyer, svc = judge
    for _ in range(3):
        merchant.post("/judge/scenarios/S1/run")
    holdout = merchant.get("/console/metrics?provenance=fixture").json()["by_provenance"]["fixture"]["holdout"]
    assert holdout["acted"]["n"] == 0 and holdout["held_out"]["n"] == 0
    ledger = merchant.get("/console/ledger").json()
    assert ledger and all(row["judge_scripted"] for row in ledger)


def test_judge_endpoints_are_off_outside_judge_mode(tmp_path):
    cfg = Settings(_env_file=None, merchant_db_path=tmp_path / "m.db", judge_mode=False)
    svc = MerchantService(cfg, Database(cfg.merchant_db_path), FixturePayPal())
    client = TestClient(create_merchant(svc, cfg=cfg))
    assert client.post("/judge/reset").status_code == 403
