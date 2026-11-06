"""Cards. Credit cards get statements built from what you charged to them, plus EMI instalments;
debit cards are just named so you can record which one paid (money leaves the bank straight away).

A purchase paid by card counts as spending (in its own category) on its date, so the card's
bill is not spending again; it is money you owe the card. Purchases up to and including the
statement day form one statement, payable on the due day. EMIs add a fixed instalment on the
same day each month for `months` months, and each instalment is spending in the EMI's category.

Card charges are charged automatically once their date arrives (`charge_due`), so a recurring
subscription on a card keeps rolling onto each statement without being ticked off by hand.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from . import auth, db
from .ledger import projections, r as _r, today_or as _today, urgency
from .recurrence import add_months, next_due
from .schemas import ExpenseOut

router = APIRouter(prefix="/api", tags=["cards"])
Conn = Depends(db.get_conn)
Me = Depends(auth.current_user)

CARD_BILL_CATEGORY = "Credit card bill"
HORIZON_DAYS = 400  # how far ahead statements and EMIs are worked out


# ------------------------------------------------------------------ cycle maths

def statement_for(d: date, statement_day: int) -> date:
    """The statement a charge on `d` lands on: this month's statement day, or next month's."""
    this = add_months(date(d.year, d.month, 1), 0, statement_day)
    return this if d <= this else add_months(date(d.year, d.month, 1), 1, statement_day)


def due_for(statement: date, statement_day: int, due_day: int) -> date:
    """Payment due date for a statement: later the same month, or in the next month."""
    return add_months(statement, 0 if due_day > statement_day else 1, due_day)


def emi_dates(first: date, months: int) -> list[date]:
    return [add_months(first, k, first.day) for k in range(months)]


# ------------------------------------------------------------------ auto-charge

def charge_due(conn: sqlite3.Connection, uid: int, today: date) -> None:
    """Card charges whose date has arrived are charged (marked paid on that date); recurring ones
    roll to their next occurrence, which is charged too if its date has also passed."""
    while True:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id=? AND paid=0 AND card_id IS NOT NULL"
            " AND payment_mode='credit_card' AND due_date <= ?", (uid, today.isoformat()),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            conn.execute("UPDATE expenses SET paid=1, paid_on=due_date WHERE id=?", (row["id"],))
            nxt = next_due(date.fromisoformat(row["due_date"]), row["recurring"], row["anchor_day"])
            has_child = conn.execute("SELECT 1 FROM expenses WHERE generated_from=?", (row["id"],)).fetchone()
            if nxt and not has_child:
                conn.execute(
                    "INSERT INTO expenses (user_id, name, amount, due_date, category, recurring, anchor_day,"
                    " generated_from, payment_mode, card_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (uid, row["name"], row["amount"], nxt.isoformat(), row["category"], row["recurring"],
                     row["anchor_day"], row["id"], row["payment_mode"], row["card_id"]),
                )
    conn.commit()


# ------------------------------------------------------------------ statements

@dataclass
class Statement:
    statement_date: date
    due_date: date
    purchases: float = 0.0
    emis: float = 0.0
    paid: float = 0.0
    charged_so_far: float = 0.0  # part dated today or earlier
    items: list[tuple[date, str, float]] = field(default_factory=list)

    @property
    def total(self) -> float:
        return _r(self.purchases + self.emis)

    @property
    def balance(self) -> float:
        return _r(max(self.total - self.paid, 0))


def _card(conn: sqlite3.Connection, uid: int, card_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cards WHERE id=? AND user_id=?", (card_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "Card not found")
    return row


def _credit_card(conn: sqlite3.Connection, uid: int, card_id: int) -> sqlite3.Row:
    row = _card(conn, uid, card_id)
    if row["kind"] != "credit":
        raise HTTPException(409, "Debit cards have no bill or EMIs")
    return row


def statements(conn: sqlite3.Connection, uid: int, card: sqlite3.Row, today: date) -> list[Statement]:
    """Every statement with something on it, oldest first, up to HORIZON_DAYS ahead."""
    s_day, d_day = card["statement_day"], card["due_day"]
    horizon = today + timedelta(days=HORIZON_DAYS)
    by_date: dict[date, Statement] = {}

    def add(d: date, label: str, amount: float, emi: bool) -> None:
        sd = statement_for(d, s_day)
        st = by_date.setdefault(sd, Statement(sd, due_for(sd, s_day, d_day)))
        if emi:
            st.emis += amount
        else:
            st.purchases += amount
        if d <= today:
            st.charged_so_far += amount
        st.items.append((d, label, amount))

    for row in conn.execute("SELECT name, amount, due_date FROM expenses WHERE user_id=? AND card_id=?"
                            " AND payment_mode='credit_card' AND due_date <= ?",
                            (uid, card["id"], horizon.isoformat())):
        add(date.fromisoformat(row["due_date"]), row["name"], row["amount"], emi=False)
    for p in projections(conn, uid, today, horizon, today):
        if p.card_id == card["id"] and p.payment_mode == "credit_card":
            add(p.due_date, p.name, p.amount, emi=False)
    for emi in conn.execute("SELECT * FROM emis WHERE card_id=? AND user_id=?", (card["id"], uid)):
        dates = emi_dates(date.fromisoformat(emi["first_date"]), emi["months"])
        for k, d in enumerate(dates, 1):
            if d <= horizon:
                add(d, f"{emi['name']} EMI {k}/{emi['months']}", emi["monthly_amount"], emi=True)

    for p in conn.execute("SELECT statement_date, SUM(amount) s FROM card_payments WHERE card_id=? AND user_id=?"
                          " GROUP BY statement_date", (card["id"], uid)):
        sd = date.fromisoformat(p["statement_date"])
        st = by_date.setdefault(sd, Statement(sd, due_for(sd, s_day, d_day)))
        st.paid += p["s"]
    return [by_date[k] for k in sorted(by_date)]


def bills_to_pay(conn: sqlite3.Connection, uid: int, today: date, until: date) -> list[ExpenseOut]:
    """Card bills as timeline items: closed statements still unpaid (payable), and the statement
    currently building up (an estimate, so `projected`), when due by `until`."""
    out: list[ExpenseOut] = []
    for card in conn.execute("SELECT * FROM cards WHERE user_id=? AND kind='credit'", (uid,)):
        for st in statements(conn, uid, card, today):
            closed = st.statement_date < today
            if st.due_date > until or st.balance <= 0:
                continue
            if not closed and st.statement_date != statement_for(today, card["statement_day"]):
                continue  # only the current cycle is worth estimating
            days_left = (st.due_date - today).days
            out.append(ExpenseOut(
                id=None, kind="card_bill", name=f"{card['name']} bill", amount=st.balance, due_date=st.due_date,
                category=CARD_BILL_CATEGORY, recurring="none", paid=False, days_left=days_left,
                urgency=urgency(False, days_left), projected=not closed, payment_mode=None,
                card_id=card["id"], statement_date=st.statement_date,
            ))
    return out


def emi_items(conn: sqlite3.Connection, uid: int, start: date, end: date, today: date) -> list[ExpenseOut]:
    """EMI instalments dated in [start, end) as read-only ledger rows (they are spending)."""
    out: list[ExpenseOut] = []
    for emi in conn.execute("SELECT e.*, c.name AS card_name FROM emis e JOIN cards c ON c.id=e.card_id"
                            " WHERE e.user_id=?", (uid,)):
        for k, d in enumerate(emi_dates(date.fromisoformat(emi["first_date"]), emi["months"]), 1):
            if start <= d < end:
                charged = d <= today
                days_left = (d - today).days
                out.append(ExpenseOut(
                    id=None, kind="emi", emi_id=emi["id"], name=f"{emi['name']} EMI {k}/{emi['months']}",
                    amount=emi["monthly_amount"], due_date=d, category=emi["category"], recurring="monthly",
                    paid=charged, paid_on=d if charged else None, days_left=days_left,
                    urgency=urgency(charged, days_left), payment_mode="credit_card", card_id=emi["card_id"],
                ))
    return out


# ------------------------------------------------------------------ API models

CardKind = Literal["credit", "debit"]


class CardIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    kind: CardKind = "credit"
    statement_day: Optional[int] = Field(None, ge=1, le=31)  # credit cards only
    due_day: Optional[int] = Field(None, ge=1, le=31)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def _days(self) -> "CardIn":
        if self.kind == "credit" and (self.statement_day is None or self.due_day is None):
            raise ValueError("a credit card needs its statement day and due day")
        if self.kind == "debit":
            self.statement_day = self.due_day = None
        return self

    def days(self) -> tuple[int, int]:
        """Stored values (the columns are NOT NULL; debit cards never use them)."""
        return (self.statement_day or 1, self.due_day or 1)


class EmiIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field("EMI", min_length=1, max_length=60)
    monthly_amount: float = Field(gt=0, le=1_000_000_000)
    first_date: date
    months: int = Field(ge=1, le=360)

    @field_validator("name", "category")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class EmiOut(BaseModel):
    id: int
    card_id: int
    name: str
    category: str
    monthly_amount: float
    first_date: date
    last_date: date
    months: int
    months_done: int  # instalments dated today or earlier
    months_left: int
    remaining: float  # instalments still to come


class StatementItem(BaseModel):
    date: date
    name: str
    amount: float


class StatementOut(BaseModel):
    statement_date: date
    due_date: date
    total: float
    paid: float
    balance: float
    overdue: bool
    items: list[StatementItem]  # purchases and EMI instalments on this bill, by date


class CardOut(BaseModel):
    id: int
    name: str
    kind: CardKind
    statement_day: Optional[int]  # credit cards only
    due_day: Optional[int]
    due_now: float  # closed statements not yet paid
    unpaid_statements: list[StatementOut]
    current_statement: Optional[StatementOut]  # the cycle building up now (estimate)
    charged_this_cycle: float  # already charged in the current cycle
    emi_remaining: float  # EMI instalments still to come
    total_owed: float  # due_now + charged_this_cycle + emi_remaining
    emis: list[EmiOut]


class PayIn(BaseModel):
    statement_date: date
    amount: Optional[float] = Field(None, gt=0)  # default: the whole balance


class UnpayIn(BaseModel):
    statement_date: date


def _emi_out(emi: sqlite3.Row, today: date) -> EmiOut:
    dates = emi_dates(date.fromisoformat(emi["first_date"]), emi["months"])
    done = sum(1 for d in dates if d <= today)
    return EmiOut(
        id=emi["id"], card_id=emi["card_id"], name=emi["name"], category=emi["category"],
        monthly_amount=emi["monthly_amount"], first_date=dates[0], last_date=dates[-1], months=emi["months"],
        months_done=done, months_left=emi["months"] - done,
        remaining=_r((emi["months"] - done) * emi["monthly_amount"]),
    )


def card_out(conn: sqlite3.Connection, uid: int, card: sqlite3.Row, today: date) -> CardOut:
    if card["kind"] == "debit":
        return CardOut(id=card["id"], name=card["name"], kind="debit", statement_day=None, due_day=None,
                       due_now=0, unpaid_statements=[], current_statement=None, charged_this_cycle=0,
                       emi_remaining=0, total_owed=0, emis=[])
    sts = statements(conn, uid, card, today)
    current_sd = statement_for(today, card["statement_day"])
    unpaid = [st for st in sts if st.statement_date < today and st.balance > 0]
    current = next((st for st in sts if st.statement_date == current_sd), None)
    emis = [_emi_out(e, today) for e in conn.execute(
        "SELECT * FROM emis WHERE card_id=? AND user_id=? ORDER BY first_date, id", (card["id"], uid))]

    def st_out(st: Statement) -> StatementOut:
        return StatementOut(statement_date=st.statement_date, due_date=st.due_date, total=st.total,
                            paid=_r(st.paid), balance=st.balance, overdue=st.balance > 0 and st.due_date < today,
                            items=[StatementItem(date=d, name=n, amount=a) for d, n, a in sorted(st.items)])

    due_now = _r(sum(st.balance for st in unpaid))
    charged = _r(max((current.charged_so_far - current.paid) if current else 0, 0))
    emi_left = _r(sum(e.remaining for e in emis))
    return CardOut(
        id=card["id"], name=card["name"], kind="credit", statement_day=card["statement_day"],
        due_day=card["due_day"], due_now=due_now, unpaid_statements=[st_out(st) for st in unpaid],
        current_statement=st_out(current) if current else None,
        charged_this_cycle=charged, emi_remaining=emi_left, total_owed=_r(due_now + charged + emi_left),
        emis=emis,
    )


# ------------------------------------------------------------------ routes

@router.get("/cards", response_model=list[CardOut])
def list_cards(today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    t = _today(today)
    charge_due(conn, uid, t)
    return [card_out(conn, uid, c, t) for c in conn.execute(
        "SELECT * FROM cards WHERE user_id=? ORDER BY kind, name COLLATE NOCASE", (uid,))]


@router.post("/cards", response_model=CardOut, status_code=201)
def create_card(body: CardIn, today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    cur = conn.execute("INSERT INTO cards (user_id, name, kind, statement_day, due_day) VALUES (?,?,?,?,?)",
                       (uid, body.name, body.kind, *body.days()))
    conn.commit()
    return card_out(conn, uid, _card(conn, uid, cur.lastrowid), _today(today))


@router.put("/cards/{card_id}", response_model=CardOut)
def update_card(card_id: int, body: CardIn, today: Optional[date] = None,
                conn: sqlite3.Connection = Conn, uid: int = Me):
    if _card(conn, uid, card_id)["kind"] != body.kind:
        raise HTTPException(422, "A card's type cannot be changed; add it again as the other type")
    conn.execute("UPDATE cards SET name=?, statement_day=?, due_day=? WHERE id=?",
                 (body.name, *body.days(), card_id))
    conn.commit()
    return card_out(conn, uid, _card(conn, uid, card_id), _today(today))


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, conn: sqlite3.Connection = Conn, uid: int = Me):
    """Removes the card, its EMIs and payments. Purchases made with it stay, without a card."""
    _card(conn, uid, card_id)
    conn.execute("UPDATE expenses SET card_id=NULL WHERE card_id=?", (card_id,))
    conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
    conn.commit()
    return Response(status_code=204)


@router.post("/cards/{card_id}/pay", response_model=CardOut)
def pay_statement(card_id: int, body: PayIn, today: Optional[date] = None,
                  conn: sqlite3.Connection = Conn, uid: int = Me):
    t = _today(today)
    card = _credit_card(conn, uid, card_id)
    st = next((s for s in statements(conn, uid, card, t) if s.statement_date == body.statement_date), None)
    if st is None or st.balance <= 0:
        raise HTTPException(409, "Nothing left to pay on that statement")
    amount = body.amount or st.balance
    if amount > st.balance + 0.005:
        raise HTTPException(422, f"Only {st.balance} is due on that statement")
    conn.execute("INSERT INTO card_payments (user_id, card_id, statement_date, amount, paid_on) VALUES (?,?,?,?,?)",
                 (uid, card_id, body.statement_date.isoformat(), _r(amount), t.isoformat()))
    conn.commit()
    return card_out(conn, uid, card, t)


@router.post("/cards/{card_id}/unpay", response_model=CardOut)
def unpay_statement(card_id: int, body: UnpayIn, today: Optional[date] = None,
                    conn: sqlite3.Connection = Conn, uid: int = Me):
    card = _credit_card(conn, uid, card_id)
    conn.execute("DELETE FROM card_payments WHERE card_id=? AND user_id=? AND statement_date=?",
                 (card_id, uid, body.statement_date.isoformat()))
    conn.commit()
    return card_out(conn, uid, card, _today(today))


@router.post("/cards/{card_id}/emis", response_model=EmiOut, status_code=201)
def create_emi(card_id: int, body: EmiIn, today: Optional[date] = None,
               conn: sqlite3.Connection = Conn, uid: int = Me):
    _credit_card(conn, uid, card_id)
    cur = conn.execute(
        "INSERT INTO emis (user_id, card_id, name, category, monthly_amount, first_date, months) VALUES (?,?,?,?,?,?,?)",
        (uid, card_id, body.name, body.category, _r(body.monthly_amount), body.first_date.isoformat(), body.months),
    )
    conn.commit()
    return _emi_out(conn.execute("SELECT * FROM emis WHERE id=?", (cur.lastrowid,)).fetchone(), _today(today))


def _emi(conn: sqlite3.Connection, uid: int, emi_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM emis WHERE id=? AND user_id=?", (emi_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "EMI not found")
    return row


@router.put("/emis/{emi_id}", response_model=EmiOut)
def update_emi(emi_id: int, body: EmiIn, today: Optional[date] = None,
               conn: sqlite3.Connection = Conn, uid: int = Me):
    _emi(conn, uid, emi_id)
    conn.execute("UPDATE emis SET name=?, category=?, monthly_amount=?, first_date=?, months=? WHERE id=?",
                 (body.name, body.category, _r(body.monthly_amount), body.first_date.isoformat(), body.months, emi_id))
    conn.commit()
    return _emi_out(_emi(conn, uid, emi_id), _today(today))


@router.delete("/emis/{emi_id}", status_code=204)
def delete_emi(emi_id: int, conn: sqlite3.Connection = Conn, uid: int = Me):
    _emi(conn, uid, emi_id)
    conn.execute("DELETE FROM emis WHERE id=?", (emi_id,))
    conn.commit()
    return Response(status_code=204)


def owned_card(conn: sqlite3.Connection, uid: int, card_id: Optional[int], mode: Optional[str]) -> None:
    """422 unless `card_id` is one of your cards of the right type for `mode` (saving an expense)."""
    if card_id is None:
        return
    row = conn.execute("SELECT kind FROM cards WHERE id=? AND user_id=?", (card_id, uid)).fetchone()
    want = "credit" if mode == "credit_card" else "debit"
    if row is None or row["kind"] != want:
        raise HTTPException(422, f"Choose one of your {want} cards")

