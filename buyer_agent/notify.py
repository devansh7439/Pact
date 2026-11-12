"""Human inbox copy (doc 06 §5). Built from the guard's structured result.

Templates are the source of truth. The LLM is never given the merchant's
`display.text` here and has no tools, so the worst a bad generation can do is
read awkwardly. Without LLM credentials, templates are used as-is.
"""

from __future__ import annotations

from buyer_agent.guard import CLASS_LABELS, GuardResult
from shared.money import fmt

REASONS = {
    "bad_signature": "the offer wasn't properly signed by the merchant, so I ignored it",
    "agent_paused": "you've paused me",
    "unrecognised_offer": "the merchant sent an offer I don't recognise",
    "offer_for_other_intent": "the offer didn't match this order",
    "offer_from_other_merchant": "the offer came from a different merchant than the order",
    "offer_lifetime_invalid": "the offer broke the protocol's expiry rules",
    "failed_alias_offered": "the merchant offered to retry the payment method that just failed",
    "duplicate_option_ids": "the offer was malformed",
    "expired": "the offer had already expired",
    "merchant_out_of_scope": "this merchant isn't one you allowed",
    "amount_changed": "the merchant changed the amount",
    "mandate_expired": "your spending mandate has expired",
    "over_budget": "it would go over your budget or per-purchase cap",
    "class_requires_human": "this kind of decline needs your decision",
    "recovery_attempts_exhausted": "I've already used the automatic recoveries you allowed for this order",
    "needs_human_approval": "none of the automatic options are allowed by your mandate",
    "no_acceptable_option": "none of the merchant's options are acceptable",
}


def escalation_text(r: GuardResult, merchant_name: str, amount_minor: int, currency: str,
                    failure_class: str | None, has_link: bool) -> str:
    why = CLASS_LABELS.get(failure_class or "", "a decline")
    reason = REASONS.get(r.reason, r.reason.replace("_", " "))
    ask = " Tap to approve it on PayPal." if has_link else ""
    return (f"Your payment of {fmt(amount_minor, currency)} to {merchant_name} was declined ({why}). "
            f"I didn't retry it because {reason}.{ask}")


def rejection_text(r: GuardResult, merchant_name: str) -> str:
    reason = REASONS.get(r.reason, r.reason.replace("_", " "))
    return f"I rejected a recovery offer from {merchant_name}: {reason}. Nothing was charged."


def receipt_text(merchant_name: str, amount_minor: int, currency: str, *, alias: str | None,
                 failure_class: str | None, recovered: bool, alias_kind: str | None = None) -> str:
    amount = fmt(amount_minor, currency)
    if not recovered:
        return f"Paid {amount} to {merchant_name}."
    pretty = "your PayPal balance" if alias_kind == "PAYPAL_WALLET" else (alias or "another saved method")
    why = CLASS_LABELS.get(failure_class or "", "a decline")
    return (f"Your card was declined ({why}), so I used {pretty} as you allowed. "
            f"{amount}, {merchant_name}.")


def security_text(merchant_name: str, flags: list[str]) -> str:
    return (f"Heads up: an offer from {merchant_name} contained text that looked like instructions "
            f"to me ({', '.join(flags)}). I ignored it; it didn't affect any decision.")
