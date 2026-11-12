"""Mandate helpers: budget periods, remaining budget, purchase-time checks.

Spend is counted on capture only (doc 07 `budget_ledger`), so a declined
attempt never eats budget. Periods are UTC: DAY from midnight, WEEK from
Monday 00:00, MONTH from the 1st.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from shared.money import fmt
from shared.prp.models import Mandate


def period_start(period: str, now: datetime) -> datetime:
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "DAY":
        return day
    if period == "WEEK":
        return day - timedelta(days=day.weekday())
    if period == "MONTH":
        return day.replace(day=1)
    raise ValueError(f"unknown budget period {period!r}")


def remaining_budget(mandate: Mandate, spent_this_period_minor: int) -> int:
    return mandate.budget.limit_minor - spent_this_period_minor


@dataclass(frozen=True)
class PurchaseCheck:
    ok: bool
    reason: str  # "ok" or a machine code
    detail: str


def check_purchase(
    mandate: Mandate,
    *,
    merchant_id: str,
    category: str,
    amount_minor: int,
    currency_code: str,
    spent_this_period_minor: int,
    now: datetime,
    paused: bool = False,
) -> PurchaseCheck:
    """Purchase-time rules (doc 06 §3): run on the shopper's structured intent
    before any checkout call. The LLM's output only gets here after validation."""
    cur = mandate.currency_code
    if paused:
        return PurchaseCheck(False, "agent_paused", "Agent is paused")
    if not now < mandate.expires_at:
        return PurchaseCheck(False, "mandate_expired", "Mandate has expired")
    if merchant_id not in mandate.merchant_scope:
        return PurchaseCheck(False, "merchant_out_of_scope", f"{merchant_id} is not an allowed merchant")
    if mandate.allowed_categories and category not in mandate.allowed_categories:
        return PurchaseCheck(False, "category_not_allowed", f"'{category}' is not an allowed category")
    if currency_code != cur:
        return PurchaseCheck(False, "currency_mismatch", f"{currency_code} is not {cur}")
    if amount_minor > mandate.per_purchase_cap_minor:
        return PurchaseCheck(False, "over_cap", f"{fmt(amount_minor, cur)} is over the {fmt(mandate.per_purchase_cap_minor, cur)} cap")
    left = remaining_budget(mandate, spent_this_period_minor)
    if amount_minor > left:
        return PurchaseCheck(False, "over_budget", f"{fmt(amount_minor, cur)} needed, {fmt(max(left, 0), cur)} left")
    return PurchaseCheck(True, "ok", "Within mandate")


def preferred_funding(mandate: Mandate) -> str:
    """The alias to use for a first attempt: lowest priority number."""
    return min(mandate.funding, key=lambda f: f.priority).alias
