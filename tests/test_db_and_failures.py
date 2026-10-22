import sqlite3

from fastapi.testclient import TestClient

from app.db import migrations
from app.db.init import init_database
from app.db.session import connect
from app.main import create_app
from conftest import make_settings, tx


def test_init_is_idempotent_and_seed_runs_once(settings):
    init_database(settings)
    init_database(settings)
    c = connect(settings.db_path)
    n = c.execute("select count(*) from transactions").fetchone()[0]
    assert n > 100 and migrations.current_version(c) == migrations.LATEST == 3
    assert c.execute("select count(*) from audit where action='demo_data_seeded'").fetchone()[0] == 1


def test_each_test_gets_an_isolated_database(tmp_path):
    a = TestClient(create_app(make_settings(tmp_path / "a", seed_demo=False)))
    b = TestClient(create_app(make_settings(tmp_path / "b", seed_demo=False)))
    a.post("/api/transactions", json=tx())
    assert a.get("/api/transactions").json()["total"] == 1 and b.get("/api/transactions").json()["total"] == 0


def test_legacy_v1_database_is_migrated_in_place(tmp_path):
    p = tmp_path / "legacy.sqlite"
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE transactions(id INTEGER PRIMARY KEY, token TEXT NOT NULL, amount REAL NOT NULL, merchant TEXT NOT NULL, country TEXT NOT NULL,
        channel TEXT NOT NULL, created TEXT NOT NULL, score REAL NOT NULL, decision TEXT NOT NULL, reasons TEXT NOT NULL, review TEXT NOT NULL DEFAULT 'OPEN');
      CREATE TABLE cards(token TEXT PRIMARY KEY, blocked INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
      INSERT INTO transactions(token,amount,merchant,country,channel,created,score,decision,reasons,review) VALUES
        ('SYNTH-1042',12,'Corner Cafe','US','POS','2026-01-01T00:00:00+00:00',0.04,'APPROVE','[]','OPEN'),
        ('SYNTH-9999',2000,'Shop','US','ONLINE','2026-01-02T00:00:00+00:00',0.49,'HOLD','["High amount"]','OPEN');
      INSERT INTO cards VALUES('SYNTH-9999',1);
      INSERT INTO config VALUES('approve_max','0.3'),('hold_max','0.7'),('high_amount','1500'),('blocked_countries','XX,RU');
    """)
    c.commit(); c.close()
    with TestClient(create_app(make_settings(tmp_path, db_path=p, seed_demo=False))) as client:
        items = {r["token"]: r for r in client.get("/api/transactions").json()["items"]}
        assert items["SYNTH-1042"]["review"] == "NOT_REQUIRED" and items["SYNTH-1042"]["source"] == "SEED"
        assert items["SYNTH-9999"]["review"] == "OPEN" and items["SYNTH-9999"]["reasons"] == ["High amount"]
        assert client.get("/api/config").json()["approve_max"] == 0.3  # existing config preserved
        assert client.get("/api/health").json()["schema_version"] == migrations.LATEST
        assert next(x for x in client.get("/api/cards").json() if x["token"] == "SYNTH-9999")["blocked"]


def test_database_failure_returns_503_without_leaking_details(settings):
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        settings.db_path.unlink()
        for ext in ("-wal", "-shm"):
            p = settings.db_path.with_name(settings.db_path.name + ext)
            p.exists() and p.unlink()
        settings.db_path.mkdir()  # path is now a directory: connect() fails
        r = c.get("/api/health")
        assert r.status_code == 503 and r.json()["error"]["code"] == "database_error"
        assert "sqlite" not in r.text.lower().replace("database_error", "")


def test_failed_ingest_rolls_back_everything(empty_client, monkeypatch):
    from app.repositories import db_access
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(db_access, "insert_audit", boom)
    c = TestClient(empty_client.app, raise_server_exceptions=False)
    assert c.post("/api/transactions", json=tx()).status_code == 503
    monkeypatch.undo()
    assert empty_client.get("/api/transactions").json()["total"] == 0  # transaction row rolled back with the failed audit write
    assert empty_client.get("/api/cards").json() == []


def test_unknown_route_and_method_use_error_shape(client):
    assert client.get("/api/nope").json()["error"]["code"] == "not_found"
    assert client.delete("/api/transactions").status_code == 405


def test_static_serving_falls_back_to_index_and_blocks_traversal(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>Fraud Desk</title>SPA-INDEX")
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    with TestClient(create_app(make_settings(tmp_path, seed_demo=False, frontend_dist=dist))) as c:
        assert "SPA-INDEX" in c.get("/transactions/5").text  # client-side route
        for evil in ("/..%2fsecret.txt", "/%2e%2e/secret.txt", "/../secret.txt"):
            assert "TOP-SECRET" not in c.get(evil).text
        assert c.get("/api/nope").status_code == 404 and "SPA-INDEX" not in c.get("/api/nope").text
