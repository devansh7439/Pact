from merchant.engine.economics import RecoveryAction
from merchant.ml.features import ALL_FEATURES, extract
from merchant.simulator.generate import generate_events, stream_events
from merchant.simulator.oracle import observe, observe_do_nothing


def test_generation_is_reproducible():
    a = generate_events(300, seed=1)
    b = generate_events(300, seed=1)
    assert [e.id for e in a] == [e.id for e in b]
    assert [e.id for e in generate_events(300, seed=2)] != [e.id for e in a]


def test_events_look_like_paypal_declines():
    events = generate_events(2000, seed=3)
    assert all(e.currency == "USD" and isinstance(e.amount, int) and e.amount >= 100 for e in events)
    assert {e.channel for e in events} == {"agent", "human"}
    assert any(e.processor_response_code for e in events)
    assert any(e.issue for e in events)
    # The exception path is exercised by data, not only by unit tests.
    assert any(e.processor_response_code is None and e.issue is None for e in events)


def test_latent_truth_never_reaches_features():
    e = generate_events(10, seed=4)[0]
    assert not any(k.startswith("_") for k in e.features())
    row = extract(e)
    assert set(row) == set(ALL_FEATURES)
    assert not any("true" in k for k in row)


def test_stream_is_lazy():
    gen = stream_events(10**9, seed=5)
    assert next(gen).id.startswith("pi_")


def test_oracle_is_paired_and_monotone():
    for e in generate_events(1500, seed=6):
        fc = "INSUFFICIENT_FUNDS"
        organic = observe_do_nothing(e, fc)
        acted = observe(e, RecoveryAction.PAYER_ACTION_OFFER, fc)
        # Common random numbers: an intervention never un-recovers an organic payer.
        assert not (organic.recovered and not acted.recovered)
        assert acted.incremental_minor in (0, e.amount)
        if organic.recovered:
            assert acted.incremental_minor == 0


def test_alternate_funding_needs_an_alternate():
    for e in generate_events(500, seed=7):
        if e.alternate_funding_count == 0:
            o = observe(e, RecoveryAction.ALTERNATE_FUNDING_OFFER, "INSUFFICIENT_FUNDS")
            assert o.p_action == o.p_organic


def test_already_paid_is_unrecoverable():
    for e in generate_events(200, seed=8):
        assert observe(e, RecoveryAction.CHECKOUT_LINK, "ALREADY_PAID").incremental_minor == 0
