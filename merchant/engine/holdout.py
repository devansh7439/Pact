"""Live holdout: measure what Pact *caused* on real traffic (doc 05 §4).

Simulation-based incrementality is easy to dismiss, so a deterministic slice of
real intents the engine *would* have acted on gets no action at all. Recovery
rate (acted) minus recovery rate (held out) is the lift, reported with Wilson
intervals — and "not enough data yet" when the samples are too small to say.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace

from merchant.engine.economics import RecoveryAction
from merchant.engine.policy import PolicyDecision
from merchant.engine.taxonomy import Classification, FailureClass

BUCKETS = 10_000

#: Below this many intents per arm, the console says "not enough data yet".
MIN_SAMPLES_PER_ARM = 30


def assigned_to_holdout(intent_id: str, salt: str, rate: float) -> bool:
    """`sha256(intent_id + salt) mod 10000 < rate x 10000` — deterministic and auditable."""
    if not 0.0 <= rate <= 0.5:
        raise ValueError(f"holdout rate must be in [0, 0.5], got {rate}")
    digest = hashlib.sha256(f"{intent_id}{salt}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % BUCKETS < round(rate * BUCKETS)


def eligible(decision: PolicyDecision, classification: Classification,
             amount_minor: int, autonomy_ceiling_minor: int) -> bool:
    """Only intents where the engine would have acted, not risk, below the ceiling."""
    return (
        decision.action not in (RecoveryAction.DROP, RecoveryAction.ESCALATE)
        and classification.failure_class is not FailureClass.RISK_BLOCKED
        and amount_minor <= autonomy_ceiling_minor
    )


def apply(decision: PolicyDecision, classification: Classification, intent_id: str,
          amount_minor: int, *, salt: str, rate: float,
          autonomy_ceiling_minor: int) -> tuple[PolicyDecision, bool]:
    """Return (decision, held_out). A held-out decision keeps the action it *would*
    have taken in its rationale but becomes inert: action DROP, no offer."""
    if not (eligible(decision, classification, amount_minor, autonomy_ceiling_minor)
            and assigned_to_holdout(intent_id, salt, rate)):
        return decision, False
    held = replace(
        decision,
        action=RecoveryAction.DROP,
        rule_id="HELD_OUT",
        rationale=(f"Live holdout: would have taken {decision.action.value} "
                   f"({decision.rule_id}). No action sent, so this intent measures "
                   "what happens without Pact."),
        offer_actions=(),
        eligible_funding_aliases=(),
    )
    return held, True


@dataclass(frozen=True, slots=True)
class Interval:
    rate: float
    low: float
    high: float
    n: int


def wilson(successes: int, n: int, z: float = 1.96) -> Interval:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n <= 0:
        return Interval(0.0, 0.0, 0.0, 0)
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be in [0, n]: {successes}/{n}")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(p, max(0.0, centre - half), min(1.0, centre + half), n)


@dataclass(frozen=True, slots=True)
class LiftReport:
    acted: Interval
    held_out: Interval
    enough_data: bool

    @property
    def lift(self) -> float:
        return self.acted.rate - self.held_out.rate

    def to_dict(self) -> dict[str, object]:
        def iv(i: Interval) -> dict[str, float | int]:
            return {"rate": round(i.rate, 4), "low": round(i.low, 4),
                    "high": round(i.high, 4), "n": i.n}
        return {
            "acted": iv(self.acted), "held_out": iv(self.held_out),
            "lift": round(self.lift, 4) if self.enough_data else None,
            "enough_data": self.enough_data,
            "message": None if self.enough_data else "not enough data yet",
        }


def lift_report(acted_recovered: int, acted_n: int,
                held_recovered: int, held_n: int) -> LiftReport:
    """Recovery rate (acted) - recovery rate (held out). Report per provenance,
    never pooled across sandbox and simulated."""
    return LiftReport(
        acted=wilson(acted_recovered, acted_n),
        held_out=wilson(held_recovered, held_n),
        enough_data=min(acted_n, held_n) >= MIN_SAMPLES_PER_ARM,
    )
