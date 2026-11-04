"""Shared bill maths: urgency, the API shape of a bill, and projected recurring occurrences."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from .recurrence import next_due
from .schemas import ExpenseOut

ALERT_WINDOW_DAYS = 3  # bills due within this many days are colour-coded
MAX_PROJECTED = 600  # safety cap on occurrences rolled forward per bill


def today_or(today: Optional[date]) -> date:
    """Clients pass their local date so 'due today' is right across time zones."""
    return today or date.today()


def month_bounds(month: Optional[str], today: date) -> tuple[str, date, date]:
    if month is None:
        month = today.strftime("%Y-%m")
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year + (mon == 12), (mon % 12) + 1, 1)
    return month, start, end


def urgency(paid: bool, days_left: int) -> str:
    if paid:
        return "paid"
    if days_left < 0:
        return "overdue"
    if days_left <= 1:
        return "urgent"  # today or tomorrow
    if days_left <= ALERT_WINDOW_DAYS:
        return "soon"  # 2-3 days out
    return "later"


def to_out(row: sqlite3.Row, today: date) -> ExpenseOut:
    due = date.fromisoformat(row["due_date"])
    days_left = (due - today).days
    paid = bool(row["paid"])
    return ExpenseOut(
        id=row["id"],
        name=row["name"],
        amount=row["amount"],
        reimbursed=row["reimbursed"],
        reimbursed_note=row["reimbursed_note"],
        due_date=due,
        category=row["category"],
        recurring=row["recurring"],
        paid=paid,
        paid_on=date.fromisoformat(row["paid_on"]) if row["paid_on"] else None,
        generated_from=row["generated_from"],
        payment_mode=row["payment_mode"],
        card_id=row["card_id"],
        days_left=days_left,
        urgency=urgency(paid, days_left),
    )


def projections(conn: sqlite3.Connection, uid: int, start: date, end: date, today: date,
                 category: Optional[str] = None) -> list[ExpenseOut]:
    """Future occurrences of recurring bills in [start, end) that are not stored yet.

    The next row of a series is only created when the current one is paid, so every
    unpaid recurring bill is the end of its series: roll it forward to fill the window.
    Only dates from today on are projected; the past is whatever was recorded.
    """
    start = max(start, today)
    sql, args = "SELECT * FROM expenses WHERE user_id=? AND paid=0 AND recurring != 'none'", [uid]
    if category:
        sql += " AND category = ? COLLATE NOCASE"
        args.append(category)
    out: list[ExpenseOut] = []
    for row in conn.execute(sql, args):
        d = date.fromisoformat(row["due_date"])
        for _ in range(MAX_PROJECTED):
            d = next_due(d, row["recurring"], row["anchor_day"])
            if d is None or d >= end:
                break
            if d >= start:
                days_left = (d - today).days
                out.append(ExpenseOut(
                    id=None, name=row["name"], amount=row["amount"], due_date=d,
                    category=row["category"], recurring=row["recurring"], paid=False,
                    days_left=days_left, urgency=urgency(False, days_left),
                    projected=True, projected_from=row["id"],
                    payment_mode=row["payment_mode"], card_id=row["card_id"],
                ))
    return out


def chronological(items: list[ExpenseOut]) -> list[ExpenseOut]:
    return sorted(items, key=lambda e: (e.due_date, e.projected, e.id or e.projected_from or e.emi_id or e.card_id or 0))


def r(x: float) -> float:
    return round(x + 0.0, 2)
