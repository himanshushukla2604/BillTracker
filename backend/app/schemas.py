from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Recurrence = Literal["none", "weekly", "monthly", "quarterly", "yearly"]
Urgency = Literal["paid", "overdue", "urgent", "soon", "later"]


class ExpenseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=1_000_000_000)
    due_date: date
    category: str = Field(min_length=1, max_length=60)
    recurring: Recurrence = "none"

    @field_validator("name", "category")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ExpenseOut(BaseModel):
    id: Optional[int]  # None for a projected occurrence (not stored yet)
    name: str
    amount: float
    due_date: date
    category: str
    recurring: Recurrence
    paid: bool
    paid_on: Optional[date] = None
    generated_from: Optional[int] = None
    days_left: int
    urgency: Urgency
    projected: bool = False  # a future occurrence of a recurring bill, not stored yet
    projected_from: Optional[int] = None  # the unpaid bill it rolls forward from


class SettingsIn(BaseModel):
    total_budget: float = Field(ge=0, le=1_000_000_000)


class SettingsOut(BaseModel):
    total_budget: float


class BudgetIn(BaseModel):
    monthly_target: float = Field(ge=0, le=1_000_000_000)


class BudgetOut(BaseModel):
    category: str
    monthly_target: float


class Summary(BaseModel):
    month: str
    total_budget: float
    scheduled_total: float  # everything dated in the month: paid + still to pay
    paid_total: float
    unpaid_total: float
    projected_total: float  # part of unpaid_total that is projected recurring bills
    remaining: float  # total_budget - scheduled_total  (what is truly uncommitted)
    remaining_after_paid: float  # total_budget - paid_total
    percent_committed: float
    overdue_count: int
    overdue_amount: float
    due_soon_count: int  # unpaid, due within the next 3 days (incl. today)
    due_soon_amount: float


class VarianceRow(BaseModel):
    category: str
    target: Optional[float]  # None => no target set for this category
    actual: float
    paid: float
    variance: Optional[float]  # target - actual; positive = under target (good)
    status: Literal["under", "over", "on", "no_target"]


class Variance(BaseModel):
    month: str
    rows: list[VarianceRow]
    total_target: float
    total_actual: float
    total_variance: float
    unbudgeted_actual: float
