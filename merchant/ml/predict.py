"""Inference: a failed payment -> calibrated base propensity.

The model learns P(recovery | reference action) from history collected under one
intervention (a checkout link). The policy engine needs an intervention-
independent number to price several actions against each other, so the
reference action's documented effectiveness is divided out:

    base_propensity = P(recovery | reference) / effectiveness[class][reference]

Every probability this produces is trained on simulated data and must be
labelled SIMULATED wherever it is shown (doc 05 §2).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from merchant.config import settings
from merchant.engine.economics import RecoveryAction, effectiveness
from merchant.ml.features import ALL_FEATURES, extract, failure_class_of

#: Never trained on: hard constraints resolve them before the model is consulted.
UNTRAINED_CLASSES: frozenset[str] = frozenset(
    {"RISK_BLOCKED", "ALREADY_PAID", "MERCHANT_CONFIG", "UNKNOWN"})

#: Divisor for untrained classes, ~ mean checkout-link effectiveness over trained ones.
NEUTRAL_REFERENCE_FIT = 0.64
MIN_USABLE_FIT = 0.05
INFERENCE_CHUNK = 4096

_lock = threading.Lock()
_bundle: dict[str, Any] | None = None


class ModelNotTrainedError(RuntimeError):
    pass


def load_model(path: Path | None = None) -> dict[str, Any]:
    """Load once and cache. An explicit `path` loads without touching the cache."""
    global _bundle
    if path is not None:
        if not path.exists():
            raise ModelNotTrainedError(f"No model at {path}. Run: python -m merchant.ml.train")
        return joblib.load(path)
    with _lock:
        if _bundle is None:
            if not settings.model_path.exists():
                raise ModelNotTrainedError(
                    f"No model at {settings.model_path}. Run: python -m merchant.ml.train")
            _bundle = joblib.load(settings.model_path)
    return _bundle


def predict_propensity_batch(events: list[Any], bundle: dict[str, Any] | None = None,
                             chunk_size: int = INFERENCE_CHUNK) -> list[float]:
    """Vectorised scoring in bounded chunks, so peak memory doesn't scale with input."""
    if not events:
        return []
    bundle = bundle or load_model()
    pipeline = bundle["pipeline"]
    reference = RecoveryAction(bundle["reference_action"])

    out: list[float] = []
    for start in range(0, len(events), chunk_size):
        window = events[start:start + chunk_size]
        frame = pd.DataFrame([extract(e) for e in window], columns=list(ALL_FEATURES))
        for event, p_ref in zip(window, pipeline.predict_proba(frame)[:, 1]):
            fc = failure_class_of(event)
            fit = effectiveness(fc, reference)
            # Dividing by a ~zero fit would send propensity to its ceiling.
            if fc in UNTRAINED_CLASSES or fit < MIN_USABLE_FIT:
                fit = NEUTRAL_REFERENCE_FIT
            out.append(float(min(1.0, max(0.0, p_ref / fit))))
    return out


def predict_propensity(event: Any) -> float:
    return predict_propensity_batch([event])[0]
