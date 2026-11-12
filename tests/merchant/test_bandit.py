import random
import pytest

from merchant.engine.bandit import (
    BanditLearner,
    BetaDistribution,
    initial_prior,
)
from merchant.engine.economics import (
    ACTION_EFFECTIVENESS,
    MerchantPolicy,
    RecoveryAction,
)


def test_beta_distribution_properties():
    dist = BetaDistribution(alpha=8.0, beta=2.0)
    assert dist.mean == pytest.approx(0.8)
    assert dist.variance > 0


def test_beta_distribution_invalid():
    with pytest.raises(ValueError, match="positive"):
        BetaDistribution(alpha=0.0, beta=1.0)


def test_beta_update():
    dist = BetaDistribution(alpha=10.0, beta=10.0)
    assert dist.mean == pytest.approx(0.5)

    updated = dist.update(success=True)
    assert updated.alpha == 11.0
    assert updated.beta == 10.0
    assert updated.mean > 0.5

    failed = updated.update(success=False)
    assert failed.alpha == 11.0
    assert failed.beta == 11.0
    assert failed.mean == pytest.approx(0.5)


def test_initial_prior_matches_economics():
    fc = "INSUFFICIENT_FUNDS"
    action = RecoveryAction.ALTERNATE_FUNDING_OFFER
    expected_eff = ACTION_EFFECTIVENESS[fc][action]  # 0.80

    prior = initial_prior(fc, action, prior_weight=20.0)
    assert prior.mean == pytest.approx(expected_eff, abs=0.01)


def test_bandit_learner_record_outcome():
    learner = BanditLearner(prior_weight=10.0)
    fc = "INSUFFICIENT_FUNDS"
    action = RecoveryAction.RETRY_AFTER_OFFER

    initial_mean = learner.get_distribution(fc, action).mean

    # Success should increase expected recovery probability
    learner.record_outcome(fc, action, success=True)
    assert learner.get_distribution(fc, action).mean > initial_mean

    # Repeated failures should lower it
    for _ in range(5):
        learner.record_outcome(fc, action, success=False)
    assert learner.get_distribution(fc, action).mean < initial_mean


def test_bandit_exploration_policy_bounds():
    learner = BanditLearner()
    fc = "INSUFFICIENT_FUNDS"
    action = RecoveryAction.ALTERNATE_FUNDING_OFFER
    rng = random.Random(42)

    # 1. When exploration is 0.0, rate equals deterministic mean regardless of amount
    policy_no_explore = MerchantPolicy(explore_fraction=0.0)
    r1 = learner.effective_rate(fc, action, policy_no_explore, amount_minor=1000, rng=rng)
    assert r1 == pytest.approx(learner.get_distribution(fc, action).mean)

    # 2. When amount exceeds max_explore_amount_minor, exploration is suppressed
    policy_explore = MerchantPolicy(explore_fraction=0.5, max_explore_amount_minor=2000)
    r_high_value = learner.effective_rate(fc, action, policy_explore, amount_minor=5000, rng=rng)
    assert r_high_value == pytest.approx(learner.get_distribution(fc, action).mean)

    # 3. Below ceiling with exploration, sample is bounded in [0, 1]
    r_sampled = learner.effective_rate(fc, action, policy_explore, amount_minor=500, rng=rng)
    assert 0.0 <= r_sampled <= 1.0


def test_bandit_serialization():
    learner = BanditLearner(prior_weight=20.0)
    learner.record_outcome("INSUFFICIENT_FUNDS", RecoveryAction.ALTERNATE_FUNDING_OFFER, success=True)
    learner.record_outcome("INSTRUMENT_INVALID", RecoveryAction.PAYER_ACTION_OFFER, success=False)

    exported = learner.export_state()
    assert "INSUFFICIENT_FUNDS" in exported
    assert "ALTERNATE_FUNDING_OFFER" in exported["INSUFFICIENT_FUNDS"]

    serialized = learner.serialize_json()
    reconstituted = BanditLearner.from_json(serialized)
    assert reconstituted.get_distribution("INSUFFICIENT_FUNDS", RecoveryAction.ALTERNATE_FUNDING_OFFER).mean == pytest.approx(
        learner.get_distribution("INSUFFICIENT_FUNDS", RecoveryAction.ALTERNATE_FUNDING_OFFER).mean
    )
