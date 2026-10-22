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
