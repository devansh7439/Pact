import threading

import pytest

from merchant.engine.controls import AgentMode, ControlPlane
from merchant.engine.evaluate import evaluate_batch
from merchant.simulator.generate import generate_events


def test_first_boot_is_review_first():
    c = ControlPlane().get()
    assert c.mode is AgentMode.REVIEW_FIRST and not c.executes


def test_kill_switch_is_immediate_and_does_not_deadlock():
    plane = ControlPlane()
    plane.set(mode=AgentMode.AUTONOMOUS)
    assert plane.get().executes
    done = threading.Event()

    def kill():
        plane.kill("incident")
        done.set()
    threading.Thread(target=kill).start()
    assert done.wait(2), "kill switch deadlocked"
    c = plane.get()
    assert not c.executes and c.status == "disabled" and c.disabled_reason == "incident"


def test_policy_beats_blind_retry_with_perfect_propensities():
    """Strategy logic, isolated from model quality: feed the latent truth."""
    events = generate_events(1500, seed=77771111)
    rep = evaluate_batch(events, propensities=[e._true_base_propensity for e in events])
    s = rep["strategies"]
    assert rep["provenance"] == "simulated"
    assert s["pact"]["net_value_minor"] > s["blind_retry"]["net_value_minor"]
    assert s["pact"]["net_value_minor"] > 0
    assert s["pact"]["actions_on_unrecoverable"] == 0
    assert s["do_nothing"]["incremental_recovered_minor"] == 0
    assert s["pact"]["exceptions"] > 0  # unmapped declines reach the exception queue


@pytest.mark.slow
def test_trained_model_is_calibrated_and_below_the_ceiling(tmp_path):
    from merchant.ml.predict import load_model, predict_propensity_batch
    from merchant.ml.train import train

    _, report = train(n_events=4000, model_path=tmp_path / "m.joblib",
                      metrics_path=tmp_path / "m.json", n_estimators=80)
    assert report.brier < report.brier_baseline          # learned something
    assert report.roc_auc <= report.oracle_auc + 0.02    # no leak past the Bayes ceiling
    assert report.propensity_correlation > 0.3

    bundle = load_model(tmp_path / "m.joblib")
    events = generate_events(600, seed=77771111)
    p = predict_propensity_batch(events, bundle=bundle)
    assert all(0.0 <= x <= 1.0 for x in p)
    rep = evaluate_batch(events, propensities=p)
    assert rep["strategies"]["pact"]["net_value_minor"] > rep["strategies"]["blind_retry"]["net_value_minor"]
