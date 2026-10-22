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
        self._active: tuple[int, str, object] | None = None
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

    def load(self, model: dict | None) -> bool:
        """Make `model` (a registry row) the live model, or clear it when None. Returns True when a model is live."""
        with self._lock:
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
            self._active = (model["model_id"], f"{model['name']}", joblib.load(path))
            log.info("ML model %s is live", model["name"])
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
