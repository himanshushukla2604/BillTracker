from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, backup, db
from .recurrence import next_due
from .schemas import (
    BudgetIn, BudgetOut, ExpenseIn, ExpenseOut, SettingsIn, SettingsOut,
    Summary, Variance, VarianceRow,
)

ALERT_WINDOW_DAYS = 3  # bills due within this many days are colour-coded
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
MAX_PROJECTED = 600  # safety cap on occurrences rolled forward per bill


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    backup.backup_if_due()
    yield


app = FastAPI(title="Personal Finance & Bill Tracker", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5180", "http://127.0.0.1:5180"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)

Conn = Depends(db.get_conn)
Me = Depends(auth.current_user)  # every data route is scoped to the logged-in user


@app.middleware("http")
async def daily_backup(request: Request, call_next):
    """Snapshot the database before the first change of each day (the server may run for weeks)."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
        backup.backup_if_due()
    return await call_next(request)


# ---------------------------------------------------------------- helpers

def _today(today: Optional[date]) -> date:
    """Clients pass their local date so 'due today' is right across time zones."""
    return today or date.today()


def _month_bounds(month: Optional[str], today: date) -> tuple[str, date, date]:
    if month is None:
        month = today.strftime("%Y-%m")
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year + (mon == 12), (mon % 12) + 1, 1)
    return month, start, end


def _urgency(paid: bool, days_left: int) -> str:
    if paid:
        return "paid"
    if days_left < 0:
        return "overdue"
    if days_left <= 1:
        return "urgent"  # today or tomorrow
    if days_left <= ALERT_WINDOW_DAYS:
        return "soon"  # 2-3 days out
    return "later"


def _to_out(row: sqlite3.Row, today: date) -> ExpenseOut:
    due = date.fromisoformat(row["due_date"])
    days_left = (due - today).days
    paid = bool(row["paid"])
    return ExpenseOut(
        id=row["id"],
        name=row["name"],
        amount=row["amount"],
        due_date=due,
        category=row["category"],
        recurring=row["recurring"],
        paid=paid,
        paid_on=date.fromisoformat(row["paid_on"]) if row["paid_on"] else None,
        generated_from=row["generated_from"],
        days_left=days_left,
        urgency=_urgency(paid, days_left),
    )


def _projections(conn: sqlite3.Connection, uid: int, start: date, end: date, today: date,
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
                    days_left=days_left, urgency=_urgency(False, days_left),
                    projected=True, projected_from=row["id"],
                ))
    return out


def _chronological(items: list[ExpenseOut]) -> list[ExpenseOut]:
    return sorted(items, key=lambda e: (e.due_date, e.projected, e.id or e.projected_from))


def _get_row(conn: sqlite3.Connection, uid: int, expense_id: int) -> sqlite3.Row:
    """Someone else's expense is reported as missing, not forbidden, so ids reveal nothing."""
    row = conn.execute("SELECT * FROM expenses WHERE id=? AND user_id=?", (expense_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "Expense not found")
    return row


def _total_budget(conn: sqlite3.Connection, uid: int) -> float:
    row = conn.execute("SELECT value FROM settings WHERE user_id=? AND key='total_budget'", (uid,)).fetchone()
    return float(row["value"]) if row else 0.0


def _r(x: float) -> float:
    return round(x + 0.0, 2)


# --------------------------------------------------------------- expenses

@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN),
    status: Optional[str] = Query(None, pattern="^(paid|unpaid)$"),
    category: Optional[str] = None,
    projected: bool = True,
    today: Optional[date] = None,
    conn: sqlite3.Connection = Conn,
    uid: int = Me,
):
    """Stored bills, plus projected recurring ones when a month is given (`projected=false` to skip)."""
    t = _today(today)
    sql, args = "SELECT * FROM expenses WHERE user_id=?", [uid]
    if month:
        _, start, end = _month_bounds(month, t)
        sql += " AND due_date >= ? AND due_date < ?"
        args += [start.isoformat(), end.isoformat()]
    if status:
        sql += " AND paid = ?"
        args.append(1 if status == "paid" else 0)
    if category:
        sql += " AND category = ? COLLATE NOCASE"
        args.append(category)
    sql += " ORDER BY due_date, id"
    items = [_to_out(r, t) for r in conn.execute(sql, args)]
    if month and projected and status != "paid":
        items += _projections(conn, uid, start, end, t, category)
    return _chronological(items)


@app.get("/api/upcoming", response_model=list[ExpenseOut])
def upcoming(
    days: int = Query(60, ge=1, le=365),
    projected: bool = True,
    today: Optional[date] = None,
    conn: sqlite3.Connection = Conn,
    uid: int = Me,
):
    """Unpaid bills in chronological order: everything overdue, then the next `days` days
    (including projected occurrences of recurring bills)."""
    t = _today(today)
    horizon = t + timedelta(days=days)
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? AND paid=0 AND due_date <= ? ORDER BY due_date, id",
        (uid, horizon.isoformat()),
    )
    items = [_to_out(r, t) for r in rows]
    if projected:
        items += _projections(conn, uid, t, horizon + timedelta(days=1), t)
    return _chronological(items)


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(body: ExpenseIn, today: Optional[date] = None, conn: sqlite3.Connection = Conn,
                   uid: int = Me):
    cur = conn.execute(
        "INSERT INTO expenses (user_id, name, amount, due_date, category, recurring, anchor_day)"
        " VALUES (?,?,?,?,?,?,?)",
        (uid, body.name, _r(body.amount), body.due_date.isoformat(), body.category,
         body.recurring, body.due_date.day),
    )
    conn.commit()
    return _to_out(_get_row(conn, uid, cur.lastrowid), _today(today))


@app.put("/api/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, body: ExpenseIn, today: Optional[date] = None,
                   conn: sqlite3.Connection = Conn, uid: int = Me):
    _get_row(conn, uid, expense_id)
    conn.execute(
        "UPDATE expenses SET name=?, amount=?, due_date=?, category=?, recurring=?, anchor_day=? WHERE id=?",
        (body.name, _r(body.amount), body.due_date.isoformat(), body.category,
         body.recurring, body.due_date.day, expense_id),
    )
    conn.commit()
    return _to_out(_get_row(conn, uid, expense_id), _today(today))


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, conn: sqlite3.Connection = Conn, uid: int = Me):
    _get_row(conn, uid, expense_id)
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    return Response(status_code=204)


@app.post("/api/expenses/{expense_id}/pay", response_model=ExpenseOut)
def mark_paid(expense_id: int, today: Optional[date] = None, conn: sqlite3.Connection = Conn,
              uid: int = Me):
    """Mark paid. Recurring bills automatically roll over to their next due date."""
    t = _today(today)
    row = _get_row(conn, uid, expense_id)
    if not row["paid"]:
        conn.execute("UPDATE expenses SET paid=1, paid_on=? WHERE id=?", (t.isoformat(), expense_id))
        nxt = next_due(date.fromisoformat(row["due_date"]), row["recurring"], row["anchor_day"])
        has_child = conn.execute(
            "SELECT 1 FROM expenses WHERE generated_from=?", (expense_id,)
        ).fetchone()
        if nxt and not has_child:
            conn.execute(
                "INSERT INTO expenses (user_id, name, amount, due_date, category, recurring, anchor_day,"
                " generated_from) VALUES (?,?,?,?,?,?,?,?)",
                (uid, row["name"], row["amount"], nxt.isoformat(), row["category"],
                 row["recurring"], row["anchor_day"], expense_id),
            )
        conn.commit()
    return _to_out(_get_row(conn, uid, expense_id), t)


@app.post("/api/expenses/{expense_id}/unpay", response_model=ExpenseOut)
def mark_unpaid(expense_id: int, today: Optional[date] = None, conn: sqlite3.Connection = Conn,
                uid: int = Me):
    """Undo a payment, and remove the auto-created next occurrence if it is still unpaid."""
    row = _get_row(conn, uid, expense_id)
    if row["paid"]:
        child = conn.execute("SELECT * FROM expenses WHERE generated_from=?", (expense_id,)).fetchone()
        if child is not None:
            if child["paid"]:
                raise HTTPException(409, "The next occurrence is already paid; undo that one first.")
            conn.execute("DELETE FROM expenses WHERE id=?", (child["id"],))
        conn.execute("UPDATE expenses SET paid=0, paid_on=NULL WHERE id=?", (expense_id,))
        conn.commit()
    return _to_out(_get_row(conn, uid, expense_id), _today(today))


# -------------------------------------------------- settings / budgets

@app.get("/api/settings", response_model=SettingsOut)
def get_settings(conn: sqlite3.Connection = Conn, uid: int = Me):
    return SettingsOut(total_budget=_total_budget(conn, uid))


@app.put("/api/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, conn: sqlite3.Connection = Conn, uid: int = Me):
    conn.execute("INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?, 'total_budget', ?)",
                 (uid, str(_r(body.total_budget))))
    conn.commit()
    return SettingsOut(total_budget=_total_budget(conn, uid))


@app.get("/api/budgets", response_model=list[BudgetOut])
def list_budgets(conn: sqlite3.Connection = Conn, uid: int = Me):
    rows = conn.execute("SELECT category, monthly_target FROM budgets WHERE user_id=? ORDER BY category COLLATE NOCASE",
                        (uid,))
    return [BudgetOut(**dict(r)) for r in rows]


@app.put("/api/budgets/{category}", response_model=BudgetOut)
def put_budget(category: str, body: BudgetIn, conn: sqlite3.Connection = Conn, uid: int = Me):
    category = category.strip()
    if not category:
        raise HTTPException(422, "Category must not be blank")
    existing = conn.execute(
        "SELECT category FROM budgets WHERE user_id=? AND category = ? COLLATE NOCASE", (uid, category)
    ).fetchone()
    if existing:
        category = existing["category"]
        conn.execute("UPDATE budgets SET monthly_target=? WHERE user_id=? AND category=?",
                     (_r(body.monthly_target), uid, category))
    else:
        conn.execute("INSERT INTO budgets (user_id, category, monthly_target) VALUES (?,?,?)",
                     (uid, category, _r(body.monthly_target)))
    conn.commit()
    return BudgetOut(category=category, monthly_target=_r(body.monthly_target))


@app.delete("/api/budgets/{category}", status_code=204)
def delete_budget(category: str, conn: sqlite3.Connection = Conn, uid: int = Me):
    cur = conn.execute("DELETE FROM budgets WHERE user_id=? AND category = ? COLLATE NOCASE", (uid, category))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "No target for that category")
    return Response(status_code=204)


@app.get("/api/categories", response_model=list[str])
def categories(conn: sqlite3.Connection = Conn, uid: int = Me):
    names: dict[str, str] = {}
    for table in ("budgets", "expenses"):
        for r in conn.execute(f"SELECT DISTINCT category FROM {table} WHERE user_id=?", (uid,)):
            names.setdefault(r["category"].lower(), r["category"])
    return sorted(names.values(), key=str.lower)


# --------------------------------------------------- summary / variance

@app.get("/api/summary", response_model=Summary)
def summary(
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN),
    today: Optional[date] = None,
    conn: sqlite3.Connection = Conn,
    uid: int = Me,
):
    """Remaining budget = total budget minus everything dated in the month (paid, not yet paid,
    and projected recurring bills).

    The overdue / due-soon figures are global (not limited to the month) because
    they drive the alerts.
    """
    t = _today(today)
    month, start, end = _month_bounds(month, t)
    paid_total = unpaid_total = 0.0
    for r in conn.execute(
        "SELECT paid, COALESCE(SUM(amount),0) AS s FROM expenses"
        " WHERE user_id=? AND due_date >= ? AND due_date < ? GROUP BY paid",
        (uid, start.isoformat(), end.isoformat()),
    ):
        if r["paid"]:
            paid_total = r["s"]
        else:
            unpaid_total = r["s"]
    projected_total = sum(p.amount for p in _projections(conn, uid, start, end, t))
    unpaid_total += projected_total
    scheduled = paid_total + unpaid_total
    budget = _total_budget(conn, uid)

    od = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM expenses WHERE user_id=? AND paid=0 AND due_date < ?",
        (uid, t.isoformat()),
    ).fetchone()
    soon_end = t + timedelta(days=ALERT_WINDOW_DAYS)
    ds = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM expenses"
        " WHERE user_id=? AND paid=0 AND due_date BETWEEN ? AND ?",
        (uid, t.isoformat(), soon_end.isoformat()),
    ).fetchone()
    soon_projected = _projections(conn, uid, t, soon_end + timedelta(days=1), t)

    return Summary(
        month=month,
        total_budget=_r(budget),
        scheduled_total=_r(scheduled),
        paid_total=_r(paid_total),
        unpaid_total=_r(unpaid_total),
        projected_total=_r(projected_total),
        remaining=_r(budget - scheduled),
        remaining_after_paid=_r(budget - paid_total),
        percent_committed=_r(scheduled / budget * 100) if budget else 0.0,
        overdue_count=od["c"],
        overdue_amount=_r(od["s"]),
        due_soon_count=ds["c"] + len(soon_projected),
        due_soon_amount=_r(ds["s"] + sum(p.amount for p in soon_projected)),
    )


@app.get("/api/variance", response_model=Variance)
def variance(
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN),
    today: Optional[date] = None,
    conn: sqlite3.Connection = Conn,
    uid: int = Me,
):
    """Target vs actual per category. variance = target - actual: positive means under target."""
    t = _today(today)
    month, start, end = _month_bounds(month, t)

    targets: dict[str, tuple[str, float]] = {}
    for r in conn.execute("SELECT category, monthly_target FROM budgets WHERE user_id=?", (uid,)):
        targets[r["category"].lower()] = (r["category"], r["monthly_target"])

    actuals: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT category, SUM(amount) AS actual, SUM(CASE WHEN paid=1 THEN amount ELSE 0 END) AS paid"
        " FROM expenses WHERE user_id=? AND due_date >= ? AND due_date < ? GROUP BY category",
        (uid, start.isoformat(), end.isoformat()),
    ):
        key = r["category"].lower()
        slot = actuals.setdefault(key, {"name": r["category"], "actual": 0.0, "paid": 0.0})
        slot["actual"] += r["actual"]
        slot["paid"] += r["paid"]
    for p in _projections(conn, uid, start, end, t):
        slot = actuals.setdefault(p.category.lower(), {"name": p.category, "actual": 0.0, "paid": 0.0})
        slot["actual"] += p.amount

    rows: list[VarianceRow] = []
    for key in sorted(set(targets) | set(actuals)):
        name = targets[key][0] if key in targets else actuals[key]["name"]
        target = targets[key][1] if key in targets else None
        a = actuals.get(key, {"actual": 0.0, "paid": 0.0})
        actual = _r(a["actual"])
        var = _r(target - actual) if target is not None else None
        if target is None:
            status = "no_target"
        elif abs(var) < 0.005:
            status = "on"
        else:
            status = "under" if var > 0 else "over"
        rows.append(VarianceRow(category=name, target=target, actual=actual,
                                paid=_r(a["paid"]), variance=var, status=status))
    rows.sort(key=lambda x: (-x.actual, x.category.lower()))

    total_target = _r(sum(r.target for r in rows if r.target is not None))
    total_actual = _r(sum(r.actual for r in rows))
    return Variance(
        month=month,
        rows=rows,
        total_target=total_target,
        total_actual=total_actual,
        total_variance=_r(total_target - total_actual),
        unbudgeted_actual=_r(sum(r.actual for r in rows if r.target is None)),
    )


@app.get("/api/export")
def export(conn: sqlite3.Connection = Conn, uid: int = Me):
    """Everything in your account as a JSON download. (Server-wide backups are in backup.py.)"""
    def rows(sql: str) -> list[dict]:
        return [dict(r) for r in conn.execute(sql, (uid,))]

    data = {
        "exported_on": date.today().isoformat(),
        "expenses": rows("SELECT id, name, amount, due_date, category, recurring, anchor_day, paid, paid_on,"
                         " generated_from FROM expenses WHERE user_id=? ORDER BY due_date, id"),
        "budgets": rows("SELECT category, monthly_target FROM budgets WHERE user_id=? ORDER BY category"),
        "settings": {r["key"]: r["value"] for r in rows("SELECT key, value FROM settings WHERE user_id=?")},
    }
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="bill-tracker-{date.today().isoformat()}.json"'})


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the built React app (npm run build) from the same origin in production.
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
