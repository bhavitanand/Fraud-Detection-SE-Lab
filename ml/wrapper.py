"""Serialisable model = classifier + isotonic calibrator fitted on a validation split."""
from __future__ import annotations

import numpy as np

FEATURES = [f"V{i}" for i in range(1, 29)] + ["log1p_amount"]


def make_row(anon_features, amount: float) -> np.ndarray:
    return np.array([[*anon_features, np.log1p(max(amount, 0.0))]], dtype=float)


class CalibratedModel:
    def __init__(self, clf, calibrator) -> None:
        self.clf, self.calibrator = clf, calibrator

    def predict_fraud_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.clf.predict_proba(X)[:, 1]
        return np.clip(self.calibrator.predict(raw), 0.0, 1.0)


class LiveModel:
    """Calibrated classifier for the live (India) feature set, plus what is needed to explain a single prediction."""

    def __init__(self, calibrated, feature_names: list[str], baseline: list[float], groups: dict[str, list[str]]) -> None:
        self.model, self.feature_names, self.baseline, self.groups = calibrated, list(feature_names), np.asarray(baseline, dtype=float), groups

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict_fraud_proba(np.asarray(X, dtype=float))

    def predict_with_attribution(self, x: list[float], top: int = 4) -> tuple[float, list[dict]]:
        """Probability plus occlusion-based attribution: for each feature group, how much the probability drops when the group is
        replaced by its typical (training median) value. Positive impact = pushes the score towards fraud. Model-agnostic and approximate."""
        x = np.asarray(x, dtype=float)
        names = list(self.groups)
        rows = [x]
        for g in names:
            r = x.copy()
            for f in self.groups[g]:
                i = self.feature_names.index(f)
                r[i] = self.baseline[i]
            rows.append(r)
        p = self.predict(np.vstack(rows))
        base, impacts = float(p[0]), [(g, float(p[0] - p[k + 1])) for k, g in enumerate(names)]
        impacts.sort(key=lambda t: -t[1])
        return base, [{"feature": g, "impact": round(v, 4)} for g, v in impacts[:top] if v > 0.005]
