import pytest

from merchant.engine.economics import RecoveryAction
from merchant.engine.holdout import apply, assigned_to_holdout, lift_report, wilson
from merchant.engine.policy import Channel, FundingSource, RecoveryContext, decide
from merchant.engine.taxonomy import classify

CTX = RecoveryContext(channel=Channel.AGENT, failed_funding_aliases=("primary-card",),
                      funding_sources=(FundingSource("primary-card", "CARD"),
                                       FundingSource("paypal-wallet", "PAYPAL_WALLET")))


def test_assignment_is_deterministic_and_near_the_rate():
    ids = [f"pi_{i:08d}" for i in range(20_000)]
    first = [assigned_to_holdout(i, "salt", 0.10) for i in ids]
    assert first == [assigned_to_holdout(i, "salt", 0.10) for i in ids]
    assert 0.09 < sum(first) / len(ids) < 0.11


def test_salt_changes_assignment():
    ids = [f"pi_{i}" for i in range(2000)]
    assert [assigned_to_holdout(i, "a", 0.1) for i in ids] != [assigned_to_holdout(i, "b", 0.1) for i in ids]


def test_rate_zero_never_holds_out():
    assert not any(assigned_to_holdout(f"pi_{i}", "s", 0.0) for i in range(1000))


def _held_out_id(salt="s"):
    return next(f"pi_{i}" for i in range(10_000) if assigned_to_holdout(f"pi_{i}", salt, 0.1))


def test_holdout_inert():
    """I14: a held-out intent receives no action and no offer."""
    c = classify("5120")
    d = decide(c, 3200, 0.95, CTX)
    held, was_held = apply(d, c, _held_out_id(), 3200, salt="s", rate=0.1,
                           autonomy_ceiling_minor=25_000)
    assert was_held
    assert held.action is RecoveryAction.DROP and held.rule_id == "HELD_OUT"
    assert held.offer_actions == () and held.eligible_funding_aliases == ()
    assert "ALTERNATE_FUNDING_OFFER" in held.rationale


def test_risk_and_drops_are_never_held_out():
    human = RecoveryContext(channel=Channel.HUMAN)
    for code, amount, ctx in (("9500", 3200, CTX), ("5400", 400, human)):
        c = classify(code)
        d = decide(c, amount, 0.9, ctx)
        assert d.action is not RecoveryAction.ALTERNATE_FUNDING_OFFER
        _, was_held = apply(d, c, _held_out_id(), amount, salt="s", rate=0.1,
                            autonomy_ceiling_minor=25_000)
        assert not was_held


def test_wilson_interval():
    iv = wilson(50, 100)
    assert iv.rate == 0.5 and iv.low == pytest.approx(0.4038, abs=1e-3)
    assert iv.high == pytest.approx(0.5962, abs=1e-3)
    assert wilson(0, 0).n == 0


def test_small_samples_say_not_enough_data():
    r = lift_report(5, 10, 1, 4).to_dict()
    assert r["enough_data"] is False and r["lift"] is None and r["message"] == "not enough data yet"
    big = lift_report(60, 100, 30, 100)
    assert big.enough_data and big.lift == pytest.approx(0.30)
