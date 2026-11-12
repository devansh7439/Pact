"""The mandate guard: THE decision function for recovery offers (doc 06 §2).

    guard(GuardInput) -> GuardResult  ACCEPT(option_id, alias) | ESCALATE(reason) | REJECT(reason)

Pure: no I/O, no clock, no LLM. Rules run in order and the first one that
fires decides. The guard never reads `display.text` (offer rule R6, invariant I6).

Every evaluated rule is recorded as a `Check`, so the buyer pane can render the
checklist straight from the structured result, including when the answer is ACCEPT.

Choices this module makes where doc 06 is silent:
- Buyer-side pause ("pause my agent") is checked right after G1: forged offers
  are still REJECTed, everything else is ESCALATEd.
- Offer-rule violations the buyer can detect (R2: failed alias offered again;
  R4: lifetime > 30 min; offer is for a different intent/merchant than our
  purchase) are REJECTed under G2.
- An expired mandate ESCALATEs under G6 (`mandate_expired`).
- Funding priority: lower `priority` number wins (1 = first choice).
- G9 excludes every alias that already failed on this purchase (the buyer's own
  record), not only the offer's `failed_funding_alias`. G10 may reuse the
  offer's failed alias only when `retry_same_instrument` is true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import ValidationError

from shared.money import fmt
from shared.prp.models import (
    AlternateFundingOption,
    Mandate,
    PayerActionOption,
    RecoveryOffer,
    RetryAfterOption,
)

Decision = Literal["ACCEPT", "ESCALATE", "REJECT"]
CheckStatus = Literal["pass", "fail", "skip"]

MAX_OFFER_LIFETIME = timedelta(minutes=30)

CLASS_LABELS = {
    "INSUFFICIENT_FUNDS": "insufficient funds",
    "INSTRUMENT_INVALID": "card no longer valid",
    "ISSUER_DECLINED": "declined by the bank",
    "AUTH_FAILURE": "authentication failed",
    "RISK_BLOCKED": "blocked by risk checks",
    "UNKNOWN": "unknown reason",
}


@dataclass(frozen=True)
class PurchaseRecord:
    """The buyer's own record of what it tried to buy. The offer is checked against this."""

    purchase_id: str
    merchant_id: str
    intent_id: str
    amount_minor: int
    currency_code: str
    funding_alias: str
    autonomous_recoveries: int = 0
    #: Every alias that has already declined on this purchase (the buyer's own
    #: record; the offer's failed_funding_alias only names the latest one).
    failed_aliases: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GuardInput:
    offer: dict[str, Any] | None  # parsed body from prp_client; None if unparseable
    signature_ok: bool  # G1 is decided by prp_client before the guard runs
    mandate: Mandate
    purchase: PurchaseRecord
    spent_this_period_minor: int  # from the budget ledger (captures only)
    now: datetime  # timezone-aware
    paused: bool = False
    merchant_name: str | None = None  # registered name, for checklist labels only


@dataclass(frozen=True)
class Check:
    rule: str  # "G1".."G12", "PAUSE"
    status: CheckStatus
    label: str


@dataclass(frozen=True)
class GuardResult:
    decision: Decision
    rule_fired: str
    reason: str  # machine code, e.g. "over_budget"; "accepted" on ACCEPT
    option_id: str | None = None
    alias: str | None = None
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def first_failure(self) -> Check | None:
        return next((c for c in self.checks if c.status == "fail"), None)


class _Builder:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def ok(self, rule: str, label: str) -> None:
        self.checks.append(Check(rule, "pass", label))

    def stop(
        self,
        decision: Decision,
        rule: str,
        reason: str,
        label: str,
        *,
        status: CheckStatus = "fail",
        option_id: str | None = None,
        alias: str | None = None,
    ) -> GuardResult:
        self.checks.append(Check(rule, status, label))
        return GuardResult(decision, rule, reason, option_id, alias, tuple(self.checks))


def _mmss(delta: timedelta) -> str:
    secs = max(0, int(delta.total_seconds()))
    return f"{secs // 60}:{secs % 60:02d}"


def _offer_rule_violation(offer: RecoveryOffer, purchase: PurchaseRecord) -> str | None:
    if offer.intent_id != purchase.intent_id:
        return "offer_for_other_intent"
    if offer.merchant.id != purchase.merchant_id:
        return "offer_from_other_merchant"
    if offer.expires_at - offer.created_at > MAX_OFFER_LIFETIME or offer.expires_at <= offer.created_at:
        return "offer_lifetime_invalid"  # R4
    if not offer.failure.retry_same_instrument:
        failed = offer.failure.failed_funding_alias
        for opt in offer.options:
            if isinstance(opt, (AlternateFundingOption, RetryAfterOption)) and failed in opt.eligible_funding_aliases:
                return "failed_alias_offered"  # R2
    if len({o.option_id for o in offer.options}) != len(offer.options):
        return "duplicate_option_ids"
    return None


def _best_alias(
    candidates: list[str], mandate: Mandate, exclude: frozenset[str]
) -> tuple[int, str] | None:
    """Highest-priority mandate funding source among `candidates`, minus `exclude`."""
    best: tuple[int, str] | None = None
    for alias in candidates:
        if alias in exclude:
            continue
        src = mandate.funding_by_alias(alias)
        if src is None:
            continue
        if best is None or src.priority < best[0]:
            best = (src.priority, alias)
    return best


def guard(inp: GuardInput) -> GuardResult:
    b = _Builder()
    m, p = inp.mandate, inp.purchase

    # G1 — signature (verified by prp_client before we get here)
    if not inp.signature_ok:
        return b.stop("REJECT", "G1", "bad_signature", "Signature check failed — offer ignored")
    b.ok("G1", f"Signed by {inp.merchant_name or p.merchant_id}")

    if inp.paused:
        return b.stop("ESCALATE", "PAUSE", "agent_paused", "Agent is paused — asking you instead")

    # G2 — schema valid, no unknown fields/kinds (R7), plus buyer-detectable offer rules
    try:
        if inp.offer is None:
            raise ValueError("no offer body")
        offer = RecoveryOffer.model_validate(inp.offer)
    except (ValidationError, ValueError):
        return b.stop("ESCALATE", "G2", "unrecognised_offer", "Offer format not recognised")
    violation = _offer_rule_violation(offer, p)
    if violation:
        return b.stop("REJECT", "G2", violation, "Offer breaks the recovery protocol rules")
    b.ok("G2", "Offer format valid")

    # G3 — not expired
    if not inp.now < offer.expires_at:
        return b.stop("REJECT", "G3", "expired", "Offer has expired")
    b.ok("G3", f"Offer still valid (expires in {_mmss(offer.expires_at - inp.now)})")

    # G4 — merchant in scope
    if offer.merchant.id not in m.merchant_scope:
        return b.stop("REJECT", "G4", "merchant_out_of_scope", f"{offer.merchant.id} is not a merchant you allowed")
    b.ok("G4", "Merchant is in your allowed list")

    # G5 — amount and currency unchanged vs our own purchase record (R1)
    amt = offer.amount
    if amt.value_minor != p.amount_minor or amt.currency_code != p.currency_code:
        return b.stop(
            "REJECT", "G5", "amount_changed",
            f"Amount changed: offer says {fmt(amt.value_minor, amt.currency_code)}, "
            f"order was {fmt(p.amount_minor, p.currency_code)}",
        )
    b.ok("G5", "Same amount as the original order")

    # G6 — mandate active, per-purchase cap and remaining period budget
    cur = m.currency_code
    if not inp.now < m.expires_at:
        return b.stop("ESCALATE", "G6", "mandate_expired", "Your spending mandate has expired")
    if amt.currency_code != cur:
        return b.stop("ESCALATE", "G6", "over_budget", f"Offer currency {amt.currency_code} is not your budget currency {cur}")
    remaining = m.budget.limit_minor - inp.spent_this_period_minor
    period = {"DAY": "today's", "WEEK": "this week's", "MONTH": "this month's"}[m.budget.period]
    if amt.value_minor > remaining:
        return b.stop(
            "ESCALATE", "G6", "over_budget",
            f"Over {period} budget ({fmt(amt.value_minor, cur)} needed, {fmt(max(remaining, 0), cur)} left)",
        )
    b.ok("G6", f"Within {period} budget ({fmt(amt.value_minor, cur)} needed, {fmt(remaining, cur)} left)")
    if amt.value_minor > m.per_purchase_cap_minor:
        return b.stop(
            "ESCALATE", "G6", "over_budget",
            f"Over the per-purchase cap ({fmt(m.per_purchase_cap_minor, cur)})",
        )
    b.ok("G6", f"Within the per-purchase cap ({fmt(m.per_purchase_cap_minor, cur)})")

    # G7 — failure class allowed for autonomous recovery (R3: RISK_BLOCKED always escalates)
    cls = offer.failure.class_
    cls_label = CLASS_LABELS.get(cls, cls.lower())
    if cls in m.recovery.always_escalate_classes:
        return _human_or_stop(b, offer, "G7", "class_requires_human", f"Failure type needs you to decide ({cls_label})")
    b.ok("G7", f"Failure type allowed for automatic recovery ({cls_label})")

    # G8 — autonomous recovery attempts left for this purchase
    used, cap = p.autonomous_recoveries, m.recovery.max_autonomous_recoveries_per_purchase
    if used >= cap:
        return _human_or_stop(
            b, offer, "G8", "recovery_attempts_exhausted",
            f"Automatic recoveries used for this order: {used} of {cap}",
        )
    b.ok("G8", f"Automatic recoveries used for this order: {used} of {cap}")

    failed = offer.failure.failed_funding_alias
    all_failed = p.failed_aliases | {failed}

    # G9 — ALTERNATE_FUNDING with the best mandate alias that isn't the failed one
    if m.recovery.allow_alternate_funding:
        best: tuple[int, str, str] | None = None
        for opt in offer.options:
            if isinstance(opt, AlternateFundingOption):
                pick = _best_alias(opt.eligible_funding_aliases, m, exclude=all_failed)
                if pick and (best is None or pick[0] < best[0]):
                    best = (pick[0], pick[1], opt.option_id)
        if best:
            _, alias, option_id = best
            kind = m.funding_by_alias(alias).kind  # type: ignore[union-attr]
            pretty = "PayPal wallet" if kind == "PAYPAL_WALLET" else alias
            return b.stop(
                "ACCEPT", "G9", "accepted",
                f"Paying with: {pretty} — allowed, not a source that failed",
                status="pass", option_id=option_id, alias=alias,
            )

    # G10 — RETRY_AFTER if the mandate allows it
    if m.recovery.allow_retry_after:
        for opt in offer.options:
            if isinstance(opt, RetryAfterOption):
                exclude = all_failed - {failed} if offer.failure.retry_same_instrument else all_failed
                pick = _best_alias(opt.eligible_funding_aliases, m, exclude=exclude)
                if pick:
                    return b.stop(
                        "ACCEPT", "G10", "accepted",
                        f"Retrying with {pick[1]} after {opt.not_before.isoformat()}",
                        status="pass", option_id=opt.option_id, alias=pick[1],
                    )

    # G11 / G12
    return _human_or_stop(b, offer, "G11", "needs_human_approval", "No automatic option your mandate allows")


def _human_or_stop(b: _Builder, offer: RecoveryOffer, rule: str, reason: str, label: str) -> GuardResult:
    """Escalate. Attach the PAYER_ACTION option (if any) so the inbox can offer an approve link."""
    payer = next((o for o in offer.options if isinstance(o, PayerActionOption)), None)
    if rule == "G11" and payer is None:
        return b.stop("ESCALATE", "G12", "no_acceptable_option", "No acceptable option — asking you")
    return b.stop("ESCALATE", rule, reason, label, option_id=payer.option_id if payer else None)


def render_checklist(result: GuardResult, merchant_name: str, amount_minor: int, currency_code: str) -> str:
    """Plain-text checklist (doc 06 §2). Built only from the structured result."""
    lines = [f"Recovery offer from {merchant_name} · {fmt(amount_minor, currency_code)}"]
    marks = {"pass": "✓", "fail": "✗", "skip": "–"}
    for c in result.checks:
        lines.append(f"  {marks[c.status]} {c.label}")
    tail = {
        "ACCEPT": "Accepted automatically",
        "ESCALATE": "Asked you to decide",
        "REJECT": "Rejected",
    }[result.decision]
    lines.append(f"  → {tail}")
    return "\n".join(lines)
