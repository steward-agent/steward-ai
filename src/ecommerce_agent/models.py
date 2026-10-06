"""Shared records. Amounts stay as decimals until a JSON response formats them."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

def _parse_decimal(value: object) -> Decimal:
    if isinstance(value, float):
        raise ValueError("send amounts as strings, not floating-point numbers")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError("invalid amount") from exc


def parse_positive_money(value: object) -> Decimal:
    amount = _parse_decimal(value)
    if amount <= 0 or amount > Decimal("1000000"):
        raise ValueError("amount must be greater than 0 and at most 1000000")
    return amount.quantize(Decimal("0.01"))


def parse_non_negative_money(value: object) -> Decimal:
    amount = _parse_decimal(value)
    if amount < 0 or amount > Decimal("1000000"):
        raise ValueError("amount must be from 0 to 1000000")
    return amount.quantize(Decimal("0.01"))


def _money_serializer(value: Decimal) -> str:
    return format(value, "f")


Money = Annotated[
    Decimal,
    BeforeValidator(parse_positive_money),
    PlainSerializer(_money_serializer, return_type=str, when_used="json"),
]
MoneyOrZero = Annotated[
    Decimal,
    BeforeValidator(parse_non_negative_money),
    PlainSerializer(_money_serializer, return_type=str, when_used="json"),
]


def parse_rate(value: object) -> Decimal:
    amount = _parse_decimal(value)
    if amount <= 0 or amount > Decimal("1000000"):
        raise ValueError("invalid conversion rate")
    return amount.quantize(Decimal("0.000001"))


Rate = Annotated[
    Decimal,
    BeforeValidator(parse_rate),
    PlainSerializer(_money_serializer, return_type=str, when_used="json"),
]


class Intent(str, Enum):
    CUSTOMER_SERVICE = "customer_service"
    REFUND = "refund"
    SETTLEMENT = "settlement"
    CONVERSION = "conversion"


class Outcome(str, Enum):
    COMPLETED = "completed"
    PENDING_APPROVAL = "pending_approval"
    DENIED = "denied"
    NEEDS_DETAILS = "needs_details"
    FAILED = "failed"


class Scope(str, Enum):
    PUBLIC = "public"
    SERVER = "server"


class Caller(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sku: str
    name: str
    quantity: int = Field(ge=0)
    amount: MoneyOrZero


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    customer_ref: str | None = None
    currency: str
    total: Money
    refundable: MoneyOrZero
    created_at: datetime
    payment_id: str
    items: list[OrderItem] = Field(default_factory=list)


class RefundRequest(BaseModel):
    payment_id: str
    order_id: str
    amount: Money
    currency: str
    reason: str


class RefundResult(BaseModel):
    id: str
    status: str
    amount: Money
    currency: str


class ReturnRequest(BaseModel):
    order_id: str
    amount: Money
    currency: str
    reason: str


class ReturnResult(BaseModel):
    id: str
    status: str


class ConversionRequest(BaseModel):
    amount: Money
    from_currency: str
    to_currency: str


class ConversionQuote(BaseModel):
    quote_id: str
    rate: Rate
    amount: Money
    from_currency: str
    converted_amount: Money
    to_currency: str
    fee: MoneyOrZero
    provider: str


class CreatePaymentRequest(BaseModel):
    amount: Money
    currency: str
    order_id: str | None = None
    customer_ref: str | None = None


class PaymentCreated(BaseModel):
    id: str
    status: str
    provider: str


class UnsettledPayment(BaseModel):
    payment_id: str
    order_id: str | None = None
    amount: Money
    currency: str
    captured: bool


class PayoutRecord(BaseModel):
    id: str
    amount: Money
    currency: str
    status: str


class SettlementReport(BaseModel):
    unsettled: list[UnsettledPayment] = Field(default_factory=list)
    payouts: list[PayoutRecord] = Field(default_factory=list)
    captured: list[str] = Field(default_factory=list)


class CaptureResult(BaseModel):
    id: str
    status: str
    captured: bool


class ApprovalRequest(BaseModel):
    action: str
    order_id: str
    amount: Money
    currency: str
    reason: str
    policy_window_days: int
    retrieval_score: float | None = None


class ApprovalDecision(BaseModel):
    status: str
    id: str
    reason: str


class PolicyDocument(BaseModel):
    id: str
    title: str
    text: str


class PolicyHit(BaseModel):
    document_id: str
    title: str
    excerpt: str
    score: float


class ActionRecord(BaseModel):
    tool: str
    ok: bool
    status: str
    reference: str | None = None
    amount: str | None = None
    currency: str | None = None


class AgentResult(BaseModel):
    request_id: str
    intent: Intent
    outcome: Outcome
    message: str
    actions: list[ActionRecord] = Field(default_factory=list)
    idempotency_key: str | None = None
    trace: dict = Field(default_factory=dict)


class UserRequest(BaseModel):
    """A single stateless turn. The plugin does not save this after the response."""

    model_config = ConfigDict(extra="forbid")
    message: str = ""
    intent: Intent | None = None
    channel: str = "web"
    customer_ref: str | None = None
    order_id: str | None = None
    amount: Money | None = None
    currency: str | None = None
    from_currency: str | None = None
    to_currency: str | None = None
    reason: str = "requested_by_customer"
    idempotency_key: str | None = None
    settlement_mode: str = "reconcile"
    execute_conversion: bool = False
    order_access: bool = False
    queue_wait_ms: float | None = None
