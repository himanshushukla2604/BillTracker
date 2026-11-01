"""Date arithmetic for recurring bills."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

RECURRENCE_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def add_months(d: date, months: int, anchor_day: int | None = None) -> date:
    """Add whole months, clamping to the month's last day.

    `anchor_day` is the day-of-month the bill was originally set on, so a bill
    anchored on the 31st goes Jan 31 -> Feb 28 -> Mar 31 (not Mar 28).
    """
    anchor = anchor_day or d.day
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor, last))


def next_due(d: date, recurring: str, anchor_day: int | None = None) -> date | None:
    """Return the next due date, or None for one-off bills."""
    if recurring == "weekly":
        return d + timedelta(days=7)
    months = RECURRENCE_MONTHS.get(recurring)
    if months is None:
        return None
    return add_months(d, months, anchor_day)
