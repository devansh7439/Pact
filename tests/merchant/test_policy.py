"""Policy engine: the demo scenarios (doc 01 §8) and the engine-side invariants (doc 08)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from merchant.engine.diagnosis import AIDiagnosis, apply
from merchant.engine.economics import OFFER_ACTIONS, MerchantPolicy, RecoveryAction, value_action
from merchant.engine.policy import (
    CANDIDATES,
    Channel,
    FundingSource,
    RecoveryContext,
    Verdict,
    decide,
)
from merchant.engine.taxonomy import ALL_ENTRIES, FailureClass, classify

A = RecoveryAction
CARD = FundingSource("primary-card", "CARD")
WALLET = FundingSource("paypal-wallet", "PAYPAL_WALLET")


def agent(**kw) -> RecoveryContext:
    base = dict(channel=Channel.AGENT, failed_funding_aliases=("primary-card",),
                funding_sources=(CARD, WALLET))
    return RecoveryContext(**{**base, **kw})


def human(**kw) -> RecoveryContext:
    return RecoveryContext(channel=Channel.HUMAN, **kw)


def row(decision, action):
    return next(r for r in decision.options if r.action is action)


# -- Demo scenarios -----------------------------------------------------------

def test_s1_autonomous_save_offers_the_wallet_not_the_failed_card():
    d = decide(classify("5120"), 3200, 0.95, agent())
    assert d.action is A.ALTERNATE_FUNDING_OFFER
    assert d.eligible_funding_aliases == ("paypal-wallet",)
    assert A.ALTERNATE_FUNDING_OFFER in d.offer_actions
    assert row(d, A.ALTERNATE_FUNDING_OFFER).verdict is Verdict.CHOSEN
    assert row(d, A.RETRY_SAME_INSTRUMENT).removed_by == "HARD_NO_SAME_INSTRUMENT"


def test_s2_suspected_fraud_offers_payer_action_only():
    d = decide(classify("9500"), 12000, 0.9, agent())
    assert d.action is A.PAYER_ACTION_OFFER
    assert d.offer_actions == (A.PAYER_ACTION_OFFER,)
    assert d.eligible_funding_aliases == ()
    for a in (A.ALTERNATE_FUNDING_OFFER, A.RETRY_AFTER_OFFER, A.RETRY_SAME_INSTRUMENT):
        assert row(d, a).removed_by == "HARD_RISK_NO_AUTONOMY"


def test_s3_second_decline_never_reoffers_either_failed_source():
    first = decide(classify("0500"), 2800, 0.9, agent())
    assert first.eligible_funding_aliases == ("paypal-wallet",)
    second = decide(classify("0500"), 2800, 0.9, agent(
        failed_funding_aliases=("primary-card", "paypal-wallet"), attempts_so_far=1))
    assert second.action is A.PAYER_ACTION_OFFER
    assert second.eligible_funding_aliases == ()
    assert row(second, A.ALTERNATE_FUNDING_OFFER).removed_by == "HARD_NO_SAME_INSTRUMENT"


def test_s4_four_dollar_add_on_is_dropped_with_the_arithmetic():
    d = decide(classify("5400"), 400, 0.8, human())
    assert d.action is A.DROP and d.rule_id == "ECON_BELOW_FLOOR"
    assert d.valuation is not None and "$" in d.rationale


def test_s6_human_save_sends_a_checkout_link():
    d = decide(classify("5100"), 4800, 0.8, human())
    assert d.action is A.CHECKOUT_LINK
    assert d.offer_actions == ()


# -- Hard constraints ---------------------------------------------------------

def test_already_paid_stops_everything():
    assert decide(classify(None, "ORDER_ALREADY_CAPTURED"), 3200, 0.9, agent()).rule_id == "HARD_ALREADY_PAID"
    assert decide(classify("5120"), 3200, 0.9, agent(already_recovered=True)).action is A.DROP


def test_undiagnosed_goes_to_exceptions():
    d = decide(classify("9999"), 3200, 0.9, agent())
    assert d.action is A.DROP and d.is_exception and d.rule_id == "HARD_UNDIAGNOSED"


def test_attempt_cap():
    d = decide(classify("5120"), 3200, 0.9, agent(attempts_so_far=2))
    assert d.rule_id == "HARD_ATTEMPT_CAP"


def test_unregistered_agent_gets_no_offer():
    d = decide(classify("5120"), 3200, 0.9, agent(agent_registered=False))
    assert d.action is A.DROP and d.offer_actions == ()


def test_high_value_escalates():
    d = decide(classify("5120"), 30_000, 0.9, agent())
    assert d.action is A.ESCALATE and d.rule_id == "HARD_HIGH_VALUE_ESCALATION"


def test_llm_diagnosis_gets_a_quarter_of_the_ceiling():
    llm = apply(classify("9999"), AIDiagnosis(FailureClass.INSUFFICIENT_FUNDS, 0.9, "short of funds", True))
    assert llm.diagnosed_by == "llm" and llm.retry_same_instrument is False
    assert decide(llm, 7_000, 0.9, agent()).rule_id == "HARD_HIGH_VALUE_ESCALATION"
    assert decide(llm, 5_000, 0.9, agent()).action is A.ALTERNATE_FUNDING_OFFER


def test_consent_invalid_removes_saved_source_options():
    revoked = FundingSource("paypal-wallet", "PAYPAL_WALLET", consent_valid=False)
    d = decide(classify("5120"), 3200, 0.95, agent(funding_sources=(CARD, revoked)))
    assert row(d, A.ALTERNATE_FUNDING_OFFER).removed_by == "HARD_CONSENT_INVALID"
    assert d.action is A.PAYER_ACTION_OFFER and d.eligible_funding_aliases == ()


def test_opt_out_blocks_human_contact_only():
    d = decide(classify("5100"), 4800, 0.8, human(customer_opted_out=True))
    assert row(d, A.CHECKOUT_LINK).removed_by == "HARD_OPT_OUT"
    assert d.action is not A.CHECKOUT_LINK


def test_contact_cooldown():
    d = decide(classify("5100"), 4800, 0.8, human(hours_since_last_contact=2.0))
    assert row(d, A.CHECKOUT_LINK).removed_by == "CONTACT_COOLDOWN"


def test_contact_cap_cannot_be_dodged_by_escalating():
    d = decide(classify("5100"), 20_000, 0.9, human(contacts_today=5))
    assert d.action is A.DROP
    assert row(d, A.ESCALATE).removed_by == "CONTACT_DAILY_CAP"
    # Config faults are an ops fix, not a customer contact: still escalated.
    cfg = decide(classify(None, "PAYEE_ACCOUNT_RESTRICTED"), 20_000, 0.9, human(contacts_today=5))
    assert cfg.action is A.ESCALATE


def test_merchant_config_only_escalates():
    d = decide(classify(None, "PAYEE_ACCOUNT_RESTRICTED"), 20_000, 0.9, human())
    assert d.action is A.ESCALATE


def test_kill_switch_records_but_blocks_execution():
    d = decide(classify("5120"), 3200, 0.95, agent(kill_switch_active=True))
    assert d.action is A.ALTERNATE_FUNDING_OFFER  # decided and recorded…
    assert d.execution_blocked_by == "HARD_KILL_SWITCH"  # …but not executed


def test_every_candidate_appears_in_the_table():
    for ctx in (agent(), human()):
        d = decide(classify("5120"), 3200, 0.9, ctx)
        assert {r.action for r in d.options} == set(CANDIDATES[ctx.channel]) | {A.DROP}
        assert all(r.removed_by or r.valuation for r in d.options if r.verdict is not Verdict.BASELINE)


def test_valuation_formula():
    v = value_action(A.ALTERNATE_FUNDING_OFFER, 3200, 0.95, "INSUFFICIENT_FUNDS")
    assert v.probability == pytest.approx(0.76) and v.organic_probability == pytest.approx(0.19)
    assert v.gross_expected_minor == round(3200 * 0.57)
    assert v.net_ev_minor == v.gross_expected_minor - v.fee_minor - v.cost_minor


# -- Property tests (doc 08) --------------------------------------------------

CODES = [e.code for e in ALL_ENTRIES] + ["9999", None]
aliases = st.sampled_from(["primary-card", "paypal-wallet", "backup-card"])
sources = st.lists(st.builds(FundingSource, aliases, st.sampled_from(["CARD", "PAYPAL_WALLET"]),
                             st.booleans()), max_size=3, unique_by=lambda s: s.alias)
contexts = st.builds(
    RecoveryContext,
    channel=st.sampled_from(list(Channel)),
    failed_funding_aliases=st.lists(aliases, max_size=2, unique=True).map(tuple),
    funding_sources=sources.map(tuple),
    agent_registered=st.booleans(),
    attempts_so_far=st.integers(0, 3),
    contacts_today=st.integers(0, 3),
    customer_opted_out=st.booleans(),
)
signals = st.sampled_from(CODES).map(
    lambda c: classify(c) if c is None or c[0].isdigit() else classify(None, c))
amounts = st.integers(1, 60_000)
props = st.floats(0.0, 1.0)


@settings(max_examples=400)
@given(signals, amounts, props, contexts)
def test_no_same_instrument_after_hard_decline(c, amount, p, ctx):
    """I2: with retry disallowed, no offered alias is one that already failed."""
    d = decide(c, amount, p, ctx)
    if not c.retry_same_instrument:
        assert not set(d.eligible_funding_aliases) & set(ctx.failed_funding_aliases)
        assert d.action is not A.RETRY_SAME_INSTRUMENT


@settings(max_examples=400)
@given(st.sampled_from(["9500", "9520"]), amounts, props, contexts)
def test_risk_never_autonomous(code, amount, p, ctx):
    """I3: RISK_BLOCKED never yields an autonomous attempt on a saved source."""
    d = decide(classify(code), amount, p, ctx)
    assert d.action not in (A.ALTERNATE_FUNDING_OFFER, A.RETRY_AFTER_OFFER, A.RETRY_SAME_INSTRUMENT,
                            A.CHECKOUT_LINK)
    assert set(d.offer_actions) <= {A.PAYER_ACTION_OFFER}
    assert d.eligible_funding_aliases == ()


@settings(max_examples=400)
@given(signals, amounts, props, contexts)
def test_offered_aliases_are_consented(c, amount, p, ctx):
    d = decide(c, amount, p, ctx)
    valid = {s.alias for s in ctx.funding_sources if s.consent_valid}
    assert set(d.eligible_funding_aliases) <= valid
    assert set(d.offer_actions) <= OFFER_ACTIONS
    if d.offer_actions:
        assert ctx.channel is Channel.AGENT


TERMINAL = [
    ("5120", dict(already_recovered=True)),
    ("9999", {}),
    ("5120", dict(attempts_so_far=5)),
    ("5120", dict(agent_registered=False)),
]


@pytest.mark.parametrize("code,kw", TERMINAL)
def test_constraints_before_score(code, kw):
    """I12: terminal hard constraints resolve without ever reading the score."""
    def exploding(_fc, _a):
        raise AssertionError("score read before hard constraints")
    d = decide(classify(code), 3200, 0.9, agent(**kw), effectiveness_for=exploding)
    assert d.action is A.DROP


def test_high_value_resolves_before_score():
    def exploding(_fc, _a):
        raise AssertionError("score read before hard constraints")
    assert decide(classify("5120"), 99_999, 0.9, agent(), MerchantPolicy(),
                  effectiveness_for=exploding).action is A.ESCALATE
