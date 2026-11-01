"""Demo data for trying the dashboard out.

Amounts are illustrative placeholders in INR - edit or delete them in the UI.
New accounts start empty; set FT_SEED=1 to give each new account this data.
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


def seed_demo(conn: sqlite3.Connection, user_id: int, today: date | None = None) -> None:
    """Fill one account with demo bills, targets and a budget. The caller commits."""
    today = today or date.today()

    def _insert(name, amount, due, category, recurring, anchor, paid, paid_on=None, parent=None) -> int:
        cur = conn.execute(
            "INSERT INTO expenses (user_id, name, amount, due_date, category, recurring, anchor_day, paid,"
            " paid_on, generated_from) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, name, amount, due.isoformat(), category, recurring, anchor, int(paid),
             paid_on.isoformat() if paid_on else None, parent),
        )
        return cur.lastrowid

    this_month = date(today.year, today.month, 1)
    prev_month = add_months(this_month, -1)

    for name, amount, day, category, rec in RECURRING:
        # Build the chain the way the app itself does: paid occurrences link to
        # the next one via generated_from; the first unpaid one ends the chain.
        due = add_months(prev_month, 0, day)
        parent = None
        while True:
            paid = due < today
            pid = _insert(name, amount, due, category, rec, day, paid,
                          due if paid else None, parent)
            if not paid:
                break
            parent = pid
            due = add_months(due, 1, day)

    name, amount, day, category, rec = OVERDUE_DEMO
    _insert(name, amount, add_months(prev_month, 0, day), category, rec, day, False)

    for name, amount, (back, day), category in ONE_OFFS:
        due = add_months(this_month, -back, day)
        if due > today:  # never seed a "paid" expense in the future
            continue
        _insert(name, amount, due, category, "none", day, True, due)

    conn.executemany("INSERT INTO budgets (user_id, category, monthly_target) VALUES (?,?,?)",
                     [(user_id, c, t) for c, t in BUDGETS.items()])
    conn.execute("INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?, 'total_budget', ?)",
                 (user_id, str(TOTAL_BUDGET)))
