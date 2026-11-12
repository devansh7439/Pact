"""Recovery economics: what each intervention costs and what it is worth.

A recovery decision is an *investment* decision. Every intervention costs
money, so the question is never "can we do something?" but "is doing something
worth more than doing nothing?". DROP is not a special case: it is what happens
when no action clears the merchant's floor (doc 05 §3, stage 3).

    p(a)   = base_propensity x effectiveness[class][a]
    p0     = base_propensity x organic_baseline[class]
    lift   = max(0, p(a) - p0)
    V      = amount x contribution_margin
    fee    = lift x PayPal fee on the amount      (only the incremental capture is ours to pay for)
    NEV(a) = lift x V - fee - C(a)

All money is integer minor units (cents for USD); see `shared/money.py`.
Intervention costs use PayPal's fee schedule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from shared.money import fmt


class RecoveryAction(str, Enum):
    """Every intervention the merchant engine can choose (doc 05 stage 2)."""

    ALTERNATE_FUNDING_OFFER = "ALTERNATE_FUNDING_OFFER"
    """Agent channel: offer to charge a different saved, consented funding source."""

    RETRY_AFTER_OFFER = "RETRY_AFTER_OFFER"
    """Agent channel: offer a retry no earlier than a backoff sized to the failure."""

    PAYER_ACTION_OFFER = "PAYER_ACTION_OFFER"
    """Agent channel: the human approves a fresh order on PayPal (agent escalates)."""

    CHECKOUT_LINK = "CHECKOUT_LINK"
    """Human channel: a PayPal order needing payer approval, sent with a message."""

    ESCALATE = "ESCALATE"
    """Merchant review queue. For config faults, risk on the human channel, high value."""

    RETRY_SAME_INSTRUMENT = "RETRY_SAME_INSTRUMENT"
    """Re-present the failed source unchanged. Never eligible for any PayPal class
    we map (PayPal's guidance and doc 05 forbid it); kept so the per-option table
    can show it being refused, and as the blind-retry baseline in evaluation."""

    DROP = "DROP"
    """Do nothing. The baseline every other action has to beat."""


#: Actions that become options inside a signed PRP offer (agent channel).
OFFER_ACTIONS: frozenset[RecoveryAction] = frozenset({
    RecoveryAction.ALTERNATE_FUNDING_OFFER,
    RecoveryAction.RETRY_AFTER_OFFER,
    RecoveryAction.PAYER_ACTION_OFFER,
})

#: Offer action -> PRP option kind (doc 03 §4).
OPTION_KIND: dict[RecoveryAction, str] = {
    RecoveryAction.ALTERNATE_FUNDING_OFFER: "ALTERNATE_FUNDING",
    RecoveryAction.RETRY_AFTER_OFFER: "RETRY_AFTER",
    RecoveryAction.PAYER_ACTION_OFFER: "PAYER_ACTION",
}


@dataclass(frozen=True, slots=True)
class ActionCost:
    """Fully loaded cost of one attempt, in minor units.

    direct_minor covers delivery, order creation and ops minutes; goodwill_minor
    is modelled customer irritation — not an invoice, but pricing it keeps the
    optimiser quiet when the upside is thin.
    """

    direct_minor: int
    goodwill_minor: int

    @property
    def total_minor(self) -> int:
        return self.direct_minor + self.goodwill_minor


#: Order-of-magnitude US costs. The ratios drive behaviour more than the values:
#: ESCALATE (five minutes of ops time) costs ~12x an offer, so human attention
#: is only spent where the ticket justifies it.
ACTION_COSTS: dict[RecoveryAction, ActionCost] = {
    RecoveryAction.ALTERNATE_FUNDING_OFFER: ActionCost(direct_minor=20, goodwill_minor=0),
    RecoveryAction.RETRY_AFTER_OFFER: ActionCost(direct_minor=10, goodwill_minor=0),
    # Interrupts the human principal, so it carries goodwill cost.
    RecoveryAction.PAYER_ACTION_OFFER: ActionCost(direct_minor=15, goodwill_minor=30),
    # An unsolicited "your payment failed" email has a real churn cost. At $1.50
    # goodwill, links on instrument-invalid orders break even around $5, so the
    # S4 $4 add-on is dropped while the S6 $48 reorder is chased.
    RecoveryAction.CHECKOUT_LINK: ActionCost(direct_minor=5, goodwill_minor=150),
    RecoveryAction.ESCALATE: ActionCost(direct_minor=250, goodwill_minor=0),
    # Repeated declines on one card attract issuer scrutiny.
    RecoveryAction.RETRY_SAME_INSTRUMENT: ActionCost(direct_minor=10, goodwill_minor=0),
    RecoveryAction.DROP: ActionCost(direct_minor=0, goodwill_minor=0),
}


@dataclass(frozen=True, slots=True)
class MerchantPolicy:
    """Merchant guardrails — the outer bound on autonomy (doc 05 §7).

    Checked before expected value is computed, so no score can argue past them.
    """

    max_attempts_per_payment: int = 2
    max_contacts_per_customer_per_day: int = 2
    cooldown_hours: float = 12.0
    contribution_margin: float = 1.0
    #: PayPal standard US checkout pricing (3.49% + $0.49). Merchant-editable.
    processor_fee_rate: float = 0.0349
    processor_fee_fixed_minor: int = 49
    min_net_ev_minor: int = 50
    max_autonomous_amount_minor: int = 25_000
    require_human_above_threshold: bool = True
    # Learning: bounded exploration, off by default (see bandit, once ported).
    explore_fraction: float = 0.0
    max_explore_amount_minor: int = 2_000

    def __post_init__(self) -> None:
        if not 0.0 <= self.explore_fraction <= 0.5:
            raise ValueError(f"explore_fraction must be in [0, 0.5]: {self.explore_fraction}")
        if not 0.0 <= self.processor_fee_rate < 1.0:
            raise ValueError(f"processor_fee_rate must be in [0, 1): {self.processor_fee_rate}")
        if not 0.0 < self.contribution_margin <= 1.0:
            raise ValueError(f"contribution_margin must be in (0, 1]: {self.contribution_margin}")
        if self.max_attempts_per_payment < 1:
            raise ValueError("max_attempts_per_payment must be at least 1")


DEFAULT_POLICY = MerchantPolicy()

A = RecoveryAction

#: Structural fit between a failure mode and a remedy, in [0, 1]:
#:     P(recovery | action) = base_propensity x effectiveness[class][action]
#: Modelling assumptions, written down so a reviewer can dispute a number rather
#: than an opaque score. Claims they encode:
#:  - Another saved source is the strongest remedy whenever the instrument, not
#:    the customer, is the problem — and the agent can use it with no human.
#:  - Payer action and a checkout link work about equally (a human must act).
#:  - Retrying the same instrument is weak at best and zero for dead or risky ones.
ACTION_EFFECTIVENESS: dict[str, dict[RecoveryAction, float]] = {
    "INSUFFICIENT_FUNDS": {
        A.ALTERNATE_FUNDING_OFFER: 0.80, A.RETRY_AFTER_OFFER: 0.45,
        A.PAYER_ACTION_OFFER: 0.62, A.CHECKOUT_LINK: 0.60,
        A.ESCALATE: 0.30, A.RETRY_SAME_INSTRUMENT: 0.15,
    },
    "INSTRUMENT_INVALID": {
        A.ALTERNATE_FUNDING_OFFER: 0.82, A.RETRY_AFTER_OFFER: 0.0,
        A.PAYER_ACTION_OFFER: 0.64, A.CHECKOUT_LINK: 0.70,
        A.ESCALATE: 0.25, A.RETRY_SAME_INSTRUMENT: 0.0,
    },
    "ISSUER_DECLINED": {
        A.ALTERNATE_FUNDING_OFFER: 0.75, A.RETRY_AFTER_OFFER: 0.20,
        A.PAYER_ACTION_OFFER: 0.58, A.CHECKOUT_LINK: 0.60,
        A.ESCALATE: 0.30, A.RETRY_SAME_INSTRUMENT: 0.12,
    },
    "AUTH_FAILURE": {
        A.ALTERNATE_FUNDING_OFFER: 0.40, A.RETRY_AFTER_OFFER: 0.0,
        A.PAYER_ACTION_OFFER: 0.66, A.CHECKOUT_LINK: 0.66,
        A.ESCALATE: 0.30, A.RETRY_SAME_INSTRUMENT: 0.05,
    },
    # Only the payer re-authenticating can recover these; nothing autonomous works.
    "RISK_BLOCKED": {
        A.ALTERNATE_FUNDING_OFFER: 0.0, A.RETRY_AFTER_OFFER: 0.0,
        A.PAYER_ACTION_OFFER: 0.35, A.CHECKOUT_LINK: 0.0,
        A.ESCALATE: 0.30, A.RETRY_SAME_INSTRUMENT: 0.0,
    },
    # Ops fixes our configuration and the payment becomes collectable again.
    "MERCHANT_CONFIG": {
        A.ALTERNATE_FUNDING_OFFER: 0.0, A.RETRY_AFTER_OFFER: 0.0,
        A.PAYER_ACTION_OFFER: 0.0, A.CHECKOUT_LINK: 0.0,
        A.ESCALATE: 0.88, A.RETRY_SAME_INSTRUMENT: 0.0,
    },
}

#: For an unmodelled (class, action) pair. Conservative: it should look
#: unattractive, not free.
DEFAULT_EFFECTIVENESS = 0.25

#: Classes no intervention can recover, at any price.
ZERO_EFFECTIVENESS_CLASSES: frozenset[str] = frozenset({"ALREADY_PAID"})


def effectiveness(failure_class: str, action: RecoveryAction) -> float:
    if action is RecoveryAction.DROP or failure_class in ZERO_EFFECTIVENESS_CLASSES:
        return 0.0
    return ACTION_EFFECTIVENESS.get(failure_class, {}).get(action, DEFAULT_EFFECTIVENESS)


#: Share of customers who pay unprompted, per class — the merchant's own estimate,
#: the kind a no-contact cohort produces. Optimising lift over this (not gross
#: recovery) is what stops the engine paying to nudge people who'd return anyway.
ORGANIC_BASELINE: dict[str, float] = {
    "INSUFFICIENT_FUNDS": 0.20,
    "INSTRUMENT_INVALID": 0.08,
    "ISSUER_DECLINED": 0.15,
    "AUTH_FAILURE": 0.25,
    "RISK_BLOCKED": 0.05,
    "MERCHANT_CONFIG": 0.0,
    "ALREADY_PAID": 0.0,
    "UNKNOWN": 0.10,
}
DEFAULT_ORGANIC_BASELINE = 0.10


def organic_baseline(failure_class: str) -> float:
    return ORGANIC_BASELINE.get(failure_class, DEFAULT_ORGANIC_BASELINE)


@dataclass(frozen=True, slots=True)
class Valuation:
    """Every term behind one action's NEV — the row data for the per-option table."""

    action: RecoveryAction
    amount_minor: int
    currency_code: str
    base_propensity: float
    effectiveness: float
    probability: float
    organic_probability: float
    lift: float
    gross_expected_minor: int
    fee_minor: int
    cost_minor: int
    net_ev_minor: int

    def explain(self) -> str:
        m = lambda v: fmt(v, self.currency_code)  # noqa: E731
        return (
            f"{m(self.amount_minor)} x ({self.probability:.0%} with this action "
            f"- {self.organic_probability:.0%} without = {self.lift:.0%} lift) "
            f"= {m(self.gross_expected_minor)} incremental, less {m(self.fee_minor)} "
            f"PayPal fee and {m(self.cost_minor)} action cost = {m(self.net_ev_minor)} net"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "p_action": round(self.probability, 4),
            "p0": round(self.organic_probability, 4),
            "lift": round(self.lift, 4),
            "gross_expected_minor": self.gross_expected_minor,
            "fee_minor": self.fee_minor,
            "cost_minor": self.cost_minor,
            "net_ev_minor": self.net_ev_minor,
        }


def value_action(
    action: RecoveryAction,
    amount_minor: int,
    base_propensity: float,
    failure_class: str,
    policy: MerchantPolicy = DEFAULT_POLICY,
    effectiveness_for: Callable[[str, RecoveryAction], float] | None = None,
    currency_code: str = "USD",
) -> Valuation:
    """Net expected value of taking one action. See the module docstring for the formula."""
    if not 0.0 <= base_propensity <= 1.0:
        raise ValueError(f"base_propensity must be in [0, 1], got {base_propensity}")
    if amount_minor < 0:
        raise ValueError(f"amount_minor must be non-negative, got {amount_minor}")

    fit = (effectiveness_for or effectiveness)(failure_class, action)
    probability = base_propensity * fit
    p0 = base_propensity * organic_baseline(failure_class)
    lift = max(0.0, probability - p0)

    gross = round(amount_minor * policy.contribution_margin * lift)
    fee_on_capture = amount_minor * policy.processor_fee_rate + policy.processor_fee_fixed_minor
    fee = round(lift * fee_on_capture)
    cost = ACTION_COSTS[action].total_minor
    return Valuation(
        action=action, amount_minor=amount_minor, currency_code=currency_code,
        base_propensity=base_propensity, effectiveness=fit, probability=probability,
        organic_probability=p0, lift=lift, gross_expected_minor=gross, fee_minor=fee,
        cost_minor=cost, net_ev_minor=gross - fee - cost,
    )


def blind_retry_cost_minor(attempts: int) -> int:
    """Cost of the naive baseline: re-present the same instrument `attempts` times."""
    if attempts < 0:
        raise ValueError(f"attempts must be non-negative, got {attempts}")
    return attempts * ACTION_COSTS[RecoveryAction.RETRY_SAME_INSTRUMENT].total_minor
