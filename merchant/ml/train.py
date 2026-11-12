"""Train and calibrate the recovery-propensity model.

Three choices matter more than the estimator:

**Calibration, not accuracy.** The probability gets multiplied by dollars, so the
estimator is wrapped in isotonic `CalibratedClassifierCV` and the headline metric
is the Brier score.

**Split by customer, not by row.** Customers recur; a row split would let the
model score well by recognising people. `GroupShuffleSplit` on customer_id.

**Train only on the population that gets scored.** Risk, already-paid, merchant
config and undiagnosed declines are resolved by hard constraints first, so they
are excluded.

Fix vs the original: the latent-propensity diagnostic divided every prediction by
one class's effectiveness; it now divides each by its own class's fit, matching
what inference does.

    python -m merchant.ml.train
"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from merchant.config import DATA_DIR, settings
from merchant.engine.economics import RecoveryAction, effectiveness
from merchant.ml.features import (
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    extract,
    failure_class_of,
)
from merchant.ml.predict import UNTRAINED_CLASSES
from merchant.simulator.generate import SyntheticEvent, generate_events
from merchant.simulator.oracle import observe

#: The intervention historical outcomes were collected under: "send everyone a
#: checkout link", which is what most off-the-shelf recovery tools do.
REFERENCE_ACTION = RecoveryAction.CHECKOUT_LINK

METRICS_PATH = DATA_DIR / "model_metrics.json"


@dataclass(slots=True)
class TrainingReport:
    """Held-out performance. Every figure comes from unseen customers. SIMULATED."""

    n_total: int
    n_train: int
    n_test: int
    n_excluded: int
    base_rate: float
    roc_auc: float
    brier: float
    brier_baseline: float
    brier_improvement: float
    propensity_correlation: float
    oracle_auc: float
    oracle_brier: float
    signal_captured: float
    calibration_bins: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {"provenance": "simulated",
                **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}}


def build_pipeline(seed: int = 42, n_estimators: int = 500) -> Pipeline:
    """Preprocessing plus a shallow, regularised forest, isotonically calibrated."""
    prep = ColumnTransformer([
        ("num", StandardScaler(), list(NUMERIC_FEATURES)),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
         list(CATEGORICAL_FEATURES)),
    ])
    forest = RandomForestClassifier(n_estimators=n_estimators, max_depth=10,
                                    min_samples_leaf=25, max_features=0.5,
                                    random_state=seed, n_jobs=-1)
    return Pipeline([("prep", prep),
                     ("model", CalibratedClassifierCV(forest, method="isotonic", cv=5))])


def _label_events(events: list[SyntheticEvent]):
    rows, labels, groups, latent, true_p, fits = [], [], [], [], [], []
    for event in events:
        fc = failure_class_of(event)
        if fc in UNTRAINED_CLASSES:
            continue
        outcome = observe(event, REFERENCE_ACTION, fc)
        rows.append(extract(event))
        labels.append(int(outcome.recovered))
        groups.append(event.customer_id)
        latent.append(event._true_base_propensity)
        true_p.append(outcome.p_action)
        fits.append(effectiveness(fc, REFERENCE_ACTION))
    return rows, labels, groups, latent, true_p, fits


def _calibration_bins(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 8):
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = []
    for lo, hi in itertools.pairwise(edges):
        mask = (y_prob >= lo) & (y_prob < hi if hi < 1.0 else y_prob <= hi)
        if mask.any():
            bins.append({"range": f"{lo:.2f}-{hi:.2f}", "n": int(mask.sum()),
                         "predicted": round(float(y_prob[mask].mean()), 4),
                         "observed": round(float(y_true[mask].mean()), 4)})
    return bins


def train(n_events: int = 8000, seed: int = 20261111, test_fraction: float = 0.25,
          save: bool = True, model_path: Path | None = None,
          metrics_path: Path | None = None, n_estimators: int = 500,
          ) -> tuple[Pipeline, TrainingReport]:
    events = generate_events(n_events, seed=seed)
    rows, labels, groups, latent, true_p, fits = _label_events(events)
    if len(rows) < 100:
        raise ValueError(f"Not enough trainable events: {len(rows)}")

    X = pd.DataFrame(rows, columns=list(ALL_FEATURES))
    y, g = np.asarray(labels), np.asarray(groups)
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_fraction, random_state=seed)
    train_idx, test_idx = next(splitter.split(X, y, groups=g))

    pipeline = build_pipeline(n_estimators=n_estimators)
    pipeline.fit(X.iloc[train_idx], y[train_idx])
    y_test = y[test_idx]
    y_prob = pipeline.predict_proba(X.iloc[test_idx])[:, 1]

    base_rate = float(y[train_idx].mean())
    brier = float(brier_score_loss(y_test, y_prob))
    brier_baseline = float(brier_score_loss(y_test, np.full_like(y_prob, base_rate)))

    # Diagnostic only (possible because this is a simulation): did the model
    # recover the latent driver it never saw? Per-class divisor, as inference does.
    derived = np.clip(y_prob / np.maximum(np.asarray(fits)[test_idx], 1e-6), 0, 1)
    correlation = float(np.corrcoef(derived, np.asarray(latent)[test_idx])[0, 1])

    # The ceiling: scoring the true probabilities against realised labels.
    p_test = np.asarray(true_p)[test_idx]
    oracle_auc = float(roc_auc_score(y_test, p_test))
    roc_auc = float(roc_auc_score(y_test, y_prob))
    attainable = oracle_auc - 0.5

    report = TrainingReport(
        n_total=len(events), n_train=len(train_idx), n_test=len(test_idx),
        n_excluded=len(events) - len(rows), base_rate=base_rate, roc_auc=roc_auc,
        brier=brier, brier_baseline=brier_baseline,
        brier_improvement=(brier_baseline - brier) / brier_baseline,
        propensity_correlation=correlation, oracle_auc=oracle_auc,
        oracle_brier=float(brier_score_loss(y_test, p_test)),
        signal_captured=(roc_auc - 0.5) / attainable if attainable > 1e-9 else 0.0,
        calibration_bins=_calibration_bins(y_test, y_prob),
    )

    if save:
        mp, xp = model_path or settings.model_path, metrics_path or METRICS_PATH
        mp.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": pipeline, "reference_action": REFERENCE_ACTION.value,
                     "features": list(ALL_FEATURES), "trained_on": n_events,
                     "seed": seed, "provenance": "simulated"}, mp)
        xp.write_text(json.dumps(report.to_dict(), indent=2))
    return pipeline, report


def main() -> None:
    _, r = train()
    d = r.to_dict()
    print("=" * 68)
    print("  Pact - recovery propensity model   [SIMULATED data]")
    print("=" * 68)
    print(f"  corpus              {d['n_total']:,} events ({d['n_excluded']:,} excluded)")
    print(f"  train / test        {d['n_train']:,} / {d['n_test']:,} (split by customer)")
    print(f"  base recovery rate  {d['base_rate']:.1%}")
    print(f"  Brier               {d['brier']:.4f}  (base-rate {d['brier_baseline']:.4f}, "
          f"perfect-knowledge {d['oracle_brier']:.4f})")
    print(f"  ROC AUC             {d['roc_auc']:.4f}  (ceiling {d['oracle_auc']:.4f}, "
          f"{d['signal_captured']:.0%} of attainable)")
    print(f"  latent propensity r {d['propensity_correlation']:.3f}")
    for b in d["calibration_bins"]:
        print(f"    {b['range']:<12}{b['n']:>6}{b['predicted']:>10.3f}{b['observed']:>10.3f}")


if __name__ == "__main__":
    main()
