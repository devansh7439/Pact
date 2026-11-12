"""LLM boundaries: diagnosis validation, message conduct, provenance gate (I11)."""

import httpx
import pytest
import respx

from merchant.config import settings
from merchant.engine import diagnosis
from merchant.engine.diagnosis import PROPOSABLE, _parse, _validate, apply, diagnose
from merchant.engine.economics import RecoveryAction
from merchant.engine.provenance import is_simulated
from merchant.engine.taxonomy import FailureClass, classify
from merchant.integrations import llm
from merchant.simulator.generate import generate_events

LINK = "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"


@pytest.fixture
def live_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.test/v1")
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_model", "test-model")
    diagnosis.reset_breaker()
    yield
    diagnosis.reset_breaker()


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content},
                                                  "finish_reason": "stop"}]})


# -- Diagnosis ----------------------------------------------------------------

def test_model_cannot_propose_a_control_class():
    assert FailureClass.RISK_BLOCKED not in PROPOSABLE
    for cls in ("RISK_BLOCKED", "ALREADY_PAID", "MERCHANT_CONFIG"):
        v = _validate({"failure_class": cls, "confidence": 0.99})
        assert not v.accepted and "not proposable" in v.rejected_because


@pytest.mark.parametrize("raw", ["[]", "null", "not json", '{"confidence": 0.9}'])
def test_malformed_replies_are_rejected(raw):
    payload, _ = _parse(raw)
    assert payload is None or not _validate(payload).accepted


def test_low_confidence_is_rejected():
    assert not _validate({"failure_class": "INSUFFICIENT_FUNDS", "confidence": 0.5}).accepted


def test_no_llm_configured_means_no_diagnosis(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert not diagnose("9999", None, "insufficient balance").accepted


@respx.mock
def test_accepted_diagnosis_is_marked_llm_and_never_retries_same(live_llm):
    respx.post("https://llm.test/v1/chat/completions").mock(return_value=reply(
        '```json\n{"failure_class": "INSUFFICIENT_FUNDS", "confidence": 0.9, "reasoning": "balance"}\n```'))
    d = diagnose("9999", None, "Account balance too low")
    assert d.accepted and d.failure_class is FailureClass.INSUFFICIENT_FUNDS
    c = apply(classify("9999"), d)
    assert c.diagnosed_by == "llm" and c.confident and not c.retry_same_instrument


def test_simulated_events_never_call_the_model(live_llm):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://llm.test/v1/chat/completions")
        d = diagnose("9999", None, "x", allow_live=False)
        assert not d.accepted and route.call_count == 0


# -- Messages -----------------------------------------------------------------

def test_template_without_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    m = llm.generate_message("Arjun Lee", 4800, "ISSUER_DECLINED", RecoveryAction.CHECKOUT_LINK, LINK)
    assert m.provider == "template" and LINK in m.text and "$48.00" in m.text
    assert not llm.find_dark_patterns(m.text)


@pytest.mark.parametrize("bad", [
    "Hurry, your order expires today! Pay here: " + LINK,
    "Use code SAVE10 for a 10% discount: " + LINK,
    "Your payment successful, nothing to do. " + LINK,
    f"Verify your card at http://evil.example first, then {LINK}",
    "Please retry your payment soon.",  # omits the approved link
])
@respx.mock
def test_unsafe_generations_fall_back_to_template(live_llm, bad):
    respx.post("https://llm.test/v1/chat/completions").mock(return_value=reply(bad))
    m = llm.generate_message("Arjun", 4800, "ISSUER_DECLINED", RecoveryAction.CHECKOUT_LINK, LINK)
    assert m.provider == "template_fallback" and m.blocked_for


@respx.mock
def test_clean_generation_is_used(live_llm):
    good = f"Hi Arjun, your $48.00 payment didn't go through. You can finish it here: {LINK}"
    respx.post("https://llm.test/v1/chat/completions").mock(return_value=reply(good))
    m = llm.generate_message("Arjun", 4800, "ISSUER_DECLINED", RecoveryAction.CHECKOUT_LINK, LINK)
    assert m.provider == "llm:test-model" and m.text == good


def test_provenance_gate():
    """I11: simulated events are detectable from the data itself, not a flag."""
    e = generate_events(5, seed=9)[0]
    assert is_simulated(e)

    class Live:
        def __init__(self):
            self.id = "pi_live"
            self.amount = 3200
    assert not is_simulated(Live())
    assert not is_simulated(42)
