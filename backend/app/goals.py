"""Goals: money set aside for something bigger than a month, like building a house.

An expense tagged with a goal is spending towards that goal, not monthly spending, so it never
counts against the monthly budget or the category targets. It still shows in the expense list,
and a bill still to pay still shows in Upcoming bills. A goal's progress is your own share
(amount minus anything paid back) of every expense tagged with it, in any month.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from . import auth, db
from .ledger import r as _r, today_or as _today

router = APIRouter(prefix="/api/goals", tags=["goals"])
Conn = Depends(db.get_conn)
Me = Depends(auth.current_user)


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    budget: float = Field(gt=0, le=10_000_000_000)  # what you plan to spend on it in all
    target_date: Optional[date] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class GoalOut(BaseModel):
    id: int
    name: str
    budget: float
    target_date: Optional[date]
    spent: float  # your share of everything tagged with it, paid or still to pay
    paid: float  # the part of `spent` already paid
    left: float  # budget - spent; negative once over budget
    count: int  # expenses tagged with it
    days_to_target: Optional[int]


def _get(conn: sqlite3.Connection, uid: int, goal_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (goal_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "Goal not found")
    return row


def owned_goal(conn: sqlite3.Connection, uid: int, goal_id: Optional[int]) -> None:
    """422 unless `goal_id` is empty or one of your goals (saving an expense)."""
    if goal_id is not None and conn.execute(
            "SELECT 1 FROM goals WHERE id=? AND user_id=?", (goal_id, uid)).fetchone() is None:
        raise HTTPException(422, "Choose one of your goals")


def _out(conn: sqlite3.Connection, row: sqlite3.Row, today: date) -> GoalOut:
    s = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(amount - reimbursed), 0) spent,"
        " COALESCE(SUM(CASE WHEN paid=1 THEN amount - reimbursed ELSE 0 END), 0) paid"
        " FROM expenses WHERE goal_id=? AND user_id=?", (row["id"], row["user_id"])).fetchone()
    target = date.fromisoformat(row["target_date"]) if row["target_date"] else None
    return GoalOut(
        id=row["id"], name=row["name"], budget=row["budget"], target_date=target,
        spent=_r(s["spent"]), paid=_r(s["paid"]), left=_r(row["budget"] - s["spent"]), count=s["n"],
        days_to_target=(target - today).days if target else None,
    )


@router.get("", response_model=list[GoalOut])
def list_goals(today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    t = _today(today)
    return [_out(conn, r, t) for r in conn.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id", (uid,))]


@router.post("", response_model=GoalOut, status_code=201)
def create_goal(body: GoalIn, today: Optional[date] = None, conn: sqlite3.Connection = Conn, uid: int = Me):
    cur = conn.execute("INSERT INTO goals (user_id, name, budget, target_date) VALUES (?,?,?,?)",
                       (uid, body.name, _r(body.budget), body.target_date.isoformat() if body.target_date else None))
    conn.commit()
    return _out(conn, _get(conn, uid, cur.lastrowid), _today(today))


@router.put("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, body: GoalIn, today: Optional[date] = None,
                conn: sqlite3.Connection = Conn, uid: int = Me):
    _get(conn, uid, goal_id)
    conn.execute("UPDATE goals SET name=?, budget=?, target_date=? WHERE id=?",
                 (body.name, _r(body.budget), body.target_date.isoformat() if body.target_date else None, goal_id))
    conn.commit()
    return _out(conn, _get(conn, uid, goal_id), _today(today))


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: int, conn: sqlite3.Connection = Conn, uid: int = Me):
    """Removes the goal. Its expenses stay, untagged, and count as monthly spending again."""
    _get(conn, uid, goal_id)
    conn.execute("UPDATE expenses SET goal_id=NULL WHERE goal_id=?", (goal_id,))
    conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
    conn.commit()
    return Response(status_code=204)
