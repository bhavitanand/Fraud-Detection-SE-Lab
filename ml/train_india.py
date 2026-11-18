"""Train and evaluate the LIVE fraud model on simulated Indian card transactions (see ml/simulator.py).

    python -m ml.train_india [--cards 3000] [--days 150] [--register]

Protocol (everything is written to the metadata JSON next to the artifact):
  * transactions are generated per card with ground-truth labels; features are computed with ml.features (identical to live scoring);
  * split by TIME (60/20/20): a later period is never used to train for an earlier one;
  * five candidates (logistic regression, random forest, histogram gradient boosting, XGBoost, LightGBM) are compared on VALIDATION PR-AUC;
  * the winner is calibrated with isotonic regression on the validation split; the test split is used once, for the report;
  * the test report compares rules only, the model only (what is deployed, plus a policy layer for blocked countries) and a variant that adds
    every rule on top of the model (rejected: it multiplies false positives), all at the app's thresholds.
Honest limits: the data are simulated. The numbers measure how well the pipeline finds the simulated fraud patterns (with deliberately hard cases
mixed in); they are not real-world accuracy.
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
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.services.scoring import HeuristicScorer, RiskConfig

from .features import FEATURES, GROUPS, vectorize
from .simulator import FRAUD_EPISODE_PER_CARD_DAY, FRAUD_PATTERNS, build_dataset
from .wrapper import CalibratedModel, LiveModel, PortableXGB

ART = Path(__file__).resolve().parent / "artifacts"
CFG = RiskConfig()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def noisy_or(rules: np.ndarray, p: np.ndarray) -> np.ndarray:
    return np.minimum(1.0, 1 - (1 - rules) * (1 - p))


def op_report(y, score, thr) -> dict:
    pred = (score > thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"threshold": round(float(thr), 4), "precision": round(float(precision_score(y, pred, zero_division=0)), 4), "recall": round(float(recall_score(y, pred)), 4),
            "f1": round(float(f1_score(y, pred, zero_division=0)), 4), "false_positive_rate": round(float(fp / max(fp + tn, 1)), 5),
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)}


def recall_at_fpr(y, score, fpr_target) -> float:
    neg = np.sort(score[y == 0])
    thr = neg[int(len(neg) * (1 - fpr_target))]
    return float((score[y == 1] > thr).mean())


def pr_points(y, score, k=60) -> list[list[float]]:
    p, r, _ = precision_recall_curve(y, score)
    idx = np.linspace(0, len(p) - 1, k).astype(int)
    return [[round(float(r[i]), 4), round(float(p[i]), 4)] for i in idx]


def candidates(pos_weight: float) -> dict:
    out = {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=400, class_weight="balanced", C=1.0)),
        "random_forest": RandomForestClassifier(n_estimators=120, max_depth=14, min_samples_leaf=8, max_samples=0.5, class_weight="balanced_subsample", n_jobs=-1, random_state=7),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0, class_weight="balanced", random_state=7),
    }
    try:
        from xgboost import XGBClassifier
        out["xgboost"] = XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.06, subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
                                       scale_pos_weight=min(pos_weight, 30.0), eval_metric="aucpr", tree_method="hist", n_jobs=2, random_state=7)
    except ImportError:
        print("xgboost not installed; skipping", file=sys.stderr)
    try:
        from lightgbm import LGBMClassifier
        out["lightgbm"] = LGBMClassifier(n_estimators=400, learning_rate=0.06, num_leaves=48, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                         scale_pos_weight=min(pos_weight, 30.0), n_jobs=2, random_state=7, verbose=-1)
    except ImportError:
        print("lightgbm not installed; skipping", file=sys.stderr)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=3000)
    ap.add_argument("--days", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20261118)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    rows, cards = build_dataset(a.cards, a.days, a.seed)
    n = len(rows)
    print(f"generated {n:,} transactions for {a.cards} cards in {time.time() - t0:.0f}s")
    rules = HeuristicScorer()
    X = np.array([vectorize(r[1]) for r in rows], dtype=float)
    y = np.array([r[0].label for r in rows], dtype=int)
    pattern = np.array([r[0].pattern for r in rows])
    rule_score = np.array([rules.score(r[1], CFG).score for r in rows], dtype=float)
    t_sorted = np.array([r[0].t.timestamp() for r in rows])
    order = np.argsort(t_sorted, kind="stable")
    X, y, pattern, rule_score = X[order], y[order], pattern[order], rule_score[order]
    i1, i2 = int(n * 0.6), int(n * 0.8)
    sl = {"train": slice(0, i1), "val": slice(i1, i2), "test": slice(i2, n)}
    split_info = {k: {"rows": int(len(y[s])), "frauds": int(y[s].sum()), "fraud_rate": round(float(y[s].mean()), 5)} for k, s in sl.items()}
    print("splits:", split_info)

    pos_weight = float((y[sl["train"]] == 0).sum() / max(y[sl["train"]].sum(), 1))
    val_ap, fitted, fit_secs = {}, {}, {}
    for name, clf in candidates(pos_weight).items():
        t1 = time.time()
        clf.fit(X[sl["train"]], y[sl["train"]])
        val_ap[name] = float(average_precision_score(y[sl["val"]], clf.predict_proba(X[sl["val"]])[:, 1]))
        fit_secs[name] = round(time.time() - t1, 1)
        fitted[name] = clf
        print(f"{name}: validation PR-AUC {val_ap[name]:.4f} ({fit_secs[name]}s)")
    best = max(val_ap, key=val_ap.get)
    clf = fitted[best]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(clf.predict_proba(X[sl["val"]])[:, 1], y[sl["val"]])
    from xgboost import XGBClassifier
    cal = CalibratedModel(PortableXGB(clf) if isinstance(clf, XGBClassifier) else clf, iso)
    baseline = np.median(X[sl["train"]], axis=0)
    live = LiveModel(cal, FEATURES, baseline.tolist(), GROUPS)

    Xt, yt, rt, pt = X[sl["test"]], y[sl["test"]], rule_score[sl["test"]], pattern[sl["test"]]
    p_test = live.predict(Xt)
    both = noisy_or(rt, p_test)
    thr = CFG.approve_max
    comp = {"rules_only": rt, "model_only": p_test, "rules_plus_model": both}
    hybrid = p_test  # deployed scoring = model probability (+ blocked-country policy, which never fires in simulated data)
    comparison = {k: {"pr_auc": round(float(average_precision_score(yt, v)), 4), "roc_auc": round(float(roc_auc_score(yt, v)), 4),
                      "recall_at_1pct_fpr": round(recall_at_fpr(yt, v, 0.01), 4), "at_app_threshold": op_report(yt, v, thr)} for k, v in comp.items()}
    per_pattern = {}
    for pat in FRAUD_PATTERNS:
        m = pt == pat
        if m.sum():
            per_pattern[pat] = {"count": int(m.sum()), "flagged_by_rules": round(float((rt[m] > thr).mean()), 3), "flagged_by_model": round(float((p_test[m] > thr).mean()), 3),
                                "declined_by_model": round(float((p_test[m] > CFG.hold_max).mean()), 3), "flagged_by_rules_plus_model": round(float((both[m] > thr).mean()), 3)}
    decisions = {"approve": int((hybrid <= thr).sum()), "hold": int(((hybrid > thr) & (hybrid <= CFG.hold_max)).sum()), "decline": int((hybrid > CFG.hold_max).sum())}
    # permutation importance by feature group on a test subsample (drop in PR-AUC when a group is shuffled)
    rng = np.random.default_rng(7)
    sub = rng.choice(len(yt), size=min(60000, len(yt)), replace=False)
    base_ap = average_precision_score(yt[sub], live.predict(Xt[sub]))
    importance = []
    for g, feats in GROUPS.items():
        Xp = Xt[sub].copy()
        idx = [FEATURES.index(f) for f in feats]
        Xp[:, idx] = Xp[rng.permutation(len(sub))][:, idx]
        importance.append({"feature": g, "pr_auc_drop": round(float(base_ap - average_precision_score(yt[sub], live.predict(Xp))), 4)})
    importance.sort(key=lambda d: -d["pr_auc_drop"])
    edges = [0, 0.01, 0.03, 0.1, 0.25, 0.5, 0.75, 1.0001]
    calibration = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p_test >= lo) & (p_test < hi)
        if m.sum():
            calibration.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "n": int(m.sum()), "mean_predicted": round(float(p_test[m].mean()), 4), "observed_rate": round(float(yt[m].mean()), 4)})

    metrics = {
        "selected": best, "validation_pr_auc_by_candidate": {k: round(v, 4) for k, v in val_ap.items()}, "fit_seconds": fit_secs,
        "test": {"pr_auc": comparison["model_only"]["pr_auc"], "roc_auc": comparison["model_only"]["roc_auc"], "prevalence": round(float(yt.mean()), 5),
                 "at_app_threshold": comparison["model_only"]["at_app_threshold"], "comparison": comparison, "per_pattern_recall": per_pattern, "hybrid_decisions": decisions,
                 "feature_importance": importance, "calibration": calibration,
                 "pr_curves": {k: pr_points(yt, v) for k, v in comp.items()}},
        "note": "Evaluated on SIMULATED transactions (chronological hold-out). 'at_app_threshold' is the deployed model: flagged (HOLD or DECLINE) when score > 0.25.",
    }
    ART.mkdir(exist_ok=True)
    name = f"india_{best}_{a.version}"
    artifact = ART / f"{name}.joblib"
    joblib.dump(live, artifact, compress=3)
    import sklearn
    meta = {
        "name": name, "kind": "live", "version": a.version, "algorithm": best, "artifact_file": artifact.name, "artifact_sha256": sha256_file(artifact),
        "trained_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "sklearn": sklearn.__version__, "features": FEATURES,
        "dataset": {"name": "Simulated Indian card transactions", "generator": "ml/simulator.py", "seed": a.seed, "cards": a.cards, "days": a.days, "rows": n,
                    "frauds": int(y.sum()), "fraud_rate": round(float(y.mean()), 5), "currency": "INR", "fraud_patterns": FRAUD_PATTERNS,
                    "fraud_episodes_per_card_day": FRAUD_EPISODE_PER_CARD_DAY},
        "split": {"method": "chronological 60/20/20 by transaction time", **split_info}, "metrics": metrics,
        "limitations": ["Trained and tested on SIMULATED Indian transactions; metrics show how well the system finds the simulated patterns, not real-world accuracy.",
                        "Simulated fraud prevalence (about 1.2%) is far higher than real-world rates, so precision is optimistic.",
                        "The model only sees card/merchant/location/time behaviour; it cannot see device, IP or customer-service signals.",
                        "Attributions on the transaction page are occlusion-based approximations, not exact Shapley values."],
    }
    (ART / f"{name}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: comparison[k]["pr_auc"] for k in comparison}), json.dumps(comparison["model_only"]["at_app_threshold"]))
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
