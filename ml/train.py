"""Train and evaluate a fraud classifier on the public ULB credit-card dataset (European cardholders, Sept 2013).

    python -m ml.train --csv data/creditcard.csv [--register]

Protocol (all choices are recorded in the metadata JSON next to the artifact):
  * exact duplicate rows are dropped before splitting (they would leak across splits);
  * rows are ordered by Time and split 60/20/20 into train / validation / test (no shuffling: a later period is never used to train
    for an earlier one);
  * candidates are compared on VALIDATION average precision (PR-AUC); the test split is only used for the final report;
  * an isotonic calibrator is fitted on the validation split so the output behaves like a probability;
  * features: V1..V28 (anonymised PCA components) and log(1+Amount). 'Time' is not used.
Limitations: PCA was fitted by the dataset authors on all rows before release, so mild leakage across the split cannot be excluded; the data
are 2013 European card-present/online transactions in EUR, not Indian transactions; only 492 frauds exist, so test metrics are noisy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score

from .wrapper import FEATURES, CalibratedModel

ART = Path(__file__).resolve().parent / "artifacts"
APP_APPROVE_MAX, RULE_BASE = 0.25, 0.04  # decision boundary used by the app; baseline rule score of a benchmark row
CITATION = ("Dal Pozzolo, Caelen, Johnson, Bontempi. Calibrating Probability with Undersampling for Unbalanced Classification. IEEE CIDM 2015. "
            "Dataset: ULB Machine Learning Group / Worldline, Credit Card Fraud Detection (Kaggle).")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _X(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([df[[f"V{i}" for i in range(1, 29)]].to_numpy(), np.log1p(df["Amount"].to_numpy())])


def _report(y, p, thr) -> dict:
    pred = (p > thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"threshold": round(float(thr), 4), "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y, pred)), 4), "f1": round(float(f1_score(y, pred)), 4), "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--register", action="store_true", help="register the artifact as a candidate in the app database (FRAUD_DB)")
    ap.add_argument("--version", default="v1")
    a = ap.parse_args(argv)
    t0 = time.time()
    raw = pd.read_csv(a.csv)
    n_raw = len(raw)
    df = raw.drop_duplicates().sort_values("Time", kind="stable").reset_index(drop=True)
    n = len(df)
    i1, i2 = int(n * 0.6), int(n * 0.8)
    parts = {"train": df.iloc[:i1], "val": df.iloc[i1:i2], "test": df.iloc[i2:]}
    X = {k: _X(v) for k, v in parts.items()}
    y = {k: v["Class"].to_numpy() for k, v in parts.items()}
    split_info = {k: {"rows": int(len(v)), "frauds": int(v["Class"].sum()), "time_from": float(v["Time"].min()), "time_to": float(v["Time"].max())} for k, v in parts.items()}
    print("splits:", split_info)

    candidates = {
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08, max_leaf_nodes=24, l2_regularization=1.0, class_weight="balanced", random_state=7),
        "random_forest": RandomForestClassifier(n_estimators=120, max_depth=10, min_samples_leaf=5, class_weight="balanced_subsample", n_jobs=-1, random_state=7),
    }
    val_ap, fitted = {}, {}
    for name, clf in candidates.items():
        clf.fit(X["train"], y["train"])
        val_ap[name] = float(average_precision_score(y["val"], clf.predict_proba(X["val"])[:, 1]))
        fitted[name] = clf
        print(f"{name}: validation PR-AUC {val_ap[name]:.4f}")
    best = max(val_ap, key=val_ap.get)
    clf = fitted[best]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(clf.predict_proba(X["val"])[:, 1], y["val"])
    model = CalibratedModel(clf, iso)

    p_val, p_test = model.predict_fraud_proba(X["val"]), model.predict_fraud_proba(X["test"])
    prec, rec, thr = precision_recall_curve(y["val"], p_val)
    f1s = 2 * prec * rec / np.maximum(prec + rec, 1e-12)
    best_thr = float(thr[int(np.argmax(f1s[:-1]))])
    app_thr = 1 - (1 - APP_APPROVE_MAX) / (1 - RULE_BASE)  # probability at which rule-base + model crosses approve_max
    metrics = {
        "selected": best, "validation_pr_auc_by_candidate": {k: round(v, 4) for k, v in val_ap.items()},
        "test": {"pr_auc": round(float(average_precision_score(y["test"], p_test)), 4), "roc_auc": round(float(roc_auc_score(y["test"], p_test)), 4),
                 "prevalence": round(float(y["test"].mean()), 5), "at_validation_f1_threshold": _report(y["test"], p_test, best_thr),
                 "at_app_threshold": _report(y["test"], p_test, app_thr)},
        "note": "PR-AUC of a random classifier equals the prevalence. 'at_app_threshold' is what the deployed app flags (HOLD or DECLINE) for a benchmark row.",
    }
    ART.mkdir(exist_ok=True)
    name = f"ulb_{best}_{a.version}"
    artifact = ART / f"{name}.joblib"
    joblib.dump(model, artifact, compress=3)
    # Enriched replay sample from the TEST split (20% fraud) so a live demo shows both outcomes. Not representative of real prevalence.
    rng = np.random.default_rng(7)
    test = parts["test"]
    fr, ok = test[test.Class == 1], test[test.Class == 0]
    sample = pd.concat([fr.sample(min(len(fr), 60), random_state=7), ok.sample(240, random_state=7)]).sample(frac=1, random_state=7)
    sample.to_csv(ART / "benchmark_sample.csv", index=False)
    meta = {
        "name": name, "version": a.version, "algorithm": best, "artifact_file": artifact.name, "artifact_sha256": sha256_file(artifact),
        "trained_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "sklearn": sklearn.__version__, "features": FEATURES,
        "dataset": {"name": "ULB Credit Card Fraud Detection", "file": a.csv.name, "sha256": sha256_file(a.csv), "rows_raw": n_raw, "duplicates_dropped": n_raw - n,
                    "rows_used": n, "frauds": int(df["Class"].sum()), "currency": "EUR", "citation": CITATION},
        "split": {"method": "chronological 60/20/20 by Time after de-duplication", **split_info}, "metrics": metrics,
        "benchmark_sample": {"file": "benchmark_sample.csv", "rows": int(len(sample)), "frauds": int(sample.Class.sum()), "source": "test split, enriched"},
        "limitations": ["Trained on 2013 European data in EUR, not Indian transactions.", "PCA features are anonymised; the model cannot use merchant, city or channel.",
                        "Only a few dozen frauds in the test split, so metrics have wide uncertainty.", "PCA was fitted by the dataset authors on all rows before release."],
    }
    (ART / f"{name}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(metrics, indent=2))
    print(f"saved {artifact.name} ({artifact.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.0f}s")
    if a.register:
        from app.core.config import Settings
        from app.db.init import init_database
        from app.db.session import connect
        from app.services.models_service import register_from_meta
        s = Settings.from_env()
        init_database(s)
        conn = connect(s.db_path)
        try:
            register_from_meta(conn, meta, status="candidate")
        except sqlite3.IntegrityError:
            print("already registered", file=sys.stderr)
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
