"""Demo builders: Maya's mandate, a $32 purchase at Kettle & Crumb, the S1 offer.

Used by tests, property tests and the judge-mode seed. Values follow doc 06 §1
and the doc 03 §4 example offer.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from buyer_agent.guard import PurchaseRecord
from shared.prp.models import Mandate

T0 = datetime(2026, 11, 20, 10, 15, 2, tzinfo=timezone.utc)
MERCHANT_ID = "mer_kettle_crumb"
MERCHANT_NAME = "Kettle & Crumb"
INTENT_ID = "pi_01JD4JABCDEFGH"
OFFER_ID = "off_01JD4KABCDEFGH"
MANDATE_ID = "mdt_01JD3ABCDEFGH"


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def mandate_dict(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "mandate_id": MANDATE_ID,
        "principal": {"display_name": "Maya", "paypal_payer_id": "SANDBOXPAYER123"},
        "merchant_scope": [MERCHANT_ID],
        "currency_code": "USD",
        "budget": {"period": "WEEK", "limit_minor": 6000},
        "per_purchase_cap_minor": 5000,
        "allowed_categories": ["coffee", "tea", "brewing-supplies"],
        "funding": [
            {"alias": "primary-card", "kind": "CARD", "priority": 1},
            {"alias": "paypal-wallet", "kind": "PAYPAL_WALLET", "priority": 2},
        ],
        "recovery": {
            "allow_alternate_funding": True,
            "allow_retry_after": False,
            "max_autonomous_recoveries_per_purchase": 1,
            "always_escalate_classes": ["RISK_BLOCKED", "AUTH_FAILURE", "UNKNOWN"],
        },
        "approved_at": "2026-11-20T09:58:11Z",
        "approval_ref": "onb_01JD3ABCDEFGH",
        "expires_at": "2027-02-20T00:00:00Z",
    }
    _deep_update(d, overrides)
    return d


def maya_mandate(**overrides: Any) -> Mandate:
    return Mandate.model_validate(mandate_dict(**overrides))


def purchase(**overrides: Any) -> PurchaseRecord:
    base = dict(
        purchase_id="pur_01JD4JABCDEFGH",
        merchant_id=MERCHANT_ID,
        intent_id=INTENT_ID,
        amount_minor=3200,
        currency_code="USD",
        funding_alias="primary-card",
        autonomous_recoveries=0,
    )
    base.update(overrides)
    return PurchaseRecord(**base)


def s1_offer(**overrides: Any) -> dict[str, Any]:
    """S1: card declined 5120 INSUFFICIENT_FUNDS, PayPal wallet offered."""
    d: dict[str, Any] = {
        "prp_version": "0.1",
        "offer_id": OFFER_ID,
        "intent_id": INTENT_ID,
        "merchant": {"id": MERCHANT_ID, "name": MERCHANT_NAME},
        "created_at": _iso(T0),
        "expires_at": _iso(T0 + timedelta(minutes=15)),
        "amount": {"currency_code": "USD", "value_minor": 3200},
        "failure": {
            "class": "INSUFFICIENT_FUNDS",
            "retry_same_instrument": False,
            "failed_funding_alias": "primary-card",
            "paypal": {"processor_response_code": "5120", "processor_response_name": "INSUFFICIENT_FUNDS"},
        },
        "options": [
            {"option_id": "opt_alt", "kind": "ALTERNATE_FUNDING", "eligible_funding_aliases": ["paypal-wallet"]},
            {"option_id": "opt_payer", "kind": "PAYER_ACTION"},
            {"option_id": "opt_cancel", "kind": "CANCEL"},
        ],
        "decision_ref": "dec_01JD4KABCDEFGH",
        "display": {
            "untrusted": True,
            "locale": "en-US",
            "text": "Your card was declined for insufficient funds. You can pay with your saved PayPal balance instead.",
        },
    }
    _deep_update(d, overrides)
    return d


def _deep_update(base: dict[str, Any], over: dict[str, Any]) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
