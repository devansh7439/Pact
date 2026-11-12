"""Feature extraction for the recovery-propensity model.

Everything here is data a real merchant already
holds: the PayPal decline and their own history with the customer. None of the
simulator's latent variables can appear, because `SyntheticEvent.features()`
drops underscore fields structurally.

New for Pact (doc 05 §2): channel, number of alternate saved sources, funding kind.
"""

from __future__ import annotations

import math
from typing import Any

from merchant.engine.taxonomy import classify

#: Pinned order — the serialised model depends on it.
NUMERIC_FEATURES: tuple[str, ...] = (
    "log_amount",
    "customer_success_rate",
    "customer_tenure_days",
    "prior_payment_count",
    "prior_failure_count",
    "failure_ratio",
    "hours_since_last_success",
    "attempt_number",
    "alternate_funding_count",
    "hour_of_day",
    "day_of_week",
    "is_business_hours",
    "is_weekend",
)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "channel",
    "funding_kind",
    "failure_class",
)

ALL_FEATURES: tuple[str, ...] = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def failure_class_of(event: Any) -> str:
    return classify(getattr(event, "processor_response_code", None),
                    getattr(event, "issue", None)).failure_class.value


def extract(event: Any) -> dict[str, Any]:
    """One feature row. Shared by training and live inference, so they cannot skew."""
    prior_payments = int(getattr(event, "prior_payment_count", 0))
    prior_failures = int(getattr(event, "prior_failure_count", 0))
    total_prior = prior_payments + prior_failures
    hour = int(getattr(event, "hour_of_day", 12))
    dow = int(getattr(event, "day_of_week", 0))
    return {
        "log_amount": math.log1p(float(getattr(event, "amount", 0))),
        "customer_success_rate": float(getattr(event, "customer_success_rate", 0.5)),
        "customer_tenure_days": float(getattr(event, "customer_tenure_days", 0)),
        "prior_payment_count": float(prior_payments),
        "prior_failure_count": float(prior_failures),
        "failure_ratio": (prior_failures / total_prior) if total_prior else 0.5,
        "hours_since_last_success": float(getattr(event, "hours_since_last_success", 0.0)),
        "attempt_number": float(getattr(event, "attempt_number", 1)),
        "alternate_funding_count": float(getattr(event, "alternate_funding_count", 0)),
        "hour_of_day": float(hour),
        "day_of_week": float(dow),
        "is_business_hours": 1.0 if 9 <= hour <= 20 else 0.0,
        "is_weekend": 1.0 if dow >= 5 else 0.0,
        "channel": str(getattr(event, "channel", "human")),
        "funding_kind": str(getattr(event, "funding_kind", "CARD")),
        "failure_class": failure_class_of(event),
    }
