from typing import Literal

from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    dish_name: str
    quantity: int
    price: float


class GuardrailState(BaseModel):
    last_violation_type: str | None = None
    last_violation_reason: str | None = None
    blocked_attempts: int = 0


class ReservationTracker(BaseModel):
    status: Literal["idle", "collecting", "pending", "confirmed"] = "idle"
    confirmation: str | None = None
    name: str | None = None
    date: str | None = None
    time: str | None = None
    party_size: int | None = None


class ComplaintTracker(BaseModel):
    active: bool = False
    severity: Literal["low", "medium", "high"] | None = None
    summary: str | None = None
    resolution_options: list[str] = Field(default_factory=list)
    chosen_resolution: str | None = None
    manager_callback_requested: bool = False
    escalated: bool = False


class RestaurantContext(BaseModel):
    customer_name: str = "Guest"
    preferred_language: Literal["ko", "en"] = "ko"
    last_intent: str | None = None
    triage_summary: str | None = None
    sentiment_score: float | None = None
    guardrail_state: GuardrailState = Field(default_factory=GuardrailState)
    order_items: list[OrderItem] = Field(default_factory=list)
    order_confirmed: bool = False
    reservation: ReservationTracker = Field(default_factory=ReservationTracker)
    complaint: ComplaintTracker = Field(default_factory=ComplaintTracker)
    handoff_history: list["HandoffData"] = Field(default_factory=list)


class InputGuardRailOutput(BaseModel):
    is_off_topic: bool
    contains_abuse: bool
    reason: str


class OutputGuardRailOutput(BaseModel):
    is_professional: bool
    reveals_internal_info: bool
    makes_unverified_claims: bool
    reason: str


class HandoffData(BaseModel):
    to_agent_name: str
    issue_type: str
    issue_description: str
    reason: str
