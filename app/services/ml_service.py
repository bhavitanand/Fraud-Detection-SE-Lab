"""Loads the active model from ml/artifacts after verifying its SHA-256 against the registry.

Pickle-based artifacts can execute code when loaded, so only files inside the fixed artifacts directory whose hash matches a
registry row are ever loaded. scikit-learn is an optional dependency: without it the app runs rules-only.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

log = logging.getLogger("fraud.ml")
ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "ml" / "artifacts"


class ModelService:
    def __init__(self, artifacts_dir: Path = ARTIFACTS_DIR) -> None:
        self.dir = artifacts_dir
        self._lock = threading.Lock()
        self._active: tuple[int, str, object] | None = None  # benchmark (ULB) model
        self._live: tuple[int, str, object] | None = None  # live (India features) model
        try:
            import joblib  # noqa: F401
            import numpy  # noqa: F401
            import sklearn  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False

    @property
    def active_id(self) -> int | None:
        return self._active[0] if self._active else None

    @property
    def live_id(self) -> int | None:
        live = getattr(self, "_live", None)
        return live[0] if live else None

    def unload(self, kind: str = "benchmark") -> None:
        with self._lock:
            if kind == "live":
                self._live = None
            else:
                self._active = None

    def load(self, model: dict | None, kind: str | None = None) -> bool:
        """Make `model` (a registry row) the active model of its kind, or clear the benchmark slot when None. Returns True when a model is live."""
        kind = kind or (model or {}).get("kind") or "benchmark"
        with self._lock:
            if kind == "live":
                self._live = None
            else:
                self._active = None
            if model is None:
                return False
            if not self.available:
                log.warning("scikit-learn not installed; ML scoring disabled, using rules only")
                return False
            path = (self.dir / Path(model["artifact_file"]).name).resolve()
            if self.dir.resolve() not in path.parents or not path.is_file():
                log.error("model artifact missing or outside the artifacts directory: %s", model["artifact_file"])
                return False
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != model["artifact_sha256"]:
                log.error("model artifact hash mismatch for %s; refusing to load", model["artifact_file"])
                return False
            import joblib
            try:
                obj = joblib.load(path)
            except Exception:  # e.g. a library the artifact needs is not installed: fall back to rules instead of failing at start-up
                log.exception("could not load model %s; using rules only", model["name"])
                return False
            if kind == "live":
                self._live = (model["model_id"], f"{model['name']}", obj)
            else:
                self._active = (model["model_id"], f"{model['name']}", obj)
            log.info("ML model %s (%s) is live", model["name"], kind)
            return True

    def predict(self, features: tuple[float, ...], amount: float):
        active = self._active
        if active is None:
            return None
        from ml.wrapper import make_row
        try:
            p = float(active[2].predict_fraud_proba(make_row(features, amount))[0])
        except Exception:  # a broken model must never break scoring
            log.exception("model prediction failed; falling back to rules")
            return None
        return p, active[0], active[1]

    def predict_live(self, vector: list[float]):
        """Probability and top feature attributions for one live transaction, or None when no live model is active."""
        live = getattr(self, "_live", None)
        if live is None:
            return None
        try:
            p, attribution = live[2].predict_with_attribution(vector)
        except Exception:
            log.exception("live model prediction failed; falling back to rules")
            return None
        return min(max(p, 0.0), 1.0), live[0], live[1], attribution
