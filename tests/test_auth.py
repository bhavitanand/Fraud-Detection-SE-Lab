import pytest
from fastapi.testclient import TestClient

from app.db.session import connect
from app.main import create_app
from app.services import auth_service
from conftest import make_settings, tx

PW = "correct-horse-battery"
ANA, ROOT = "ana@example.com", "root@example.com"


def build(tmp_path, **kw):
    s = make_settings(tmp_path, auth_required=True, **kw)
    app = create_app(s)
    conn = connect(s.db_path)
    auth_service.create_user(conn, ANA, PW, "analyst", "Ana")
    auth_service.create_user(conn, ROOT, PW, "admin", "Root")
    conn.close()
    auth_service._fails.clear()
    return app


@pytest.fixture
def secured(tmp_path):
    with TestClient(build(tmp_path)) as c:
        yield c


def login(c, email, pw=PW):
    return c.post("/api/auth/login", json={"email": email, "password": pw})


def hdr(c, email):
    return {"Authorization": "Bearer " + login(c, email).json()["access_token"]}


def test_health_is_public_everything_else_requires_auth(secured):
    assert secured.get("/api/health").status_code == 200
    for method, path in [("get", "/api/transactions"), ("get", "/api/cards"), ("get", "/api/audit"), ("get", "/api/reports"), ("get", "/api/config"),
                         ("get", "/api/users"), ("get", "/api/models"), ("get", "/api/notifications"), ("post", "/api/cards/SYNTH-AAAA/block"), ("put", "/api/config")]:
        r = getattr(secured, method)(path)
        assert r.status_code == 401, path
        assert r.headers["www-authenticate"] == "Bearer"


def test_login_success_and_failure(secured):
    ok = login(secured, ANA).json()
    assert ok["user"] == {"email": ANA, "name": "Ana", "role": "analyst"} and "password" not in str(ok)
    assert login(secured, "ANA@Example.com").status_code == 200  # e-mail is case-insensitive
    assert login(secured, ANA, "wrong-password").status_code == 401
    assert login(secured, "ghost@example.com").status_code == 401  # same response for unknown user
    assert secured.get("/api/auth/me", headers=hdr(secured, ANA)).json()["role"] == "analyst"


def test_tampered_or_garbage_tokens_are_rejected(secured):
    t = login(secured, ANA).json()["access_token"]
    for bad in (t[:-3] + "abc", "garbage", ""):
        assert secured.get("/api/transactions", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_analyst_can_work_alerts_but_not_admin_actions(secured):
    h = hdr(secured, ANA)
    tid = secured.post("/api/transactions", json=tx(), headers=h).json()["id"]
    assert secured.post("/api/cards/SYNTH-AAAA/block", headers=h).status_code == 403
    assert secured.put("/api/config", json={"approve_max": .2, "hold_max": .6, "high_amount": 1000, "blocked_countries": "XX"}, headers=h).status_code == 403
    for path in ("/api/users", "/api/audit/verify"):
        assert secured.get(path, headers=h).status_code == 403
    assert secured.post("/api/models/1/deploy", headers=h).status_code == 403
    assert secured.post("/api/models/benchmark/replay", headers=h).status_code == 403
    assert secured.post(f"/api/alerts/{tid}/review", json={"verdict": "CONFIRMED_FRAUD"}, headers=h).status_code == 200


def test_admin_actions_and_actor_in_audit(secured):
    h = hdr(secured, ROOT)
    assert secured.post("/api/cards/SYNTH-AAAA/block", headers=h).status_code == 200
    items = secured.get("/api/audit", headers=h).json()["items"]
    assert any(a["action"] == "card_blocked" and a["actor"] == ROOT for a in items)
    login(secured, ROOT, "wrong-password")
    assert any(a["action"] == "login_failed" and a["detail"] == {"email": ROOT} for a in secured.get("/api/audit", headers=h).json()["items"])


def test_lockout_after_repeated_failures(secured):
    for _ in range(5):
        assert login(secured, ANA, "nope-nope-nope").status_code == 401
    assert login(secured, ANA).status_code == 429  # even the right password waits


def test_passwords_are_hashed_and_policy_enforced(secured):
    s = secured.app.state.settings
    row = connect(s.db_path).execute("select password_hash from users where username=?", (ANA,)).fetchone()[0]
    assert PW not in row and row.startswith("$argon2")
    from app.core.errors import Invalid
    with pytest.raises(Invalid):
        auth_service.create_user(connect(s.db_path), "weak@example.com", "short", "analyst")


def test_no_default_users_exist(tmp_path):
    s = make_settings(tmp_path, auth_required=True)
    with TestClient(create_app(s)) as c:
        assert login(c, "admin@example.com", "admin").status_code == 401
    assert connect(s.db_path).execute("select count(*) from users").fetchone()[0] == 0


# ---- users page (administrator) ----
def test_admin_manages_users_and_new_user_can_sign_in(secured):
    h = hdr(secured, ROOT)
    new = {"email": "new.analyst@example.com", "name": "New Analyst", "role": "analyst", "password": "a-long-password-1"}
    assert secured.post("/api/users", json=new, headers=h).status_code == 201
    assert secured.post("/api/users", json=new, headers=h).status_code == 409
    assert secured.post("/api/users", json={**new, "email": "not-an-email"}, headers=h).status_code == 422
    assert secured.post("/api/users", json={**new, "email": "x@example.com", "password": "short"}, headers=h).status_code == 422
    assert login(secured, new["email"], new["password"]).status_code == 200
    emails = [u["email"] for u in secured.get("/api/users", headers=h).json()]
    assert new["email"] in emails
    assert "password_hash" not in secured.get("/api/users", headers=h).text
    assert secured.patch(f"/api/users/{new['email']}", json={"disabled": True}, headers=h).status_code == 200
    assert login(secured, new["email"], new["password"]).status_code == 401  # disabled accounts cannot sign in
    assert secured.put(f"/api/users/{new['email']}/password", json={"new_password": "another-long-pass"}, headers=h).status_code == 200


def test_last_admin_cannot_be_demoted_or_disabled(secured):
    h = hdr(secured, ROOT)
    assert secured.patch(f"/api/users/{ROOT}", json={"role": "analyst"}, headers=h).json()["error"]["code"] == "last_admin"
    assert secured.patch(f"/api/users/{ROOT}", json={"disabled": True}, headers=h).status_code == 409
    assert secured.patch("/api/users/ghost@example.com", json={"role": "admin"}, headers=h).status_code == 404


def test_disabled_user_loses_access_with_existing_token(secured):
    h_ana = hdr(secured, ANA)
    assert secured.get("/api/transactions", headers=h_ana).status_code == 200
    secured.patch(f"/api/users/{ANA}", json={"disabled": True}, headers=hdr(secured, ROOT))
    assert secured.get("/api/transactions", headers=h_ana).status_code == 401


def test_change_own_password(secured):
    h = hdr(secured, ANA)
    assert secured.put("/api/auth/password", json={"current_password": "wrong", "new_password": "brand-new-password"}, headers=h).status_code == 401
    assert secured.put("/api/auth/password", json={"current_password": PW, "new_password": "brand-new-password"}, headers=h).status_code == 200
    assert login(secured, ANA, PW).status_code == 401
    assert login(secured, ANA, "brand-new-password").status_code == 200


# ---- e-mail one-time code (second step) ----
@pytest.fixture
def otp_client(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.mailer.send_otp", lambda settings, to, code, minutes: sent.append((to, code)))
    with TestClient(build(tmp_path, login_otp=True)) as c:
        c.sent = sent
        yield c


def test_otp_login_flow(otp_client):
    r = login(otp_client, ANA).json()
    assert r["otp_required"] is True and "access_token" not in r and r["email_hint"].endswith("@example.com") and "ana@" not in r["email_hint"]
    (to, code), = otp_client.sent
    assert to == ANA and len(code) == 6
    ok = otp_client.post("/api/auth/otp", json={"challenge_id": r["challenge_id"], "code": code}).json()
    assert ok["user"]["email"] == ANA and ok["access_token"]
    assert otp_client.post("/api/auth/otp", json={"challenge_id": r["challenge_id"], "code": code}).status_code == 401  # single use


def test_otp_wrong_code_expiry_and_attempt_limit(otp_client):
    r = login(otp_client, ANA).json()
    code = otp_client.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    assert otp_client.post("/api/auth/otp", json={"challenge_id": r["challenge_id"], "code": wrong}).status_code == 401
    assert otp_client.post("/api/auth/otp", json={"challenge_id": r["challenge_id"], "code": "12ab56"}).status_code == 422
    conn = connect(otp_client.app.state.settings.db_path)
    conn.execute("UPDATE otp_challenges SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (r["challenge_id"],))
    assert otp_client.post("/api/auth/otp", json={"challenge_id": r["challenge_id"], "code": code}).status_code == 401  # expired
    assert otp_client.post("/api/auth/otp", json={"challenge_id": 9999, "code": code}).status_code == 401


def test_otp_not_issued_for_wrong_password_and_never_stored_or_audited_in_clear(otp_client):
    assert login(otp_client, ANA, "wrong-password").status_code == 401 and otp_client.sent == []
    r = login(otp_client, ANA).json()
    code = otp_client.sent[-1][1]
    conn = connect(otp_client.app.state.settings.db_path)
    stored = conn.execute("SELECT code_hash FROM otp_challenges WHERE id=?", (r["challenge_id"],)).fetchone()[0]
    assert code not in stored and len(stored) == 64
    assert code not in str(conn.execute("SELECT detail FROM audit").fetchall().__repr__().replace("'", " "))


def test_smtp_delivery_failure_is_reported(tmp_path, monkeypatch):
    import smtplib

    def boom(*a, **k):
        raise smtplib.SMTPException("down")

    monkeypatch.setattr("smtplib.SMTP", boom)
    app = build(tmp_path, login_otp=True, otp_delivery="smtp", smtp_host="smtp.invalid", smtp_from="noreply@example.com")
    with TestClient(app) as c:
        r = login(c, ANA)
        assert r.status_code == 503 and r.json()["error"]["code"] == "delivery_failed"


# ---- CLI and console delivery ----
def test_cli_creates_a_user_with_prompted_password(tmp_path, monkeypatch):
    from app import cli
    monkeypatch.setenv("FRAUD_DB", str(tmp_path / "cli.sqlite"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a-very-long-password")
    assert cli.main(["create-user", "--email", "Cli.User@Example.com", "--name", "Cli User", "--role", "admin"]) == 0
    u = connect(tmp_path / "cli.sqlite").execute("select username,role,name from users").fetchone()
    assert tuple(u) == ("cli.user@example.com", "admin", "Cli User")
    assert cli.main(["create-user", "--email", "cli.user@example.com", "--role", "admin"]) == 1  # duplicate is reported, not crashed
    pw = iter(["a-very-long-password", "different-password"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(pw))
    assert cli.main(["create-user", "--email", "b@example.com", "--role", "analyst"]) == 1  # mismatch


def test_console_delivery_prints_code_to_terminal_only(capsys):
    from app.services import mailer
    mailer.send_otp(make_settings(__import__("pathlib").Path("/tmp")), "x@example.com", "123456", 5)
    assert "123456" in capsys.readouterr().err
