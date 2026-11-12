import pytest

from merchant.engine.taxonomy import (
    ALL_ENTRIES,
    ISSUES,
    PROCESSOR_CODES,
    SANDBOX_TRIGGERS,
    FailureClass,
    classify,
)

# Doc 04 §4 sandbox trigger table: processor code -> our class.
DOC_TABLE = {
    "0500": FailureClass.ISSUER_DECLINED,
    "9500": FailureClass.RISK_BLOCKED,
    "5400": FailureClass.INSTRUMENT_INVALID,
    "5180": FailureClass.INSTRUMENT_INVALID,
    "5120": FailureClass.INSUFFICIENT_FUNDS,
    "9520": FailureClass.RISK_BLOCKED,
    "1330": FailureClass.INSTRUMENT_INVALID,
    "5100": FailureClass.ISSUER_DECLINED,
    "00N7": FailureClass.AUTH_FAILURE,
}


def test_every_code_has_one_class():
    codes = [e.code for e in ALL_ENTRIES]
    assert len(codes) == len(set(codes)), "a code is mapped twice"
    for e in ALL_ENTRIES:
        assert isinstance(e.failure_class, FailureClass)


@pytest.mark.parametrize("code,expected", DOC_TABLE.items())
def test_doc_trigger_table(code, expected):
    c = classify(code)
    assert c.failure_class is expected and c.confident


def test_every_sandbox_trigger_maps():
    for trigger, code in SANDBOX_TRIGGERS.items():
        assert code in PROCESSOR_CODES, trigger


def test_paypal_says_do_not_retry_these():
    # PayPal's card-testing page: use another card for fraud, restricted, lost/stolen.
    for code in ("9500", "5180", "9520"):
        assert classify(code).retry_same_instrument is False


def test_no_mapped_code_permits_same_instrument_retry():
    assert not any(e.retry_same_instrument for e in ALL_ENTRIES)


def test_processor_code_wins_over_issue():
    assert classify("5120", "INSTRUMENT_DECLINED").failure_class is FailureClass.INSUFFICIENT_FUNDS


def test_issue_used_when_no_processor_code():
    assert classify(None, "PAYER_ACTION_REQUIRED").failure_class is FailureClass.AUTH_FAILURE
    assert classify(None, " instrument_declined ").failure_class is FailureClass.ISSUER_DECLINED


@pytest.mark.parametrize("code,issue", [(None, None), ("9999", None), (None, "SOMETHING_NEW"), ("", "")])
def test_unmapped_is_unknown_and_unconfident(code, issue):
    c = classify(code, issue)
    assert c.failure_class is FailureClass.UNKNOWN and not c.confident


def test_doc_issue_mappings():
    assert ISSUES["INSTRUMENT_DECLINED"].failure_class is FailureClass.ISSUER_DECLINED
    assert ISSUES["TRANSACTION_REFUSED"].failure_class is FailureClass.ISSUER_DECLINED
    assert ISSUES["PAYER_ACTION_REQUIRED"].failure_class is FailureClass.AUTH_FAILURE
