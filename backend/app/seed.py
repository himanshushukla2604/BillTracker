"""Demo data so the dashboard is useful on first launch.

Amounts are illustrative placeholders in INR - edit or delete them in the UI.
Seeding runs once (tracked in the settings table), so deleting everything
will not bring the demo data back. Disable entirely with FT_SEED=0.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from .recurrence import add_months

# name, amount, day-of-month, category, recurring
RECURRING = [
    ("Rent", 22000, 1, "Rent", "monthly"),
    ("ICICI Credit Card", 6850, 2, "Credit Cards", "monthly"),
    ("JioAirFiber", 1179, 3, "Utilities", "monthly"),
    ("EatClub", 149, 4, "Subscriptions", "monthly"),
    ("Nifty 50 Index SIP", 10000, 5, "Investments", "monthly"),
    ("Flexi Cap SIP", 5000, 10, "Investments", "monthly"),
    ("Claude Pro", 1950, 12, "Subscriptions", "monthly"),
    ("HDFC Credit Card", 14200, 18, "Credit Cards", "monthly"),
    ("Electricity", 1450, 20, "Utilities", "monthly"),
]

# Left unpaid last month so the "overdue" state is visible in the demo.
OVERDUE_DEMO = ("Mobile Recharge", 349, 30, "Utilities", "monthly")

# name, amount, (months back from this month, day), category  - all paid one-offs
ONE_OFFS = [
    ("Groceries", 5200, (1, 8), "Food"),
    ("Dining out", 2400, (1, 15), "Food"),
    ("Fuel", 1800, (1, 22), "Transport"),
    ("Groceries", 1240, (0, 1), "Food"),
]

BUDGETS = {
    "Rent": 22000,
    "Utilities": 3000,
    "Subscriptions": 2500,
    "Investments": 15000,
    "Credit Cards": 20000,
    "Food": 6000,
    "Transport": 2000,
}
TOTAL_BUDGET = 70000


def _insert(conn, name, amount, due, category, recurring, anchor, paid, paid_on=None, parent=None) -> int:
    cur = conn.execute(
        "INSERT INTO expenses (name, amount, due_date, category, recurring, anchor_day, paid, paid_on, generated_from)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (name, amount, due.isoformat(), category, recurring, anchor, int(paid),
         paid_on.isoformat() if paid_on else None, parent),
    )
    return cur.lastrowid


def seed_if_empty(conn: sqlite3.Connection, today: date | None = None) -> bool:
    today = today or date.today()
    if conn.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
        return False
    if conn.execute("SELECT 1 FROM expenses LIMIT 1").fetchone():
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('seeded','1')")
        conn.commit()
        return False

    this_month = date(today.year, today.month, 1)
    prev_month = add_months(this_month, -1)

    for name, amount, day, category, rec in RECURRING:
        # Build the chain the way the app itself does: paid occurrences link to
        # the next one via generated_from; the first unpaid one ends the chain.
        due = add_months(prev_month, 0, day)
        parent = None
        while True:
            paid = due < today
            pid = _insert(conn, name, amount, due, category, rec, day, paid,
                          due if paid else None, parent)
            if not paid:
                break
            parent = pid
            due = add_months(due, 1, day)

    name, amount, day, category, rec = OVERDUE_DEMO
    _insert(conn, name, amount, add_months(prev_month, 0, day), category, rec, day, False)

    for name, amount, (back, day), category in ONE_OFFS:
        due = add_months(this_month, -back, day)
        if due > today:  # never seed a "paid" expense in the future
            continue
        _insert(conn, name, amount, due, category, "none", day, True, due)

    conn.executemany("INSERT INTO budgets VALUES (?,?)", BUDGETS.items())
    conn.execute("INSERT OR REPLACE INTO settings VALUES ('total_budget', ?)", (str(TOTAL_BUDGET),))
    conn.execute("INSERT OR REPLACE INTO settings VALUES ('seeded','1')")
    conn.commit()
    return True
