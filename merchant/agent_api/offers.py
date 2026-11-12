"""Build a PRP v0.1 recovery offer from an engine decision (doc 03 §4).

Rules enforced here, at build time — a violation raises rather than shipping:

  R1  amount and currency equal the original intent
  R2  if retry_same_instrument is false, no failed alias appears in any option
  R3  RISK_BLOCKED offers only PAYER_ACTION and CANCEL
  R4  expires_at − created_at ≤ 30 minutes
  G2  intent_id and merchant.id match the purchase; option_ids are unique

`display.text` is template copy (never LLM output) and is still scanned, so a
compromised template can't ship pressure, offers or links (doc 06 §4 item 5).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from merchant.engine.economics import RecoveryAction
from merchant.engine.policy import PolicyDecision
from merchant.engine.taxonomy import Classification, FailureClass
from merchant.integrations.llm import URL_PATTERN, find_dark_patterns
from shared.money import fmt
from shared.prp.ids import new_id
from shared.prp.models import RecoveryOffer

MAX_TTL = timedelta(minutes=30)

OPTION_IDS = {
    RecoveryAction.ALTERNATE_FUNDING_OFFER: "opt_alt",
    RecoveryAction.RETRY_AFTER_OFFER: "opt_retry",
    RecoveryAction.PAYER_ACTION_OFFER: "opt_payer",
}

_TEXT = {
    "INSUFFICIENT_FUNDS": "Your card was declined for insufficient funds.",
    "INSTRUMENT_INVALID": "Your saved card can't be used for this payment.",
    "ISSUER_DECLINED": "Your card issuer declined this payment.",
    "AUTH_FAILURE": "This payment needs you to confirm it on PayPal.",
    "RISK_BLOCKED": "This payment needs you to confirm it on PayPal.",
}

#: Imperatives aimed at agents. Never present in our own copy (doc 06 §4).
AGENT_IMPERATIVES = ("ignore", "system:", "you must", "mandate updated", "pay with any")


class OfferRuleViolation(AssertionError):
    pass


def _display_text(fc: str, amount_minor: int, currency: str, has_alt: bool) -> str:
    lead = _TEXT.get(fc, "Your payment didn't go through.")
    tail = (" You can pay with another saved method instead." if has_alt
            else " You can approve the payment on PayPal.")
    text = f"{lead} {fmt(amount_minor, currency)} is still due.{tail}"
    lowered = text.lower()
    if find_dark_patterns(text) or URL_PATTERN.search(text) or any(i in lowered for i in AGENT_IMPERATIVES):
        raise OfferRuleViolation("display text failed the scanner")
    return text


def build_offer(*, intent: dict, decision: PolicyDecision, decision_id: str,
                classification: Classification, failed_alias: str, merchant_id: str,
                merchant_name: str, now: datetime, ttl_seconds: int,
                retry_after_hours: float | None) -> RecoveryOffer:
    fc = classification.failure_class
    ttl = timedelta(seconds=ttl_seconds)
    if ttl > MAX_TTL or ttl.total_seconds() <= 0:
        raise OfferRuleViolation(f"R4: offer TTL {ttl} outside (0, 30 min]")

    aliases = list(decision.eligible_funding_aliases)
    if not classification.retry_same_instrument and failed_alias in aliases:
        raise OfferRuleViolation("R2: failed alias in eligible aliases")

    options: list[dict] = []
    for action in decision.offer_actions:
        opt = {"option_id": OPTION_IDS[action],
               "kind": {RecoveryAction.ALTERNATE_FUNDING_OFFER: "ALTERNATE_FUNDING",
                        RecoveryAction.RETRY_AFTER_OFFER: "RETRY_AFTER",
                        RecoveryAction.PAYER_ACTION_OFFER: "PAYER_ACTION"}[action]}
        if action in (RecoveryAction.ALTERNATE_FUNDING_OFFER, RecoveryAction.RETRY_AFTER_OFFER):
            if not aliases:
                continue
            opt["eligible_funding_aliases"] = aliases
        if action is RecoveryAction.RETRY_AFTER_OFFER:
            opt["not_before"] = (now + timedelta(hours=retry_after_hours or 24)).isoformat()
        options.append(opt)
    options.append({"option_id": "opt_cancel", "kind": "CANCEL"})

    if fc is FailureClass.RISK_BLOCKED and {o["kind"] for o in options} - {"PAYER_ACTION", "CANCEL"}:
        raise OfferRuleViolation("R3: RISK_BLOCKED offer with an autonomous option")
    ids = [o["option_id"] for o in options]
    if len(ids) != len(set(ids)):
        raise OfferRuleViolation("G2: duplicate option_id")

    paypal = {k: v for k, v in {
        "processor_response_code": classification.entry.code
        if classification.entry and classification.entry.kind.name == "PROCESSOR" else None,
        "processor_response_name": classification.entry.name
        if classification.entry and classification.entry.kind.name == "PROCESSOR" else None,
        "issue": classification.entry.code
        if classification.entry and classification.entry.kind.name == "ISSUE" else None,
    }.items() if v}

    body = {
        "prp_version": "0.1",
        "offer_id": new_id("off"),
        "intent_id": intent["intent_id"],
        "merchant": {"id": merchant_id, "name": merchant_name},
        "created_at": now.isoformat(),
        "expires_at": (now + ttl).isoformat(),
        # R1: straight from the intent row, never from the decision or the request.
        "amount": {"currency_code": intent["currency_code"], "value_minor": intent["amount_minor"]},
        "failure": {"class": fc.value,
                    "retry_same_instrument": classification.retry_same_instrument,
                    "failed_funding_alias": failed_alias,
                    **({"paypal": paypal} if paypal else {})},
        "options": options,
        "decision_ref": decision_id,
        "display": {"untrusted": True, "locale": "en-US",
                    "text": _display_text(fc.value, intent["amount_minor"], intent["currency_code"],
                                          any(o["kind"] == "ALTERNATE_FUNDING" for o in options))},
    }
    offer = RecoveryOffer.model_validate(body)
    if offer.intent_id != intent["intent_id"] or offer.merchant.id != merchant_id:
        raise OfferRuleViolation("G2: intent or merchant mismatch")
    return offer


def offer_json(offer: RecoveryOffer) -> dict:
    return offer.model_dump(mode="json", by_alias=True, exclude_none=True)
