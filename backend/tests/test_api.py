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
from app.seed import seed_if_empty  # noqa: E402

TODAY = date(2026, 11, 1)
T = {"today": TODAY.isoformat()}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("FT_SEED", "0")
    from app.main import app

    with TestClient(app) as c:
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
    assert seed_if_empty(conn, TODAY) is True
    assert seed_if_empty(conn, TODAY) is False  # runs once

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


def test_seeded_app_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("FT_DB", str(tmp_path / "s.db"))
    monkeypatch.setenv("FT_SEED", "1")
    # lifespan seeds with the real date, so re-seed deterministically afterwards
    from app.main import app

    with TestClient(app) as c:
        conn = db.connect()
        conn.executescript("DELETE FROM expenses; DELETE FROM budgets; DELETE FROM settings;")
        conn.commit()
        seed_if_empty(conn, TODAY)
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
