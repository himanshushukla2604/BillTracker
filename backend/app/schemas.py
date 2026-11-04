from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Recurrence = Literal["none", "weekly", "monthly", "quarterly", "yearly"]
PaymentMode = Literal["cash", "upi", "debit_card", "net_banking", "credit_card"]
Urgency = Literal["paid", "overdue", "urgent", "soon", "later"]


class ExpenseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=1_000_000_000)
    due_date: date
    category: str = Field(min_length=1, max_length=60)
    recurring: Recurrence = "none"
    reimbursed: float = Field(0, ge=0, le=1_000_000_000)  # paid back to you by someone else
    reimbursed_note: Optional[str] = Field(None, max_length=120)
    payment_mode: Optional[PaymentMode] = None
    card_id: Optional[int] = None  # required for credit_card; optional for debit_card (which one)

    @field_validator("name", "category")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("reimbursed_note")
    @classmethod
    def _note(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None

    @model_validator(mode="after")
    def _paid_back_fits(self) -> "ExpenseIn":
        if self.reimbursed > self.amount:
            raise ValueError("paid back cannot be more than the amount")
        if not self.reimbursed:
            self.reimbursed_note = None
        if self.payment_mode == "credit_card" and self.card_id is None:
            raise ValueError("choose which credit card")
        if self.payment_mode not in ("credit_card", "debit_card"):
            self.card_id = None
        return self


class ExpenseOut(BaseModel):
    id: Optional[int]  # None for rows that are worked out, not stored (projected, EMI, card bill)
    kind: Literal["expense", "emi", "card_bill"] = "expense"
    name: str
    amount: float  # the full bill: what you owe
    reimbursed: float = 0  # paid back to you; your own spend is amount - reimbursed
    reimbursed_note: Optional[str] = None
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
    payment_mode: Optional[PaymentMode] = None
    card_id: Optional[int] = None
    statement_date: Optional[date] = None  # card bills: the statement being paid
    emi_id: Optional[int] = None  # EMI instalments: which EMI


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
    reimbursed_total: float  # paid back to you by others; not your spending
    own_spend: float  # scheduled_total - reimbursed_total: what counts against the budget
    remaining: float  # total_budget - own_spend  (what is truly uncommitted)
    remaining_after_paid: float  # total_budget - your share of what is paid
    percent_committed: float
    overdue_count: int
    overdue_amount: float
    due_soon_count: int  # unpaid, due within the next 3 days (incl. today)
    due_soon_amount: float


class VarianceRow(BaseModel):
    category: str
    target: Optional[float]  # None => no target set for this category
    actual: float  # your own share: bills minus what was paid back
    paid: float
    reimbursed: float = 0
    variance: Optional[float]  # target - actual; positive = under target (good)
    status: Literal["under", "over", "on", "no_target"]


class Variance(BaseModel):
    month: str
    rows: list[VarianceRow]
    total_target: float
    total_actual: float
    total_variance: float
    unbudgeted_actual: float
