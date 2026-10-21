import os
import tempfile
from pathlib import Path

# Importing app.main builds a module-level app; point it at a throwaway DB, never the user's demo DB.
_import_dir = tempfile.mkdtemp(prefix="fraud-import-")
os.environ["FRAUD_DB"] = str(Path(_import_dir) / "import.sqlite")
os.environ["FRAUD_AUTH_REQUIRED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(db_path=tmp_path / "test.sqlite", auth_required=False, secret_key="test-secret-" + "x" * 32, seed_demo=True,
                frontend_dist=tmp_path / "no-dist")
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def empty_client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, seed_demo=False))) as c:
        yield c


def tx(**over):
    base = {"card_token": "SYNTH-TEST-7788", "amount": 2400, "merchant": "Synthetic Shop", "country": "US", "channel": "ONLINE"}
    return {**base, **over}
