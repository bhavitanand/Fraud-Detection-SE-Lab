import pytest
from fastapi.testclient import TestClient

from app.db.session import connect
from app.main import create_app
from app.services import auth_service
from conftest import make_settings, tx

PW = "correct-horse-battery"


@pytest.fixture
def secured(tmp_path):
    s = make_settings(tmp_path, auth_required=True)
    app = create_app(s)
    conn = connect(s.db_path)
    auth_service.create_user(conn, "ana", PW, "analyst")
    auth_service.create_user(conn, "root", PW, "admin")
    conn.close()
    auth_service._fails.clear()
    with TestClient(app) as c:
        yield c


def login(c, user, pw=PW):
    return c.post("/api/auth/login", json={"username": user, "password": pw})


def hdr(c, user):
    return {"Authorization": "Bearer " + login(c, user).json()["access_token"]}


def test_health_is_public_everything_else_requires_auth(secured):
    assert secured.get("/api/health").status_code == 200
    for method, path in [("get", "/api/transactions"), ("get", "/api/cards"), ("get", "/api/audit"), ("get", "/api/reports"), ("get", "/api/config"),
                         ("post", "/api/cards/SYNTH-AAAA/block"), ("put", "/api/config")]:
        r = getattr(secured, method)(path)
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"] == "Bearer"


def test_login_success_and_failure(secured):
    ok = login(secured, "ana").json()
    assert ok["user"] == {"username": "ana", "role": "analyst"} and "password" not in str(ok)
    assert login(secured, "ana", "wrong-password").status_code == 401
    assert login(secured, "ghost").status_code == 401  # same response for unknown user
    me = secured.get("/api/auth/me", headers=hdr(secured, "ana")).json()
    assert me["role"] == "analyst"


def test_tampered_or_garbage_tokens_are_rejected(secured):
    t = login(secured, "ana").json()["access_token"]
    for bad in (t[:-3] + "abc", "garbage", ""):
        assert secured.get("/api/transactions", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_analyst_can_work_alerts_but_not_admin_actions(secured):
    h = hdr(secured, "ana")
    tid = secured.post("/api/transactions", json=tx(), headers=h).json()["id"]
    assert secured.post("/api/cards/SYNTH-AAAA/block", headers=h).status_code == 403
    assert secured.put("/api/config", json={"approve_max": .2, "hold_max": .6, "high_amount": 1000, "blocked_countries": "XX"}, headers=h).status_code == 403
    assert secured.post(f"/api/alerts/{tid}/review", json={"verdict": "CONFIRMED_FRAUD"}, headers=h).status_code == 200


def test_admin_actions_and_actor_in_audit(secured):
    h = hdr(secured, "root")
    assert secured.post("/api/cards/SYNTH-AAAA/block", headers=h).status_code == 200
    items = secured.get("/api/audit", headers=h).json()["items"]
    assert any(a["action"] == "card_blocked" and a["actor"] == "root" for a in items)
    login(secured, "root", "wrong-password")
    assert any(a["action"] == "login_failed" and a["detail"] == {"username": "root"} for a in secured.get("/api/audit", headers=h).json()["items"])


def test_lockout_after_repeated_failures(secured):
    for _ in range(5):
        assert login(secured, "ana", "nope-nope-nope").status_code == 401
    assert login(secured, "ana").status_code == 429  # even the right password waits


def test_passwords_are_hashed_and_policy_enforced(secured):
    s = secured.app.state.settings
    row = connect(s.db_path).execute("select password_hash from users where username='ana'").fetchone()[0]
    assert PW not in row and row.startswith("$argon2")
    from app.core.errors import Invalid
    with pytest.raises(Invalid):
        auth_service.create_user(connect(s.db_path), "weak", "short", "analyst")


def test_no_default_users_exist(tmp_path):
    s = make_settings(tmp_path, auth_required=True)
    with TestClient(create_app(s)) as c:
        assert c.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
    assert connect(s.db_path).execute("select count(*) from users").fetchone()[0] == 0
