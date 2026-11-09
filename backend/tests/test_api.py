import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.recurrence import add_months, next_due  # noqa: E402
from app import auth  # noqa: E402
from app.seed import seed_demo  # noqa: E402

TODAY = date(2026, 11, 1)
T = {"today": TODAY.isoformat()}


@pytest.fixture()
def app_(tmp_path, monkeypatch):
    monkeypatch.setenv("FT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("FT_SEED", "0")
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)  # keep tests fast
    auth._failures.clear()
    from app.main import app
    return app


def signup(c, email="me@example.com", password="correct horse"):
    r = c.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def client(app_):
    """A client logged in as me@example.com."""
    with TestClient(app_) as c:
        signup(c)
        yield c


def mk(client, name="Bill", amount=100, due=TODAY, category="Utilities", recurring="none"):
    r = client.post("/api/expenses", params=T, json={
        "name": name, "amount": amount, "due_date": due.isoformat(),
        "category": category, "recurring": recurring})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------- recurrence

def test_month_end_clamp_keeps_anchor():
    d = date(2026, 1, 31)
    feb = next_due(d, "monthly", 31)
    assert feb == date(2026, 2, 28)
    assert next_due(feb, "monthly", 31) == date(2026, 3, 31)


def test_other_recurrences():
    assert next_due(date(2026, 11, 1), "weekly") == date(2026, 11, 8)
    assert next_due(date(2026, 11, 1), "quarterly", 1) == date(2027, 2, 1)
    assert next_due(date(2026, 11, 1), "yearly", 1) == date(2027, 11, 1)
    assert next_due(date(2026, 11, 1), "none") is None
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert add_months(date(2026, 1, 15), -2) == date(2025, 11, 15)


# ------------------------------------------------------------- CRUD

def test_create_validation(client):
    bad = {"name": "x", "amount": 0, "due_date": "2026-11-01", "category": "A"}
    assert client.post("/api/expenses", json=bad).status_code == 422
    assert client.post("/api/expenses", json={**bad, "amount": 5, "name": "  "}).status_code == 422
    assert client.post("/api/expenses", json={**bad, "amount": 5, "recurring": "daily"}).status_code == 422


def test_update_and_delete(client):
    e = mk(client)
    r = client.put(f"/api/expenses/{e['id']}", params=T, json={
        "name": "Renamed", "amount": 250.5, "due_date": "2026-11-20",
        "category": "Food", "recurring": "monthly"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed" and r.json()["amount"] == 250.5
    assert r.json()["days_left"] == 19
    assert client.delete(f"/api/expenses/{e['id']}").status_code == 204
    assert client.delete(f"/api/expenses/{e['id']}").status_code == 404
    assert client.put("/api/expenses/999", json={
        "name": "n", "amount": 1, "due_date": "2026-11-01", "category": "c"}).status_code == 404


# ------------------------------------------------------ pay / unpay

def test_pay_recurring_creates_next(client):
    e = mk(client, recurring="monthly")
    r = client.post(f"/api/expenses/{e['id']}/pay", params=T).json()
    assert r["paid"] and r["paid_on"] == "2026-11-01" and r["urgency"] == "paid"
    unpaid = client.get("/api/expenses", params={"status": "unpaid", **T}).json()
    assert len(unpaid) == 1
    assert unpaid[0]["due_date"] == "2026-12-01"
    assert unpaid[0]["generated_from"] == e["id"]


def test_pay_is_idempotent(client):
    e = mk(client, recurring="monthly")
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    assert len(client.get("/api/expenses", params=T).json()) == 2


def test_pay_one_off_has_no_child(client):
    e = mk(client)
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    assert len(client.get("/api/expenses", params=T).json()) == 1


def test_month_end_chain_through_api(client):
    e = mk(client, due=date(2026, 1, 31), recurring="monthly")
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    feb = client.get("/api/expenses", params={"status": "unpaid", **T}).json()[0]
    assert feb["due_date"] == "2026-02-28"
    client.post(f"/api/expenses/{feb['id']}/pay", params=T)
    mar = client.get("/api/expenses", params={"status": "unpaid", **T}).json()[0]
    assert mar["due_date"] == "2026-03-31"


def test_unpay_removes_unpaid_child(client):
    e = mk(client, recurring="monthly")
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    r = client.post(f"/api/expenses/{e['id']}/unpay", params=T).json()
    assert not r["paid"] and r["paid_on"] is None
    assert len(client.get("/api/expenses", params=T).json()) == 1


def test_unpay_blocked_when_next_already_paid(client):
    e = mk(client, recurring="monthly")
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    child = client.get("/api/expenses", params={"status": "unpaid", **T}).json()[0]
    client.post(f"/api/expenses/{child['id']}/pay", params=T)
    assert client.post(f"/api/expenses/{e['id']}/unpay", params=T).status_code == 409


# --------------------------------------------------------- projections

def test_future_months_include_projected_recurring_bills(client):
    rent = mk(client, name="Rent", amount=20000, due=date(2026, 11, 5), recurring="monthly")
    mk(client, name="Insurance", amount=6000, due=date(2026, 11, 20), recurring="quarterly")
    mk(client, name="One-off", amount=50, due=date(2026, 11, 7))
    dec = client.get("/api/expenses", params={"month": "2026-12", **T}).json()
    assert [(e["name"], e["due_date"], e["projected"]) for e in dec] == [("Rent", "2026-12-05", True)]
    assert dec[0]["id"] is None and dec[0]["projected_from"] == rent["id"]
    feb = client.get("/api/expenses", params={"month": "2027-02", **T}).json()
    assert {e["name"] for e in feb} == {"Rent", "Insurance"}
    assert client.get("/api/expenses", params={"month": "2026-12", "projected": "false", **T}).json() == []


def test_projection_matches_what_paying_creates(client):
    e = mk(client, due=date(2026, 1, 31), recurring="monthly")
    proj = client.get("/api/expenses", params={"month": "2027-02", **T}).json()
    assert [x["due_date"] for x in proj] == ["2027-02-28"]  # month-end anchor kept
    mar = client.get("/api/expenses", params={"month": "2027-03", **T}).json()
    assert [x["due_date"] for x in mar] == ["2027-03-31"]
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    nov = client.get("/api/expenses", params={"month": "2026-11", **T}).json()
    assert [(x["due_date"], x["projected"]) for x in nov] == [("2026-11-30", True)]


def test_overdue_bill_does_not_block_or_backfill_the_series(client):
    mk(client, amount=500, due=date(2026, 8, 10), recurring="monthly")
    # past months stay as recorded; future months are projected
    assert client.get("/api/expenses", params={"month": "2026-09", **T}).json() == []
    nov = client.get("/api/expenses", params={"month": "2026-11", **T}).json()
    assert [(x["due_date"], x["projected"]) for x in nov] == [("2026-11-10", True)]
    s = client.get("/api/summary", params=T).json()
    assert s["overdue_count"] == 1


def test_paid_or_deleted_series_stops_projecting(client):
    e = mk(client, recurring="monthly")
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    child = client.get("/api/expenses", params={"status": "unpaid", **T}).json()[0]
    assert not child["projected"]  # the real next row, not a projection
    client.delete(f"/api/expenses/{child['id']}")
    assert client.get("/api/expenses", params={"month": "2027-01", **T}).json() == []
    assert client.get("/api/expenses", params={"month": "2026-12", "status": "paid", **T}).json() == []


def test_upcoming_includes_projections_in_window(client):
    mk(client, name="Gym", amount=300, due=TODAY, recurring="weekly")
    rows = client.get("/api/upcoming", params={"days": 21, **T}).json()
    assert [(r["due_date"], r["projected"]) for r in rows] == [
        ("2026-11-01", False), ("2026-11-08", True), ("2026-11-15", True), ("2026-11-22", True)]
    assert rows[1]["days_left"] == 7 and rows[1]["urgency"] == "later"


def test_summary_and_variance_count_projections(client):
    client.put("/api/settings", json={"total_budget": 30000})
    client.put("/api/budgets/Rent", json={"monthly_target": 20000})
    mk(client, amount=20000, due=date(2026, 11, 5), category="Rent", recurring="monthly")
    mk(client, amount=100, due=date(2026, 12, 3), category="Misc")
    s = client.get("/api/summary", params={"month": "2026-12", **T}).json()
    assert s["projected_total"] == 20000
    assert s["unpaid_total"] == 20100 and s["scheduled_total"] == 20100
    assert s["remaining"] == 9900
    v = client.get("/api/variance", params={"month": "2026-12", **T}).json()
    rent = next(r for r in v["rows"] if r["category"] == "Rent")
    assert rent["actual"] == 20000 and rent["status"] == "on"


# ----------------------------------------------------------- urgency

@pytest.mark.parametrize("offset,expected", [
    (-5, "overdue"), (-1, "overdue"), (0, "urgent"), (1, "urgent"),
    (2, "soon"), (3, "soon"), (4, "later"), (30, "later"),
])
def test_urgency_thresholds(client, offset, expected):
    e = mk(client, due=TODAY + timedelta(days=offset))
    assert e["urgency"] == expected
    assert e["days_left"] == offset


def test_upcoming_is_chronological_and_windowed(client):
    for off in (10, -2, 0, 5, 90):
        mk(client, name=f"b{off}", due=TODAY + timedelta(days=off))
    paid = mk(client, name="paid", due=TODAY + timedelta(days=1))
    client.post(f"/api/expenses/{paid['id']}/pay", params=T)
    rows = client.get("/api/upcoming", params={"days": 30, **T}).json()
    assert [r["name"] for r in rows] == ["b-2", "b0", "b5", "b10"]


# ------------------------------------------------- summary / variance

def test_summary_math(client):
    client.put("/api/settings", json={"total_budget": 1000})
    a = mk(client, amount=300, due=date(2026, 11, 5))
    mk(client, amount=200, due=date(2026, 11, 20))
    mk(client, amount=999, due=date(2026, 12, 2))  # next month - excluded
    client.post(f"/api/expenses/{a['id']}/pay", params=T)
    s = client.get("/api/summary", params={"month": "2026-11", **T}).json()
    assert s["total_budget"] == 1000
    assert s["scheduled_total"] == 500
    assert s["paid_total"] == 300 and s["unpaid_total"] == 200
    assert s["remaining"] == 500
    assert s["remaining_after_paid"] == 700
    assert s["percent_committed"] == 50


def test_summary_alert_counts(client):
    mk(client, amount=10, due=TODAY - timedelta(days=1))
    mk(client, amount=20, due=TODAY)
    mk(client, amount=30, due=TODAY + timedelta(days=3))
    mk(client, amount=40, due=TODAY + timedelta(days=4))
    s = client.get("/api/summary", params=T).json()
    assert (s["overdue_count"], s["overdue_amount"]) == (1, 10)
    assert (s["due_soon_count"], s["due_soon_amount"]) == (2, 50)


def test_summary_without_budget_does_not_divide_by_zero(client):
    mk(client, amount=50)
    s = client.get("/api/summary", params=T).json()
    assert s["total_budget"] == 0 and s["remaining"] == -50 and s["percent_committed"] == 0


def test_variance_signs_and_totals(client):
    client.put("/api/budgets/Food", json={"monthly_target": 1000})
    client.put("/api/budgets/Rent", json={"monthly_target": 5000})
    client.put("/api/budgets/Travel", json={"monthly_target": 400})
    mk(client, amount=1300, category="Food")
    mk(client, amount=5000, category="Rent")
    mk(client, amount=250, category="Misc")
    v = client.get("/api/variance", params={"month": "2026-11", **T}).json()
    rows = {r["category"]: r for r in v["rows"]}
    assert rows["Food"]["variance"] == -300 and rows["Food"]["status"] == "over"
    assert rows["Rent"]["variance"] == 0 and rows["Rent"]["status"] == "on"
    assert rows["Travel"]["variance"] == 400 and rows["Travel"]["status"] == "under"
    assert rows["Misc"]["variance"] is None and rows["Misc"]["status"] == "no_target"
    assert v["total_target"] == 6400
    assert v["total_actual"] == 6550
    assert v["total_variance"] == -150
    assert v["unbudgeted_actual"] == 250


def test_variance_merges_categories_case_insensitively(client):
    client.put("/api/budgets/Food", json={"monthly_target": 1000})
    mk(client, amount=100, category="food")
    mk(client, amount=200, category="FOOD")
    v = client.get("/api/variance", params={"month": "2026-11", **T}).json()
    assert len(v["rows"]) == 1
    assert v["rows"][0]["category"] == "Food" and v["rows"][0]["actual"] == 300


def test_budget_upsert_is_case_insensitive_and_deletable(client):
    client.put("/api/budgets/Food", json={"monthly_target": 1})
    client.put("/api/budgets/food", json={"monthly_target": 2})
    b = client.get("/api/budgets").json()
    assert b == [{"category": "Food", "monthly_target": 2}]
    assert client.delete("/api/budgets/FOOD").status_code == 204
    assert client.delete("/api/budgets/Food").status_code == 404


def test_month_filter_validation(client):
    assert client.get("/api/summary", params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/variance", params={"month": "nov"}).status_code == 422


def test_categories_union(client):
    client.put("/api/budgets/Food", json={"monthly_target": 1})
    mk(client, category="Rent")
    mk(client, category="food")
    assert client.get("/api/categories").json() == ["Food", "Rent"]


# --------------------------------------------------------------- seed

def test_seed_demo_data():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.execute("INSERT INTO users (email, password_hash) VALUES ('a@b.co', 'x')")
    seed_demo(conn, 1, TODAY)

    unpaid = conn.execute("SELECT name, due_date FROM expenses WHERE paid=0 ORDER BY due_date").fetchall()
    names = [r["name"] for r in unpaid]
    for expected in ("JioAirFiber", "EatClub", "Claude Pro", "Nifty 50 Index SIP", "HDFC Credit Card"):
        assert expected in names
    # Exactly one open occurrence per recurring bill, never two.
    assert len(names) == len(set(names))
    # The overdue demo is overdue; nothing paid is dated in the future.
    assert unpaid[0]["name"] == "Mobile Recharge" and unpaid[0]["due_date"] < TODAY.isoformat()
    assert conn.execute("SELECT COUNT(*) FROM expenses WHERE paid=1 AND due_date > ?",
                        (TODAY.isoformat(),)).fetchone()[0] == 0


def test_seeded_app_end_to_end(app_, monkeypatch):
    monkeypatch.setenv("FT_SEED", "1")
    with TestClient(app_) as c:
        me = signup(c)
        # registration seeds with the real date, so re-seed deterministically
        conn = db.connect()
        conn.executescript("DELETE FROM expenses; DELETE FROM budgets; DELETE FROM settings;")
        seed_demo(conn, me["id"], TODAY)
        conn.commit()
        conn.close()
        s = c.get("/api/summary", params={"month": "2026-11", **T}).json()
        assert s["total_budget"] == 70000
        assert s["scheduled_total"] == s["paid_total"] + s["unpaid_total"]
        assert s["remaining"] == s["total_budget"] - s["scheduled_total"]
        assert s["overdue_count"] == 1
        # Rent (today), ICICI card (tomorrow), JioAirFiber (+2), EatClub (+3)
        assert s["due_soon_count"] == 4
        up = c.get("/api/upcoming", params=T).json()
        assert [u["due_date"] for u in up] == sorted(u["due_date"] for u in up)
        oct_var = c.get("/api/variance", params={"month": "2026-10", **T}).json()
        food = next(r for r in oct_var["rows"] if r["category"] == "Food")
        assert food["status"] == "over" and food["variance"] == -1600


# ------------------------------------------------------------- backups

def _names(path):
    with sqlite3.connect(path) as c:
        return [r[0] for r in c.execute("SELECT name FROM expenses ORDER BY id")]


def test_backup_once_a_day_and_pruned(client, tmp_path, monkeypatch):
    from app import backup

    monkeypatch.setenv("FT_BACKUP_KEEP", "3")
    day = date(2027, 1, 1)  # clear of the startup snapshot, which uses the real date
    mk(client, name="Rent")
    first = backup.backup_if_due(day)
    assert first == tmp_path / "backups" / "finance-2027-01-01.db"
    assert _names(first) == ["Rent"]
    mk(client, name="Gym")
    assert backup.backup_if_due(day) is None  # already have today's
    assert _names(first) == ["Rent"]
    for i in range(1, 5):
        backup.backup_if_due(day + timedelta(days=i))
    assert [p.name for p in backup.list_backups()] == [
        "finance-2027-01-05.db", "finance-2027-01-04.db", "finance-2027-01-03.db"]


def test_first_write_of_the_day_takes_a_backup_first(client, tmp_path):
    from app import backup

    for f in backup.list_backups():  # the startup snapshot
        f.unlink()
    mk(client, name="Rent")
    (snap,) = backup.list_backups()
    assert _names(snap) == []  # the state before today's first change


def test_backup_can_be_disabled(client, monkeypatch):
    from app import backup

    monkeypatch.setenv("FT_BACKUP", "0")
    assert backup.backup_if_due(date(2027, 6, 1)) is None


def test_restore_saves_current_db_first(client, tmp_path):
    from app import backup

    mk(client, name="Rent")
    snap = backup.backup_if_due(date(2027, 6, 1))  # clear of the real-date startup snapshot
    mk(client, name="Oops")
    saved = backup.restore(snap)
    assert _names(db.db_path()) == ["Rent"]
    assert _names(saved) == ["Rent", "Oops"]
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    assert backup.main(["--restore", str(junk)]) == 1
    assert _names(db.db_path()) == ["Rent"]


def test_export_contains_only_my_data(app_):
    with TestClient(app_) as other:
        signup(other, "other@example.com")
        mk(other, name="Their rent")
    with TestClient(app_) as c:
        signup(c)
        mk(c, name="Rent")
        c.put("/api/settings", json={"total_budget": 500})
        r = c.get("/api/export")
    assert r.status_code == 200
    assert 'filename="bill-tracker-' in r.headers["content-disposition"]
    data = r.json()
    assert [e["name"] for e in data["expenses"]] == ["Rent"]
    assert data["settings"] == {"total_budget": "500.0"}
    assert "password_hash" not in r.text and "other@example.com" not in r.text


# ---------------------------------------------------------------- auth

def test_data_routes_need_login(app_):
    with TestClient(app_) as c:
        for method, path in [("GET", "/api/expenses"), ("GET", "/api/upcoming"), ("GET", "/api/summary"),
                             ("GET", "/api/variance"), ("GET", "/api/budgets"), ("GET", "/api/settings"),
                             ("GET", "/api/categories"), ("GET", "/api/export"), ("POST", "/api/expenses"),
                             ("POST", "/api/expenses/1/pay"), ("DELETE", "/api/expenses/1"),
                             ("PUT", "/api/settings"), ("GET", "/api/auth/me")]:
            assert c.request(method, path).status_code == 401, (method, path)
        assert c.get("/api/health").status_code == 200


def test_users_cannot_see_or_touch_each_others_data(app_):
    with TestClient(app_) as a, TestClient(app_) as b:
        signup(a, "a@example.com")
        signup(b, "b@example.com")
        mine = mk(a, name="A rent", category="Rent", recurring="monthly")
        a.put("/api/budgets/Rent", json={"monthly_target": 100})
        a.put("/api/settings", json={"total_budget": 999})

        assert b.get("/api/expenses", params=T).json() == []
        assert b.get("/api/expenses", params={"month": "2026-12", **T}).json() == []  # no projections either
        assert b.get("/api/upcoming", params=T).json() == []
        assert b.get("/api/budgets").json() == []
        assert b.get("/api/categories").json() == []
        assert b.get("/api/settings").json()["total_budget"] == 0
        assert b.get("/api/summary", params=T).json()["scheduled_total"] == 0
        assert b.get("/api/variance", params=T).json()["rows"] == []
        i = mine["id"]
        body = {"name": "x", "amount": 1, "due_date": "2026-11-01", "category": "x"}
        assert b.put(f"/api/expenses/{i}", params=T, json=body).status_code == 404
        assert b.post(f"/api/expenses/{i}/pay", params=T).status_code == 404
        assert b.post(f"/api/expenses/{i}/unpay", params=T).status_code == 404
        assert b.delete(f"/api/expenses/{i}").status_code == 404
        assert b.delete("/api/budgets/Rent").status_code == 404

        # and A's data is untouched
        assert [e["name"] for e in a.get("/api/expenses", params=T).json()] == ["A rent"]
        assert a.get("/api/settings").json()["total_budget"] == 999


def test_register_login_logout(app_):
    with TestClient(app_) as c:
        signup(c, "Me@Example.com ", "correct horse")
        assert c.get("/api/auth/me").json()["email"] == "me@example.com"
        assert c.post("/api/auth/logout").status_code == 204
        assert c.get("/api/auth/me").status_code == 401

        bad = c.post("/api/auth/login", json={"email": "me@example.com", "password": "wrong horse"})
        assert bad.status_code == 401 and bad.json()["detail"] == "Wrong email or password"
        nobody = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
        assert nobody.status_code == 401 and nobody.json()["detail"] == "Wrong email or password"
        ok = c.post("/api/auth/login", json={"email": "ME@example.com", "password": "correct horse"})
        assert ok.status_code == 200
        cookie = ok.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert c.get("/api/auth/me").status_code == 200


def test_register_validation_and_duplicates(app_):
    with TestClient(app_) as c:
        assert c.post("/api/auth/register", json={"email": "nope", "password": "longenough"}).status_code == 422
        assert c.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422
        signup(c, "a@b.co")
        dup = c.post("/api/auth/register", json={"email": "A@B.co", "password": "longenough"})
        assert dup.status_code == 409


def test_passwords_and_session_tokens_are_not_stored_in_plain_text(client):
    conn = db.connect()
    user = conn.execute("SELECT password_hash FROM users").fetchone()
    token = client.cookies.get(auth.COOKIE)
    stored = conn.execute("SELECT token_hash FROM sessions").fetchone()
    conn.close()
    assert "correct horse" not in user["password_hash"]
    assert user["password_hash"].startswith("pbkdf2_sha256$")
    assert token and stored["token_hash"] != token


def test_expired_session_is_rejected(client):
    conn = db.connect()
    conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    assert client.get("/api/expenses").status_code == 401


def test_login_is_throttled_after_repeated_failures(app_):
    with TestClient(app_) as c:
        signup(c)
        for _ in range(auth.MAX_FAILURES):
            c.post("/api/auth/login", json={"email": "me@example.com", "password": "wrong guess"})
        r = c.post("/api/auth/login", json={"email": "me@example.com", "password": "correct horse"})
        assert r.status_code == 429


def test_signups_can_be_closed_except_for_the_first_account(app_, monkeypatch):
    monkeypatch.setenv("FT_REGISTRATION", "0")
    with TestClient(app_) as c:
        signup(c, "owner@example.com")
        r = c.post("/api/auth/register", json={"email": "stranger@example.com", "password": "longenough"})
        assert r.status_code == 403


def test_existing_data_is_migrated_but_no_account_inherits_it(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            amount REAL NOT NULL, due_date TEXT NOT NULL, category TEXT NOT NULL,
            recurring TEXT NOT NULL DEFAULT 'none', anchor_day INTEGER NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0, paid_on TEXT, generated_from INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX idx_expenses_due ON expenses(due_date);
        CREATE TABLE budgets (category TEXT PRIMARY KEY, monthly_target REAL NOT NULL);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO expenses (name, amount, due_date, category, anchor_day) VALUES ('Rent', 900, '2026-11-05', 'Rent', 5);
        INSERT INTO budgets VALUES ('Rent', 1000);
        INSERT INTO settings VALUES ('total_budget', '5000'), ('seeded', '1');
    """)
    old.commit()
    old.close()
    monkeypatch.setenv("FT_DB", str(path))
    monkeypatch.setenv("FT_SEED", "0")
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    from app.main import app

    with TestClient(app) as owner, TestClient(app) as second:
        assert (tmp_path / "old.pre-accounts.db").exists()
        signup(owner, "owner@example.com")
        signup(second, "second@example.com")
        for c in (owner, second):
            assert c.get("/api/expenses", params=T).json() == []
            assert c.get("/api/budgets").json() == []
            assert c.get("/api/settings").json()["total_budget"] == 0
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM expenses WHERE user_id IS NULL").fetchone()[0] == 1  # kept, hidden
    conn.close()


def test_every_new_account_starts_empty(app_):
    with TestClient(app_) as first, TestClient(app_) as second:
        signup(first, "first@example.com")
        mk(first, name="Rent")
        signup(second, "second@example.com")
        assert second.get("/api/expenses", params=T).json() == []
        assert second.get("/api/summary", params=T).json()["scheduled_total"] == 0


# ------------------------------------------------------------ paid back

def test_paid_back_counts_against_bills_but_not_your_budget(client):
    client.put("/api/settings", json={"total_budget": 10000})
    client.put("/api/budgets/Credit Cards", json={"monthly_target": 8000})
    card = client.post("/api/expenses", params=T, json={
        "name": "HDFC Credit Card", "amount": 11000, "due_date": "2026-11-18", "category": "Credit Cards",
        "reimbursed": 4000, "reimbursed_note": "  Rahul - flight  "}).json()
    assert card["reimbursed"] == 4000 and card["reimbursed_note"] == "Rahul - flight"

    s = client.get("/api/summary", params={"month": "2026-11", **T}).json()
    assert s["scheduled_total"] == 11000 and s["unpaid_total"] == 11000  # you still owe the whole bill
    assert s["reimbursed_total"] == 4000 and s["own_spend"] == 7000
    assert s["remaining"] == 3000 and s["percent_committed"] == 70

    v = client.get("/api/variance", params={"month": "2026-11", **T}).json()
    row = v["rows"][0]
    assert (row["actual"], row["reimbursed"], row["variance"], row["status"]) == (7000, 4000, 1000, "under")

    client.post(f"/api/expenses/{card['id']}/pay", params=T)
    s = client.get("/api/summary", params={"month": "2026-11", **T}).json()
    assert s["paid_total"] == 11000 and s["remaining_after_paid"] == 3000


def test_paid_back_is_validated_and_cleared(client):
    base = {"name": "Card", "amount": 500, "due_date": "2026-11-05", "category": "Cards"}
    too_much = client.post("/api/expenses", params=T, json={**base, "reimbursed": 501})
    assert too_much.status_code == 422 and "more than the amount" in too_much.text
    assert client.post("/api/expenses", params=T, json={**base, "reimbursed": -1}).status_code == 422
    e = client.post("/api/expenses", params=T, json={**base, "reimbursed": 500, "reimbursed_note": "Asha"}).json()
    assert e["reimbursed"] == 500
    # editing it back to 0 drops the note too
    e = client.put(f"/api/expenses/{e['id']}", params=T, json={**base, "reimbursed": 0, "reimbursed_note": "Asha"}).json()
    assert e["reimbursed"] == 0 and e["reimbursed_note"] is None


def test_next_occurrence_does_not_inherit_paid_back(client):
    e = client.post("/api/expenses", params=T, json={
        "name": "Card", "amount": 900, "due_date": "2026-11-01", "category": "Cards",
        "recurring": "monthly", "reimbursed": 300}).json()
    dec_projected = client.get("/api/expenses", params={"month": "2026-12", **T}).json()
    assert [(x["amount"], x["reimbursed"]) for x in dec_projected] == [(900, 0)]
    client.post(f"/api/expenses/{e['id']}/pay", params=T)
    nxt = client.get("/api/expenses", params={"status": "unpaid", **T}).json()[0]
    assert (nxt["amount"], nxt["reimbursed"], nxt["reimbursed_note"]) == (900, 0, None)


def test_v1_database_gains_paid_back_columns(tmp_path, monkeypatch):
    path = tmp_path / "v1.db"
    old = sqlite3.connect(path)
    v1 = db.SCHEMA.replace("    reimbursed     REAL    NOT NULL DEFAULT 0,    -- part someone else paid back to you\n", "")
    v1 = v1.replace("    reimbursed_note TEXT,                          -- who / what for\n", "")
    assert "reimbursed" not in v1
    old.executescript(v1)
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()
    monkeypatch.setenv("FT_DB", str(path))
    monkeypatch.setenv("FT_SEED", "0")
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    from app.main import app

    with TestClient(app) as c:
        signup(c)
        assert mk(c)["reimbursed"] == 0
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
    assert {"reimbursed", "reimbursed_note", "payment_mode", "card_id"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()


# --------------------------------------------------------------- loans

def lend(c, **kw):
    body = {"person": "Rahul", "amount": 5000, "lent_on": "2026-10-20", **kw}
    r = c.post("/api/loans", params=T, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_loan_partial_repayments_until_closed(client):
    loan = lend(client, due_date="2026-11-30", note=" trip ")
    assert (loan["outstanding"], loan["status"], loan["days_to_due"], loan["note"]) == (5000, "open", 29, "trip")
    r = client.post(f"/api/loans/{loan['id']}/repayments", params=T, json={"amount": 2000})
    assert r.status_code == 201 and r.json()["outstanding"] == 3000
    assert r.json()["repayments"][0]["paid_on"] == "2026-11-01"
    too_much = client.post(f"/api/loans/{loan['id']}/repayments", params=T, json={"amount": 3001})
    assert too_much.status_code == 422
    done = client.post(f"/api/loans/{loan['id']}/repayments", params=T,
                       json={"amount": 3000, "paid_on": "2026-11-02"}).json()
    assert (done["outstanding"], done["status"], done["repaid"]) == (0, "repaid", 5000)
    # undoing a repayment reopens it
    rid = done["repayments"][-1]["id"]
    back = client.delete(f"/api/loans/{loan['id']}/repayments/{rid}", params=T).json()
    assert back["status"] == "open" and back["outstanding"] == 3000
    # the amount cannot drop below what was already repaid
    body = {"person": "Rahul", "amount": 1000, "lent_on": "2026-10-20"}
    assert client.put(f"/api/loans/{loan['id']}", params=T, json=body).status_code == 422


def test_loan_reminders_repeat_until_repaid(client):
    loan = lend(client, due_date="2026-11-05", remind_every_days=7)
    assert loan["next_remind_on"] == "2026-11-05" and not loan["reminder_due"]  # first reminder on the due date
    due = client.get("/api/loans", params={"today": "2026-11-06"}).json()[0]
    assert due["reminder_due"] and due["overdue"] and due["days_to_due"] == -1
    snoozed = client.post(f"/api/loans/{loan['id']}/reminded", params={"today": "2026-11-06"}).json()
    assert snoozed["next_remind_on"] == "2026-11-13" and not snoozed["reminder_due"]
    assert client.get("/api/loans", params={"today": "2026-11-13"}).json()[0]["reminder_due"]
    client.post(f"/api/loans/{loan['id']}/repayments", params=T, json={"amount": 5000})
    closed = client.get("/api/loans", params={"today": "2026-11-20"}).json()[0]
    assert closed["status"] == "repaid" and not closed["reminder_due"] and closed["next_remind_on"] is None


def test_loan_reminder_defaults_and_validation(client):
    no_due = lend(client, remind_every_days=3)
    assert no_due["next_remind_on"] == "2026-10-23"  # one interval after lending
    custom = lend(client, person="Asha", remind_every_days=14, first_reminder_on="2026-11-02")
    assert custom["next_remind_on"] == "2026-11-02"
    quiet = lend(client, person="Dev")
    assert quiet["next_remind_on"] is None
    assert client.post(f"/api/loans/{quiet['id']}/reminded", params=T).status_code == 409
    bad = client.post("/api/loans", params=T, json={"person": "X", "amount": 1, "lent_on": "2026-11-02",
                                                    "due_date": "2026-11-01"})
    assert bad.status_code == 422
    # reminder-first ordering
    order = [l["person"] for l in client.get("/api/loans", params=T).json()]
    assert order[0] == "Rahul"  # its reminder (23 Oct) is due
    # lending never touches the budget
    assert client.get("/api/summary", params=T).json()["scheduled_total"] == 0


def test_loans_are_private(app_):
    with TestClient(app_) as a, TestClient(app_) as b:
        signup(a, "a@example.com")
        signup(b, "b@example.com")
        loan = lend(a)
        assert b.get("/api/loans", params=T).json() == []
        assert b.post(f"/api/loans/{loan['id']}/repayments", params=T, json={"amount": 1}).status_code == 404
        assert b.post(f"/api/loans/{loan['id']}/reminded", params=T).status_code == 404
        assert b.delete(f"/api/loans/{loan['id']}").status_code == 404


# --------------------------------------------------------------- cards

def test_statement_cycle_maths():
    from app.cards import due_for, statement_for
    assert statement_for(date(2026, 11, 10), 15) == date(2026, 11, 15)
    assert statement_for(date(2026, 11, 15), 15) == date(2026, 11, 15)
    assert statement_for(date(2026, 11, 16), 15) == date(2026, 12, 15)
    assert statement_for(date(2026, 12, 20), 15) == date(2027, 1, 15)
    assert statement_for(date(2027, 2, 10), 31) == date(2027, 2, 28)  # month-end statement day clamps
    assert due_for(date(2026, 11, 15), 15, 5) == date(2026, 12, 5)  # due next month
    assert due_for(date(2026, 11, 15), 15, 28) == date(2026, 11, 28)  # due later the same month


def add_card(c, name="HDFC", statement_day=15, due_day=5):
    r = c.post("/api/cards", params=T, json={"name": name, "statement_day": statement_day, "due_day": due_day})
    assert r.status_code == 201, r.text
    return r.json()


def charge(c, card, name, amount, due, category="Shopping", recurring="none"):
    r = c.post("/api/expenses", params=T, json={
        "name": name, "amount": amount, "due_date": due, "category": category, "recurring": recurring,
        "payment_mode": "credit_card", "card_id": card["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_card_purchases_become_a_bill_instead_of_bills_each(client):
    card = add_card(client)
    charge(client, card, "Groceries", 1200, "2026-10-10", category="Food")   # statement 15 Oct, due 5 Nov
    charge(client, card, "Shoes", 3000, "2026-10-14")                        # same statement
    charge(client, card, "Dinner", 800, "2026-10-25", category="Food")       # statement 15 Nov (current)
    up = client.get("/api/upcoming", params={"days": 30, **T}).json()
    assert [(u["kind"], u["name"], u["amount"], u["due_date"], u["projected"]) for u in up] == [
        ("card_bill", "HDFC bill", 4200, "2026-11-05", False)]
    # purchases are spending in their own categories, already charged
    nov = client.get("/api/expenses", params={"month": "2026-10", **T}).json()
    assert all(e["paid"] for e in nov) and {e["category"] for e in nov} == {"Food", "Shopping"}
    oct_v = {r["category"]: r["actual"] for r in client.get("/api/variance", params={"month": "2026-10", **T}).json()["rows"]}
    assert oct_v == {"Food": 2000, "Shopping": 3000}
    s = client.get("/api/summary", params=T).json()
    assert (s["due_soon_count"], s["due_soon_amount"]) == (0, 0)  # 4 days away: outside the 3-day window
    s = client.get("/api/summary", params={"today": "2026-11-03"}).json()
    assert (s["due_soon_count"], s["due_soon_amount"]) == (1, 4200)

    cards = client.get("/api/cards", params=T).json()
    c = cards[0]
    assert c["due_now"] == 4200 and c["charged_this_cycle"] == 800
    assert c["current_statement"]["statement_date"] == "2026-11-15"
    assert c["current_statement"]["due_date"] == "2026-12-05"
    assert c["total_owed"] == 5000
    # each bill lists what is on it
    assert [(i["date"], i["name"], i["amount"]) for i in c["unpaid_statements"][0]["items"]] == [
        ("2026-10-10", "Groceries", 1200), ("2026-10-14", "Shoes", 3000)]
    assert [i["name"] for i in c["current_statement"]["items"]] == ["Dinner"]
    # each purchase links back to its expense, so it can be opened and moved to another card
    shoes = c["unpaid_statements"][0]["items"][1]["expense_id"]
    assert client.get(f"/api/expenses/{shoes}", params=T).json()["name"] == "Shoes"

    # paying the statement clears it; undo brings it back
    paid = client.post(f"/api/cards/{card['id']}/pay", params=T, json={"statement_date": "2026-10-15"}).json()
    assert paid["due_now"] == 0 and paid["total_owed"] == 800
    assert client.get("/api/upcoming", params={"days": 30, **T}).json() == []
    assert client.post(f"/api/cards/{card['id']}/pay", params=T,
                       json={"statement_date": "2026-10-15"}).status_code == 409
    client.post(f"/api/cards/{card['id']}/unpay", params=T, json={"statement_date": "2026-10-15"})
    assert client.get("/api/cards", params=T).json()[0]["due_now"] == 4200


def test_partial_card_payment_and_overdue(client):
    card = add_card(client)
    charge(client, card, "Laptop bag", 2000, "2026-09-20")  # statement 15 Oct, due 5 Nov
    client.post(f"/api/cards/{card['id']}/pay", params=T, json={"statement_date": "2026-10-15", "amount": 500})
    late = {"today": "2026-11-07"}
    up = client.get("/api/upcoming", params={"days": 7, **late}).json()
    bill = next(u for u in up if u["kind"] == "card_bill" and not u["projected"])
    assert (bill["amount"], bill["urgency"]) == (1500, "overdue")
    s = client.get("/api/summary", params=late).json()
    assert (s["overdue_count"], s["overdue_amount"]) == (1, 1500)
    over = client.post(f"/api/cards/{card['id']}/pay", params=late, json={"statement_date": "2026-10-15", "amount": 1501})
    assert over.status_code == 422


def test_recurring_card_charges_roll_onto_each_statement(client):
    card = add_card(client)
    charge(client, card, "Netflix", 649, "2026-09-12", category="Subscriptions", recurring="monthly")
    rows = client.get("/api/expenses", params=T).json()
    assert [(e["due_date"], e["paid"]) for e in rows] == [
        ("2026-09-12", True), ("2026-10-12", True), ("2026-11-12", False)]  # charged as each date passed
    c = client.get("/api/cards", params=T).json()[0]
    assert [s["statement_date"] for s in c["unpaid_statements"]] == ["2026-09-15", "2026-10-15"]
    assert c["current_statement"]["total"] == 649  # 12 Nov, still to be charged
    assert c["charged_this_cycle"] == 0
    # next month's projected charge carries the card too
    dec = client.get("/api/expenses", params={"month": "2026-12", **T}).json()
    assert [(e["projected"], e["card_id"]) for e in dec] == [(True, card["id"])]


def test_emis_add_instalments_to_statements_and_spending(client):
    card = add_card(client)
    r = client.post(f"/api/cards/{card['id']}/emis", params=T, json={
        "name": "iPhone", "category": "Electronics", "monthly_amount": 2000, "first_date": "2026-10-20", "months": 3})
    assert r.status_code == 201, r.text
    emi = r.json()
    assert (emi["last_date"], emi["months_done"], emi["months_left"], emi["remaining"]) == ("2026-12-20", 1, 2, 4000)

    nov = client.get("/api/expenses", params={"month": "2026-11", **T}).json()
    assert [(e["kind"], e["name"], e["amount"], e["paid"]) for e in nov] == [("emi", "iPhone EMI 2/3", 2000, False)]
    s = client.get("/api/summary", params={"month": "2026-11", **T}).json()
    assert s["scheduled_total"] == 2000 and s["unpaid_total"] == 2000
    v = client.get("/api/variance", params={"month": "2026-10", **T}).json()
    assert v["rows"][0]["category"] == "Electronics" and v["rows"][0]["actual"] == 2000
    assert "Electronics" in client.get("/api/categories").json()

    c = client.get("/api/cards", params=T).json()[0]
    # 20 Oct instalment is on the 15 Nov statement (current cycle, already charged)
    assert c["charged_this_cycle"] == 2000 and c["emi_remaining"] == 4000 and c["total_owed"] == 6000
    assert c["emis"][0]["name"] == "iPhone"
    # EMIs are not separate bills to pay
    assert all(u["kind"] != "emi" for u in client.get("/api/upcoming", params={"days": 90, **T}).json())

    client.put(f"/api/emis/{emi['id']}", params=T, json={
        "name": "iPhone", "category": "Electronics", "monthly_amount": 2000, "first_date": "2026-10-20", "months": 6})
    assert client.get("/api/cards", params=T).json()[0]["emi_remaining"] == 10000
    assert client.delete(f"/api/emis/{emi['id']}").status_code == 204
    assert client.get("/api/cards", params=T).json()[0]["total_owed"] == 0


def test_payment_mode_validation(client):
    card = add_card(client)
    base = {"name": "x", "amount": 10, "due_date": "2026-11-05", "category": "Food"}
    assert client.post("/api/expenses", params=T, json={**base, "payment_mode": "credit_card"}).status_code == 422
    assert client.post("/api/expenses", params=T, json={**base, "payment_mode": "barter"}).status_code == 422
    upi = client.post("/api/expenses", params=T, json={**base, "payment_mode": "upi", "card_id": card["id"]}).json()
    assert (upi["payment_mode"], upi["card_id"]) == ("upi", None)  # card only kept for credit cards
    # a plain UPI bill is still a bill to pay
    assert [u["name"] for u in client.get("/api/upcoming", params=T).json()] == ["x"]


def test_cards_are_private_and_deleting_keeps_purchases(app_):
    with TestClient(app_) as a, TestClient(app_) as b:
        signup(a, "a@example.com")
        signup(b, "b@example.com")
        card = add_card(a)
        charge(a, card, "Shoes", 3000, "2026-10-14")
        assert b.get("/api/cards", params=T).json() == []
        assert b.post(f"/api/cards/{card['id']}/pay", params=T, json={"statement_date": "2026-10-15"}).status_code == 404
        assert b.post(f"/api/cards/{card['id']}/emis", params=T, json={
            "name": "x", "monthly_amount": 1, "first_date": "2026-11-01", "months": 1}).status_code == 404
        steal = b.post("/api/expenses", params=T, json={"name": "x", "amount": 1, "due_date": "2026-11-01",
                                                        "category": "x", "payment_mode": "credit_card",
                                                        "card_id": card["id"]})
        assert steal.status_code == 422
        assert a.delete(f"/api/cards/{card['id']}").status_code == 204
        kept = a.get("/api/expenses", params=T).json()
        assert [(e["name"], e["card_id"]) for e in kept] == [("Shoes", None)]


def test_debit_cards_are_named_but_have_no_bill(client):
    debit = client.post("/api/cards", params=T, json={"name": "SBI", "kind": "debit"}).json()
    assert (debit["kind"], debit["statement_day"], debit["total_owed"]) == ("debit", None, 0)
    credit = add_card(client)
    assert client.post("/api/cards", params=T, json={"name": "X", "kind": "credit"}).status_code == 422  # needs days

    paid = client.post("/api/expenses", params=T, json={
        "name": "Fuel", "amount": 2000, "due_date": "2026-11-01", "category": "Transport",
        "payment_mode": "debit_card", "card_id": debit["id"]}).json()
    assert (paid["payment_mode"], paid["card_id"]) == ("debit_card", debit["id"])
    # debit purchases are ordinary bills (nothing auto-charged, no card bill)
    assert [u["name"] for u in client.get("/api/upcoming", params=T).json()] == ["Fuel"]
    # a debit card without saying which is fine too
    anon = client.post("/api/expenses", params=T, json={"name": "Taxi", "amount": 300, "due_date": "2026-11-01",
                                                        "category": "Transport", "payment_mode": "debit_card"})
    assert anon.status_code == 201 and anon.json()["card_id"] is None

    # cards must match the payment mode
    wrong = {"name": "x", "amount": 1, "due_date": "2026-11-01", "category": "x"}
    assert client.post("/api/expenses", params=T, json={**wrong, "payment_mode": "credit_card",
                                                         "card_id": debit["id"]}).status_code == 422
    assert client.post("/api/expenses", params=T, json={**wrong, "payment_mode": "debit_card",
                                                         "card_id": credit["id"]}).status_code == 422
    # no bills or EMIs on a debit card, and the type cannot be switched
    assert client.post(f"/api/cards/{debit['id']}/pay", params=T, json={"statement_date": "2026-11-15"}).status_code == 409
    assert client.post(f"/api/cards/{debit['id']}/emis", params=T, json={
        "name": "x", "monthly_amount": 1, "first_date": "2026-11-01", "months": 1}).status_code == 409
    assert client.put(f"/api/cards/{debit['id']}", params=T, json={"name": "SBI", "kind": "credit",
                                                                   "statement_day": 1, "due_day": 5}).status_code == 422
    renamed = client.put(f"/api/cards/{debit['id']}", params=T, json={"name": "SBI Savings", "kind": "debit"}).json()
    assert renamed["name"] == "SBI Savings"
    kinds = [(c["name"], c["kind"]) for c in client.get("/api/cards", params=T).json()]
    assert kinds == [("HDFC", "credit"), ("SBI Savings", "debit")]
