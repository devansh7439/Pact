"""Counterfactual outcome oracle — the simulator's ground truth. SIMULATED only.

Two properties keep it unkind
to the system being evaluated:

**Organic recovery.** Some customers pay with no intervention. Evaluation credits
only *incremental* recovery — money that arrived because the engine acted.

**Common random numbers.** Every counterfactual for one intent resolves against a
single uniform draw fixed by the intent id, so strategy comparisons are paired
and interventions are monotone (if a weak action recovers, a stronger one does).

The oracle never sees a prediction, a decision or an expected value; it reads
only latent truth. Its organic rates are deliberately *not* the merchant's
estimates in `economics.ORGANIC_BASELINE` — the two are allowed to disagree.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from merchant.engine.economics import RecoveryAction, effectiveness
from merchant.simulator.generate import SyntheticEvent

ORGANIC_RECOVERY: dict[str, float] = {
    "INSUFFICIENT_FUNDS": 0.22,
    "INSTRUMENT_INVALID": 0.06,
    "ISSUER_DECLINED": 0.17,
    "AUTH_FAILURE": 0.27,
    "RISK_BLOCKED": 0.04,
    "MERCHANT_CONFIG": 0.0,
    "ALREADY_PAID": 0.0,
    "UNKNOWN": 0.10,
}
DEFAULT_ORGANIC = 0.10

#: Actions that need another saved source; with none, they cannot recover anything.
_NEEDS_ALTERNATE = frozenset({RecoveryAction.ALTERNATE_FUNDING_OFFER,
                              RecoveryAction.RETRY_AFTER_OFFER})


@dataclass(frozen=True, slots=True)
class Outcome:
    recovered: bool
    recovered_minor: int
    would_have_recovered_organically: bool
    incremental_minor: int
    p_action: float
    p_organic: float


def _draw(event_id: str) -> float:
    digest = hashlib.sha256(f"outcome:{event_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def organic_probability(event: SyntheticEvent, failure_class: str) -> float:
    return event._true_base_propensity * ORGANIC_RECOVERY.get(failure_class, DEFAULT_ORGANIC)


def observe(event: SyntheticEvent, action: RecoveryAction, failure_class: str) -> Outcome:
    """Adjudicate what happens when `action` is taken on `event`."""
    u = _draw(event.id)
    p_organic = organic_probability(event, failure_class)
    if action is RecoveryAction.DROP:
        p_action = p_organic
    else:
        fit = effectiveness(failure_class, action)
        if action in _NEEDS_ALTERNATE and event.alternate_funding_count == 0:
            fit = 0.0
        # An intervention cannot leave the customer worse off than doing nothing.
        p_action = max(event._true_base_propensity * fit, p_organic)

    recovered = u < p_action
    organic = u < p_organic
    return Outcome(
        recovered=recovered,
        recovered_minor=event.amount if recovered else 0,
        would_have_recovered_organically=organic,
        incremental_minor=event.amount if (recovered and not organic) else 0,
        p_action=p_action,
        p_organic=p_organic,
    )


def observe_do_nothing(event: SyntheticEvent, failure_class: str) -> Outcome:
    return observe(event, RecoveryAction.DROP, failure_class)
