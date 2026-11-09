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

from . import auth, backup, cards, db, loans
from .ledger import (
    ALERT_WINDOW_DAYS, chronological as _chronological, month_bounds as _month_bounds, projections as _projections,
    r as _r, to_out as _to_out, today_or as _today,
)
from .recurrence import next_due
from .schemas import (
    BudgetIn, BudgetOut, ExpenseIn, ExpenseOut, SettingsIn, SettingsOut,
    Summary, Variance, VarianceRow,
)

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


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
app.include_router(loans.router)
app.include_router(cards.router)

Conn = Depends(db.get_conn)
Me = Depends(auth.current_user)  # every data route is scoped to the logged-in user


@app.middleware("http")
async def daily_backup(request: Request, call_next):
    """Snapshot the database before the first change of each day (the server may run for weeks)."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
        backup.backup_if_due()
    return await call_next(request)


# ---------------------------------------------------------------- helpers

def _get_row(conn: sqlite3.Connection, uid: int, expense_id: int) -> sqlite3.Row:
    """Someone else's expense is reported as missing, not forbidden, so ids reveal nothing."""
    row = conn.execute("SELECT * FROM expenses WHERE id=? AND user_id=?", (expense_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "Expense not found")
    return row


def _card_charge(e: ExpenseOut) -> bool:
    """Charged to a credit card: settled through the card's bill, not paid on its own."""
    return e.payment_mode == "credit_card" and e.card_id is not None


CARD_CHARGE_SQL = "(payment_mode = 'credit_card' AND card_id IS NOT NULL)"


def _total_budget(conn: sqlite3.Connection, uid: int) -> float:
    row = conn.execute("SELECT value FROM settings WHERE user_id=? AND key='total_budget'", (uid,)).fetchone()
    return float(row["value"]) if row else 0.0


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
    """Stored bills, plus, when a month is given, projected recurring ones (`projected=false` to skip)
    and EMI instalments dated in it."""
    t = _today(today)
    cards.charge_due(conn, uid, t)
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
    if month:
        items += [e for e in cards.emi_items(conn, uid, start, end, t)
                  if (not status or e.paid == (status == "paid"))
                  and (not category or e.category.lower() == category.lower())]
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
    (including projected occurrences of recurring bills). Purchases charged to a card are left
    out; the card's bill stands for them."""
    t = _today(today)
    cards.charge_due(conn, uid, t)
    horizon = t + timedelta(days=days)
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? AND paid=0 AND due_date <= ? ORDER BY due_date, id",
        (uid, horizon.isoformat()),
    )
    items = [_to_out(r, t) for r in rows]
    if projected:
        items += _projections(conn, uid, t, horizon + timedelta(days=1), t)
    items = [e for e in items if not _card_charge(e)]
    items += [b for b in cards.bills_to_pay(conn, uid, t, horizon) if projected or not b.projected]
    return _chronological(items)


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(body: ExpenseIn, today: Optional[date] = None, conn: sqlite3.Connection = Conn,
                   uid: int = Me):
    cards.owned_card(conn, uid, body.card_id, body.payment_mode)
    cur = conn.execute(
        "INSERT INTO expenses (user_id, name, amount, reimbursed, reimbursed_note, due_date, category,"
        " recurring, anchor_day, payment_mode, card_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, body.name, _r(body.amount), _r(body.reimbursed), body.reimbursed_note,
         body.due_date.isoformat(), body.category, body.recurring, body.due_date.day,
         body.payment_mode, body.card_id),
    )
    conn.commit()
    return _to_out(_get_row(conn, uid, cur.lastrowid), _today(today))


@app.get("/api/expenses/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, today: Optional[date] = None, conn: sqlite3.Connection = Conn,
                uid: int = Me):
    return _to_out(_get_row(conn, uid, expense_id), _today(today))


@app.put("/api/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, body: ExpenseIn, today: Optional[date] = None,
                   conn: sqlite3.Connection = Conn, uid: int = Me):
    _get_row(conn, uid, expense_id)
    cards.owned_card(conn, uid, body.card_id, body.payment_mode)
    conn.execute(
        "UPDATE expenses SET name=?, amount=?, reimbursed=?, reimbursed_note=?, due_date=?, category=?,"
        " recurring=?, anchor_day=?, payment_mode=?, card_id=? WHERE id=?",
        (body.name, _r(body.amount), _r(body.reimbursed), body.reimbursed_note, body.due_date.isoformat(),
         body.category, body.recurring, body.due_date.day, body.payment_mode, body.card_id, expense_id),
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
                " generated_from, payment_mode, card_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uid, row["name"], row["amount"], nxt.isoformat(), row["category"],
                 row["recurring"], row["anchor_day"], expense_id, row["payment_mode"], row["card_id"]),
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
    for table in ("budgets", "expenses", "emis"):
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
    """Remaining budget = total budget minus your own spend: everything dated in the month (paid,
    not yet paid, and projected recurring bills) less what other people paid back to you.
    Bill totals and the overdue / due-soon amounts stay in full, since that is what you owe.
    EMI instalments dated in the month count as spending; card bills do not (the purchases did).

    The overdue / due-soon figures are global (not limited to the month) because
    they drive the alerts. They count card bills instead of the purchases charged to cards.
    """
    t = _today(today)
    cards.charge_due(conn, uid, t)
    month, start, end = _month_bounds(month, t)
    paid_total = unpaid_total = paid_back = unpaid_back = 0.0
    for r in conn.execute(
        "SELECT paid, COALESCE(SUM(amount),0) AS s, COALESCE(SUM(reimbursed),0) AS back FROM expenses"
        " WHERE user_id=? AND due_date >= ? AND due_date < ? GROUP BY paid",
        (uid, start.isoformat(), end.isoformat()),
    ):
        if r["paid"]:
            paid_total, paid_back = r["s"], r["back"]
        else:
            unpaid_total, unpaid_back = r["s"], r["back"]
    projected_total = sum(p.amount for p in _projections(conn, uid, start, end, t))
    unpaid_total += projected_total
    for e in cards.emi_items(conn, uid, start, end, t):
        if e.paid:
            paid_total += e.amount
        else:
            unpaid_total += e.amount
    scheduled = paid_total + unpaid_total
    reimbursed = paid_back + unpaid_back
    own = scheduled - reimbursed
    budget = _total_budget(conn, uid)

    od = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM expenses"
        f" WHERE user_id=? AND paid=0 AND due_date < ? AND NOT {CARD_CHARGE_SQL}",
        (uid, t.isoformat()),
    ).fetchone()
    soon_end = t + timedelta(days=ALERT_WINDOW_DAYS)
    ds = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM expenses"
        f" WHERE user_id=? AND paid=0 AND due_date BETWEEN ? AND ? AND NOT {CARD_CHARGE_SQL}",
        (uid, t.isoformat(), soon_end.isoformat()),
    ).fetchone()
    soon_projected = [p for p in _projections(conn, uid, t, soon_end + timedelta(days=1), t) if not _card_charge(p)]
    card_bills = cards.bills_to_pay(conn, uid, t, soon_end)
    soon_projected += [b for b in card_bills if b.days_left >= 0]
    card_overdue = [b for b in card_bills if b.days_left < 0]

    return Summary(
        month=month,
        total_budget=_r(budget),
        scheduled_total=_r(scheduled),
        paid_total=_r(paid_total),
        unpaid_total=_r(unpaid_total),
        projected_total=_r(projected_total),
        reimbursed_total=_r(reimbursed),
        own_spend=_r(own),
        remaining=_r(budget - own),
        remaining_after_paid=_r(budget - (paid_total - paid_back)),
        percent_committed=_r(own / budget * 100) if budget else 0.0,
        overdue_count=od["c"] + len(card_overdue),
        overdue_amount=_r(od["s"] + sum(b.amount for b in card_overdue)),
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
    """Target vs actual per category. variance = target - actual: positive means under target.
    Actual is your own share, so money someone paid back to you does not count as overspending.
    EMI instalments count in their EMI's category."""
    t = _today(today)
    cards.charge_due(conn, uid, t)
    month, start, end = _month_bounds(month, t)

    targets: dict[str, tuple[str, float]] = {}
    for r in conn.execute("SELECT category, monthly_target FROM budgets WHERE user_id=?", (uid,)):
        targets[r["category"].lower()] = (r["category"], r["monthly_target"])

    actuals: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT category, SUM(amount - reimbursed) AS actual, SUM(reimbursed) AS back,"
        " SUM(CASE WHEN paid=1 THEN amount - reimbursed ELSE 0 END) AS paid"
        " FROM expenses WHERE user_id=? AND due_date >= ? AND due_date < ? GROUP BY category",
        (uid, start.isoformat(), end.isoformat()),
    ):
        key = r["category"].lower()
        slot = actuals.setdefault(key, {"name": r["category"], "actual": 0.0, "paid": 0.0, "back": 0.0})
        slot["actual"] += r["actual"]
        slot["paid"] += r["paid"]
        slot["back"] += r["back"]
    for p in _projections(conn, uid, start, end, t):
        slot = actuals.setdefault(p.category.lower(),
                                  {"name": p.category, "actual": 0.0, "paid": 0.0, "back": 0.0})
        slot["actual"] += p.amount
    for e in cards.emi_items(conn, uid, start, end, t):
        slot = actuals.setdefault(e.category.lower(),
                                  {"name": e.category, "actual": 0.0, "paid": 0.0, "back": 0.0})
        slot["actual"] += e.amount
        if e.paid:
            slot["paid"] += e.amount

    rows: list[VarianceRow] = []
    for key in sorted(set(targets) | set(actuals)):
        name = targets[key][0] if key in targets else actuals[key]["name"]
        target = targets[key][1] if key in targets else None
        a = actuals.get(key, {"actual": 0.0, "paid": 0.0, "back": 0.0})
        actual = _r(a["actual"])
        var = _r(target - actual) if target is not None else None
        if target is None:
            status = "no_target"
        elif abs(var) < 0.005:
            status = "on"
        else:
            status = "under" if var > 0 else "over"
        rows.append(VarianceRow(category=name, target=target, actual=actual,
                                paid=_r(a["paid"]), reimbursed=_r(a["back"]), variance=var, status=status))
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
        "expenses": rows("SELECT id, name, amount, reimbursed, reimbursed_note, payment_mode, card_id, due_date, category, recurring, anchor_day, paid, paid_on,"
                         " generated_from FROM expenses WHERE user_id=? ORDER BY due_date, id"),
        "budgets": rows("SELECT category, monthly_target FROM budgets WHERE user_id=? ORDER BY category"),
        "cards": rows("SELECT id, name, kind, statement_day, due_day FROM cards WHERE user_id=? ORDER BY id"),
        "emis": rows("SELECT id, card_id, name, category, monthly_amount, first_date, months FROM emis"
                     " WHERE user_id=? ORDER BY id"),
        "card_payments": rows("SELECT card_id, statement_date, amount, paid_on FROM card_payments"
                              " WHERE user_id=? ORDER BY paid_on, id"),
        "loans": rows("SELECT id, person, amount, lent_on, due_date, note, remind_every_days, next_remind_on"
                      " FROM loans WHERE user_id=? ORDER BY id"),
        "loan_repayments": rows("SELECT r.loan_id, r.amount, r.paid_on FROM loan_repayments r"
                                " JOIN loans l ON l.id = r.loan_id WHERE l.user_id=? ORDER BY r.paid_on, r.id"),
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
