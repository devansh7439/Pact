"""Multi-Armed Bandit & Bayesian Learning Loop (doc 05 §2, §6).

Audits and refines action effectiveness constants against observed recovery outcomes
using Beta-Bernoulli conjugate priors under bounded merchant exploration policies.

    p(a) = base_propensity * effectiveness(failure_class, action)

Priors start at the domain-expert constants from `ACTION_EFFECTIVENESS`.
When an outcome is verified (via webhooks or reconciler):
    - Recovered -> alpha += 1
    - Lost      -> beta += 1

Under bounded exploration (MerchantPolicy.explore_fraction > 0), Thompson Sampling
or posterior mean estimation explores alternative remedies safely below the amount ceiling.
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import asdict, dataclass
from typing import Any

from merchant.engine.economics import (
    ACTION_EFFECTIVENESS,
    MerchantPolicy,
    RecoveryAction,
)

logger = logging.getLogger(__name__)

#: Default pseudo-observation weight for expert priors.
DEFAULT_PRIOR_WEIGHT: float = 20.0


@dataclass(frozen=True, slots=True)
class BetaDistribution:
    """Beta(alpha, beta) conjugate prior for action recovery probability."""

    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError(f"alpha and beta must be positive: alpha={self.alpha}, beta={self.beta}")

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        total = self.alpha + self.beta
        return (self.alpha * self.beta) / (total * total * (total + 1.0))

    def update(self, success: bool, weight: float = 1.0) -> BetaDistribution:
        """Bayesian conjugate update with an observed outcome."""
        if success:
            return BetaDistribution(self.alpha + weight, self.beta)
        return BetaDistribution(self.alpha, self.beta + weight)

    def sample(self, rng: random.Random | None = None) -> float:
        """Thompson sampling draw from the Beta posterior."""
        r = rng or random
        return r.betavariate(self.alpha, self.beta)


def initial_prior(failure_class: str, action: RecoveryAction,
                  prior_weight: float = DEFAULT_PRIOR_WEIGHT) -> BetaDistribution:
    """Construct initial Beta prior centered on expert ACTION_EFFECTIVENESS."""
    cls_map = ACTION_EFFECTIVENESS.get(failure_class, {})
    eff = cls_map.get(action, 0.25)
    # Clamp slightly off 0/1 for numerical stability of Beta distribution
    eff = min(max(eff, 0.01), 0.99)
    alpha = max(0.5, eff * prior_weight)
    beta = max(0.5, (1.0 - eff) * prior_weight)
    return BetaDistribution(alpha, beta)


class BanditLearner:
    """Online Bayesian learner for recovery effectiveness across failure classes and actions."""

    def __init__(self, prior_weight: float = DEFAULT_PRIOR_WEIGHT,
                 initial_state: dict[str, dict[str, tuple[float, float]]] | None = None) -> None:
        self.prior_weight = prior_weight
        self._priors: dict[tuple[str, str], BetaDistribution] = {}

        # Initialize from provided state or defaults
        if initial_state:
            for fc, actions in initial_state.items():
                for act_str, (a, b) in actions.items():
                    try:
                        self._priors[(fc, act_str)] = BetaDistribution(a, b)
                    except ValueError:
                        pass

    def get_distribution(self, failure_class: str, action: RecoveryAction | str) -> BetaDistribution:
        """Retrieve the current Beta distribution for this failure class and action."""
        act_key = action.value if isinstance(action, RecoveryAction) else str(action)
        key = (failure_class, act_key)
        if key not in self._priors:
            act_enum = RecoveryAction(act_key) if act_key in RecoveryAction.__members__ else RecoveryAction.DROP
            self._priors[key] = initial_prior(failure_class, act_enum, self.prior_weight)
        return self._priors[key]

    def record_outcome(self, failure_class: str, action: RecoveryAction | str,
                       success: bool, weight: float = 1.0) -> BetaDistribution:
        """Incorporate an observed recovery outcome into the posterior."""
        act_key = action.value if isinstance(action, RecoveryAction) else str(action)
        key = (failure_class, act_key)
        dist = self.get_distribution(failure_class, act_key)
        updated = dist.update(success, weight)
        self._priors[key] = updated
        logger.info("Bandit update: %s / %s -> success=%s, new_mean=%.3f (alpha=%.2f, beta=%.2f)",
                    failure_class, act_key, success, updated.mean, updated.alpha, updated.beta)
        return updated

    def effective_rate(self, failure_class: str, action: RecoveryAction,
                       policy: MerchantPolicy, amount_minor: int,
                       rng: random.Random | None = None) -> float:
        """Calculate the action effectiveness under merchant policy exploration bounds."""
        dist = self.get_distribution(failure_class, action)

        # Exploration permitted only if policy enables it and amount is below safety ceiling
        can_explore = (policy.explore_fraction > 0.0 and
                       amount_minor <= policy.max_explore_amount_minor)

        if can_explore:
            # Thompson sampling with exploration fraction mixing
            r = rng or random
            if r.random() < policy.explore_fraction:
                sample_val = dist.sample(rng)
                return max(0.0, min(1.0, sample_val))

        # Default: deterministic posterior mean
        return dist.mean

    def export_state(self) -> dict[str, dict[str, dict[str, float]]]:
        """Export serialized summary for reporting, metrics, and persistence."""
        out: dict[str, dict[str, dict[str, float]]] = {}
        for (fc, act), dist in self._priors.items():
            if fc not in out:
                out[fc] = {}
            out[fc][act] = {
                "alpha": round(dist.alpha, 3),
                "beta": round(dist.beta, 3),
                "mean": round(dist.mean, 4),
                "variance": round(dist.variance, 5),
            }
        return out

    def serialize_json(self) -> str:
        """Serialize state to canonical JSON string."""
        raw: dict[str, dict[str, list[float]]] = {}
        for (fc, act), dist in self._priors.items():
            if fc not in raw:
                raw[fc] = {}
            raw[fc][act] = [dist.alpha, dist.beta]
        return json.dumps(raw, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str, prior_weight: float = DEFAULT_PRIOR_WEIGHT) -> BanditLearner:
        """Reconstitute learner from JSON string."""
        raw = json.loads(json_str) if json_str.strip() else {}
        state: dict[str, dict[str, tuple[float, float]]] = {}
        for fc, acts in raw.items():
            state[fc] = {act: (vals[0], vals[1]) for act, vals in acts.items()}
        return cls(prior_weight=prior_weight, initial_state=state)


#: Shared singleton learner instance for the merchant decision pipeline.
bandit = BanditLearner()
