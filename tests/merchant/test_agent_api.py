"""Merchant agent API end to end (fixture PayPal), plus invariants I1, I4, I8, I9, I10, I13, I16."""

from __future__ import annotations

import json
from datetime import timedelta

from shared.prp import keys
from shared.prp.models import RecoveryOffer


def body(r) -> dict:
    return json.loads(r.content)


def later(world, minutes: int) -> None:
    world.clock.t += timedelta(minutes=minutes)


def first_offer(world, trigger="CCREJECT-IF", **kw):
    world.onboard(card_trigger=trigger, **kw)
    r = world.agent.checkout()
    assert r.status_code == 402, r.text
    return body(r)


# -- Demo scenarios through the API -----------------------------------------------

def test_s1_autonomous_recovery_end_to_end(world):
    offer = first_offer(world)
    RecoveryOffer.model_validate(offer)                         # schema-valid, as signed
    assert offer["failure"]["class"] == "INSUFFICIENT_FUNDS"
    assert offer["failure"]["paypal"]["processor_response_code"] == "5120"
    alt = next(o for o in offer["options"] if o["kind"] == "ALTERNATE_FUNDING")
    assert alt["eligible_funding_aliases"] == ["paypal-wallet"]
    r = world.agent.accept(offer, alt["option_id"], "paypal-wallet")
    assert r.status_code == 200 and body(r)["status"] == "COMPLETED"
    out = world.svc.db.one("SELECT * FROM outcomes WHERE intent_id=?", (offer["intent_id"],))
    assert out["outcome"] == "RECOVERED" and out["recovered_minor"] == 3200


def test_s2_fraud_offers_payer_action_only_and_returns_approve_link(world):
    offer = first_offer(world, trigger="CCREJECT-SF")
    assert {o["kind"] for o in offer["options"]} == {"PAYER_ACTION", "CANCEL"}
    r = world.agent.accept(offer, "opt_payer")
    assert r.status_code == 202 and body(r)["approve_url"].startswith("https://")
    # The human approves on PayPal; the webhook-or-return path captures it.
    order_id = world.svc.db.one("SELECT paypal_order_id FROM attempts WHERE request_id LIKE 'acc_%'")[0]
    world.paypal.approve(order_id)
    assert world.svc.capture_approved(order_id, "api")[1]["status"] == "COMPLETED"
    out = world.svc.db.one("SELECT outcome FROM outcomes WHERE intent_id=?", (offer["intent_id"],))
    assert out["outcome"] == "RECOVERED_BY_HUMAN"


def test_s3_second_decline_gets_a_new_offer_without_either_failed_source(world):
    offer = first_offer(world, trigger="CCREJECT-REFUSED")
    world.paypal.force_decline("vault_wallet", "0500")           # sandbox negative-testing stand-in
    r = world.agent.accept(offer, "opt_alt", "paypal-wallet")
    assert r.status_code == 402
    second = body(r)
    assert second["offer_id"] != offer["offer_id"]
    for o in second["options"]:
        assert "primary-card" not in o.get("eligible_funding_aliases", [])
        assert "paypal-wallet" not in o.get("eligible_funding_aliases", [])
    assert {o["kind"] for o in second["options"]} <= {"PAYER_ACTION", "CANCEL"}
    first_row = world.svc.db.one("SELECT status FROM offers WHERE offer_id=?", (offer["offer_id"],))
    assert first_row["status"] == "ACCEPTED"


def test_onboarding_through_the_approve_link(world):
    """Follow the page flow a human takes: vault -> GET approve_url -> confirm."""
    from urllib.parse import urlsplit
    token = world.agent.register().json()["approval_url"].rsplit("/", 1)[1]
    assert world.client.post(f"/onboard/{token}/confirm").status_code == 409   # nothing saved yet
    for alias in ("primary-card", "paypal-wallet"):
        r = world.client.post(f"/onboard/{token}/vault/paypal", json={"alias": alias})
        assert r.status_code == 200
        link = urlsplit(r.json()["approve_url"])
        back = world.client.get(f"{link.path}?{link.query}")
        assert back.status_code == 200, back.text
    page = world.client.get(f"/onboard/{token}").json()
    assert {s["alias"] for s in page["saved_funding"]} == {"primary-card", "paypal-wallet"}
    assert page["missing_funding"] == []
    r = world.client.post(f"/onboard/{token}/confirm", json={"payer_id": "SANDBOXPAYER123"})
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    assert world.agent.checkout().status_code == 200          # the saved card works


def test_successful_checkout_is_a_plain_receipt(world):
    world.onboard(card_trigger=None)
    r = world.agent.checkout()
    assert r.status_code == 200 and body(r)["status"] == "COMPLETED"


# -- Caps: the merchant's copy of the mandate --------------------------------------

def test_merchant_rechecks_caps(world):
    world.onboard(card_trigger=None)
    assert world.agent.checkout("grinder-burr", key="k2").status_code == 403       # over cap
    assert world.agent.checkout(amount=100, key="k3").status_code == 422             # wrong price
    assert world.agent.checkout(alias="stolen-card", key="k4").status_code == 403    # not in mandate
    assert world.agent.checkout(key="k5").status_code == 200
    r = world.agent.checkout("beans-ethiopia-1kg", key="k6")                          # $64 > $60/week
    assert r.status_code == 403 and "budget" in body(r)["error"]["message"]


# -- Signatures -----------------------------------------------------------------------

def test_bad_signature_is_rejected_and_logged(world):
    world.onboard()
    r = world.agent.call("POST", "/agent/v1/checkout", {"x": 1}, key=keys.generate())
    assert r.status_code == 401 and body(r)["error"]["code"] == "BAD_SIGNATURE"
    assert world.svc.db.one("SELECT kind FROM security_events")["kind"] == "BAD_SIGNATURE"


def test_replayed_request_is_rejected(world):
    world.onboard(card_trigger=None)
    from shared.prp import signing
    msg = signing.sign(world.agent.key, world.agent.key_id, "GET", "/agent/v1/intents/pi_01JD4JNOPE0000")
    assert world.client.get("/agent/v1/intents/pi_01JD4JNOPE0000", headers=msg.headers).status_code == 404
    r = world.client.get("/agent/v1/intents/pi_01JD4JNOPE0000", headers=msg.headers)
    assert r.status_code == 409 and body(r)["error"]["code"] == "REPLAYED_NONCE"


# -- Invariants (doc 08) ---------------------------------------------------------------

def test_offer_amount_immutable(world):
    """I4: an offer's amount equals its intent's amount."""
    offer = first_offer(world)
    intent = world.svc.db.one("SELECT amount_minor, currency_code FROM payment_intents WHERE intent_id=?",
                              (offer["intent_id"],))
    assert offer["amount"] == {"currency_code": intent["currency_code"],
                               "value_minor": intent["amount_minor"]}


def test_accept_idempotent(world):
    """I8: N identical accepts -> one PayPal order, same response."""
    offer = first_offer(world)
    responses = [world.agent.accept(offer, "opt_alt", "paypal-wallet") for _ in range(4)]
    assert {r.status_code for r in responses} == {200}
    assert len({body(r)["paypal_order_id"] for r in responses}) == 1
    n = world.svc.db.one("SELECT COUNT(*) n FROM attempts WHERE request_id LIKE 'acc_%'")["n"]
    assert n == 1


def test_second_option_after_accept_is_refused(world):
    offer = first_offer(world)
    assert world.agent.accept(offer, "opt_alt", "paypal-wallet").status_code == 200
    r = world.agent.accept(offer, "opt_cancel")
    assert r.status_code == 409 and body(r)["error"]["code"] == "OFFER_ALREADY_ACCEPTED"


def test_expired_offer_inert(world):
    """I9: an expired offer creates nothing."""
    offer = first_offer(world)
    before = world.paypal.write_calls
    later(world, 16)
    r = world.agent.accept(offer, "opt_alt", "paypal-wallet")
    assert r.status_code == 410 and body(r)["error"]["code"] == "OFFER_EXPIRED"
    assert world.paypal.write_calls == before


def test_failed_alias_is_refused_on_accept(world):
    offer = first_offer(world)
    r = world.agent.accept(offer, "opt_alt", "primary-card")
    assert r.status_code == 422 and body(r)["error"]["code"] == "ALIAS_NOT_ALLOWED"


def test_kill_switch_blocks_writes(world):
    """I10: kill switch on -> zero PayPal write calls."""
    offer = first_offer(world)
    world.svc.set_controls({"kill_switch": "on"})
    before = world.paypal.write_calls
    assert world.agent.accept(offer, "opt_alt", "paypal-wallet").status_code == 503
    assert world.agent.accept(offer, "opt_payer").status_code == 503
    assert world.agent.checkout(key="k9").status_code == 503
    assert world.svc.reconcile(older_than_s=0)["captured"] == 0
    assert world.paypal.write_calls == before


def test_consent_checked_at_call_time(world):
    """I16: revoking the saved method between accept checks and the call -> no call."""
    offer = first_offer(world)
    from merchant.engine.executor import ExecutionBlocked
    import pytest
    with world.svc.db.tx() as conn:
        conn.execute("UPDATE funding_sources SET status='REVOKED' WHERE alias='paypal-wallet'")
    before = world.paypal.write_calls
    with pytest.raises(ExecutionBlocked) as exc:
        world.svc.executor.charge(offer["intent_id"], "paypal-wallet", "acc_direct_call")
    assert exc.value.code == "CONSENT_INVALID"
    assert world.paypal.write_calls == before
    r = world.agent.accept(offer, "opt_alt", "paypal-wallet")
    assert r.status_code == 403 and body(r)["error"]["code"] == "CONSENT_INVALID"


def test_single_capture_per_intent(world):
    """I1: webhook + poll + return racing on one approved order -> one capture, one outcome."""
    offer = first_offer(world, trigger="CCREJECT-SF")
    world.agent.accept(offer, "opt_payer")
    order_id = world.svc.db.one("SELECT paypal_order_id FROM attempts WHERE request_id LIKE 'acc_%'")[0]
    world.paypal.approve(order_id)
    for source in ("webhook", "poll", "api", "webhook"):
        world.svc.capture_approved(order_id, source)
    world.svc.reconcile(older_than_s=0)
    assert world.svc.db.one("SELECT COUNT(*) n FROM outcomes WHERE intent_id=?",
                            (offer["intent_id"],))["n"] == 1
    caps = {v.capture_id for v in world.paypal.by_request.values() if v.paid}
    assert len(caps) == 1


def test_audit_completeness(world):
    """I13: every engine stage writes exactly one audit row per failure."""
    offer = first_offer(world)
    stages = world.audit_stages(offer["intent_id"])
    for stage in ("INGEST", "DIAGNOSE", "SCORE", "DECIDE", "HOLDOUT", "ACT"):
        assert stages.count(stage) == 1, (stage, stages)
    world.agent.accept(offer, "opt_alt", "paypal-wallet")
    stages = world.audit_stages(offer["intent_id"])
    assert stages.count("VERIFY") == 1 and stages.count("MEASURE") == 1


def test_audit_trail_is_append_only(world):
    import sqlite3
    import pytest
    world.onboard()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with world.svc.db.tx() as conn:
            conn.execute("UPDATE audit_trail SET stage='X'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with world.svc.db.tx() as conn:
            conn.execute("DELETE FROM audit_trail")


def test_review_first_queues_the_charge_until_approved(world):
    offer = first_offer(world)
    world.svc.set_controls({"mode": "review_first"})
    r = world.agent.accept(offer, "opt_alt", "paypal-wallet")
    assert r.status_code == 202 and body(r)["status"] == "PENDING_REVIEW"
    assert not world.svc.db.one("SELECT 1 FROM outcomes WHERE intent_id=?", (offer["intent_id"],))
    queue = world.svc.review_queue()
    assert len(queue) == 1
    status, res = world.svc.review(queue[0]["decision_id"], approve=True)
    assert status == 200 and res["status"] == "COMPLETED"
    assert world.svc.db.one("SELECT outcome FROM outcomes WHERE intent_id=?",
                            (offer["intent_id"],))["outcome"] == "RECOVERED"
