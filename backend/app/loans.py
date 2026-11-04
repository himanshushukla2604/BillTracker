"""Money you lent to someone: partial repayments and repeating reminders to ask for it back.

Lending is not spending, so loans never touch the budget or variance. A reminder is due when
`next_remind_on` has arrived and money is still owed; "I've asked them" moves it on by
`remind_every_days`. Reminders show in the dashboard banner and as a browser notification.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from . import auth, db
from .ledger import r as _r, today_or as _today

router = APIRouter(prefix="/api/loans", tags=["loans"])
Conn = Depends(db.get_conn)
Me = Depends(auth.current_user)


class LoanIn(BaseModel):
    person: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=1_000_000_000)
    lent_on: date
    due_date: Optional[date] = None  # when you expect it back
    note: Optional[str] = Field(None, max_length=200)
    remind_every_days: Optional[int] = Field(None, ge=1, le=365)  # None = no reminders
    first_reminder_on: Optional[date] = None  # default: the due date, else one interval after lending

    @field_validator("person")
    @classmethod
    def _person(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None

    @model_validator(mode="after")
    def _dates(self) -> "LoanIn":
        if self.due_date and self.due_date < self.lent_on:
            raise ValueError("the date you expect it back cannot be before you lent it")
        return self

    def first_reminder(self) -> Optional[date]:
        if not self.remind_every_days:
            return None
        return self.first_reminder_on or self.due_date or self.lent_on + timedelta(days=self.remind_every_days)


class RepaymentIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000_000)
    paid_on: Optional[date] = None  # default: today


class RepaymentOut(BaseModel):
    id: int
    amount: float
    paid_on: date


class LoanOut(BaseModel):
    id: int
    person: str
    amount: float
    lent_on: date
    due_date: Optional[date]
    note: Optional[str]
    repaid: float
    outstanding: float
    status: Literal["open", "repaid"]
    days_to_due: Optional[int]  # negative once the date has passed
    overdue: bool
    remind_every_days: Optional[int]
    next_remind_on: Optional[date]
    reminder_due: bool  # time to ask for the money back
    repayments: list[RepaymentOut]


def _get(conn: sqlite3.Connection, uid: int, loan_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM loans WHERE id=? AND user_id=?", (loan_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "Loan not found")
    return row


def _out(conn: sqlite3.Connection, row: sqlite3.Row, today: date) -> LoanOut:
    reps = [RepaymentOut(id=p["id"], amount=p["amount"], paid_on=date.fromisoformat(p["paid_on"]))
            for p in conn.execute("SELECT * FROM loan_repayments WHERE loan_id=? ORDER BY paid_on, id", (row["id"],))]
    repaid = _r(sum(p.amount for p in reps))
    outstanding = _r(max(row["amount"] - repaid, 0))
    is_open = outstanding > 0
    due = date.fromisoformat(row["due_date"]) if row["due_date"] else None
    nxt = date.fromisoformat(row["next_remind_on"]) if row["next_remind_on"] else None
    return LoanOut(
        id=row["id"], person=row["person"], amount=row["amount"], lent_on=date.fromisoformat(row["lent_on"]),
        due_date=due, note=row["note"], repaid=repaid, outstanding=outstanding,
        status="open" if is_open else "repaid",
        days_to_due=(due - today).days if due else None,
        overdue=bool(is_open and due and due < today),
        remind_every_days=row["remind_every_days"],
        next_remind_on=nxt if is_open else None,
        reminder_due=bool(is_open and row["remind_every_days"] and nxt and nxt <= today),
        repayments=reps,
    )


@router.get("", response_model=list[LoanOut])
def list_loans(today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    t = _today(today)
    loans = [_out(conn, r, t) for r in conn.execute("SELECT * FROM loans WHERE user_id=?", (uid,))]
    # Open loans that need a nudge first, then by when they are due; repaid ones last.
    loans.sort(key=lambda l: (l.status != "open", not l.reminder_due, l.due_date or date.max, l.id))
    return loans


@router.post("", response_model=LoanOut, status_code=201)
def create_loan(body: LoanIn, today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    first = body.first_reminder()
    cur = conn.execute(
        "INSERT INTO loans (user_id, person, amount, lent_on, due_date, note, remind_every_days, next_remind_on)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (uid, body.person, _r(body.amount), body.lent_on.isoformat(),
         body.due_date.isoformat() if body.due_date else None, body.note, body.remind_every_days,
         first.isoformat() if first else None),
    )
    conn.commit()
    return _out(conn, _get(conn, uid, cur.lastrowid), _today(today))


@router.put("/{loan_id}", response_model=LoanOut)
def update_loan(loan_id: int, body: LoanIn, today: Optional[date] = None,
                conn: sqlite3.Connection = Conn, uid: int = Me):
    row = _get(conn, uid, loan_id)
    repaid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM loan_repayments WHERE loan_id=?", (loan_id,)).fetchone()[0]
    if body.amount < repaid - 0.005:
        raise HTTPException(422, f"Already repaid {_r(repaid)}; the amount cannot be less than that")
    # Keep the current reminder date unless the schedule itself changed.
    same_schedule = row["remind_every_days"] == body.remind_every_days and row["next_remind_on"]
    if body.first_reminder_on or not same_schedule:
        nxt = body.first_reminder()
    else:
        nxt = date.fromisoformat(row["next_remind_on"])
    conn.execute(
        "UPDATE loans SET person=?, amount=?, lent_on=?, due_date=?, note=?, remind_every_days=?, next_remind_on=?"
        " WHERE id=?",
        (body.person, _r(body.amount), body.lent_on.isoformat(),
         body.due_date.isoformat() if body.due_date else None, body.note, body.remind_every_days,
         nxt.isoformat() if nxt else None, loan_id),
    )
    conn.commit()
    return _out(conn, _get(conn, uid, loan_id), _today(today))


@router.delete("/{loan_id}", status_code=204)
def delete_loan(loan_id: int, conn: sqlite3.Connection = Conn, uid: int = Me):
    _get(conn, uid, loan_id)
    conn.execute("DELETE FROM loans WHERE id=?", (loan_id,))
    conn.commit()
    return Response(status_code=204)


@router.post("/{loan_id}/repayments", response_model=LoanOut, status_code=201)
def add_repayment(loan_id: int, body: RepaymentIn, today: Optional[date] = None,
                  conn: sqlite3.Connection = Conn, uid: int = Me):
    t = _today(today)
    loan = _out(conn, _get(conn, uid, loan_id), t)
    if body.amount > loan.outstanding + 0.005:
        raise HTTPException(422, f"Only {loan.outstanding} is still owed")
    conn.execute("INSERT INTO loan_repayments (loan_id, amount, paid_on) VALUES (?,?,?)",
                 (loan_id, _r(body.amount), (body.paid_on or t).isoformat()))
    conn.commit()
    return _out(conn, _get(conn, uid, loan_id), t)


@router.delete("/{loan_id}/repayments/{repayment_id}", response_model=LoanOut)
def delete_repayment(loan_id: int, repayment_id: int, today: Optional[date] = None,
                     conn: sqlite3.Connection = Conn, uid: int = Me):
    _get(conn, uid, loan_id)
    cur = conn.execute("DELETE FROM loan_repayments WHERE id=? AND loan_id=?", (repayment_id, loan_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Repayment not found")
    return _out(conn, _get(conn, uid, loan_id), _today(today))


@router.post("/{loan_id}/reminded", response_model=LoanOut)
def mark_reminded(loan_id: int, today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    """You asked them: the next reminder comes one interval from today."""
    t = _today(today)
    row = _get(conn, uid, loan_id)
    if not row["remind_every_days"]:
        raise HTTPException(409, "This loan has no reminders set")
    conn.execute("UPDATE loans SET next_remind_on=? WHERE id=?",
                 ((t + timedelta(days=row["remind_every_days"])).isoformat(), loan_id))
    conn.commit()
    return _out(conn, _get(conn, uid, loan_id), t)
