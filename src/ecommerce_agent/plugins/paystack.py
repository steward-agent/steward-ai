"""Paystack adapter. The secret key is the one Paystack issued to the merchant."""

from __future__ import annotations

from datetime import datetime

import httpx

from ecommerce_agent.errors import ToolError
from ecommerce_agent.gateway import check_currency, check_id
from ecommerce_agent.models import (
    ConversionQuote,
    ConversionRequest,
    CreatePaymentRequest,
    PaymentCreated,
    PayoutRecord,
    RefundRequest,
    RefundResult,
    SettlementReport,
)
from ecommerce_agent.plugins.http_client import CallContext, JsonClient
from ecommerce_agent.plugins.money import from_minor, to_minor


class PaystackPaymentPlugin:
    """Refunds and settlement reads through the merchant's Paystack secret key."""

    name = "paystack"
    supports_safe_retry = True

    def __init__(
        self,
        secret_env: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.paystack.co",
    ) -> None:
        self.http = JsonClient(base_url, secret_env, client)

    def refund(self, ctx: CallContext, request: RefundRequest) -> RefundResult:
        check_id(request.payment_id, "payment_id")
        body = self.http.call(
            ctx,
            "POST",
            "/refund",
            {
                "transaction": request.payment_id,
                "amount": to_minor(request.amount, request.currency),
                "currency": check_currency(request.currency),
                "merchant_note": request.reason[:180],
            },
        )
        data = _data(body)
        raw = str(data.get("status", "pending")).lower()
        status = "succeeded" if raw in {"processed", "success", "succeeded"} else "pending"
        return RefundResult(
            id=str(data.get("id") or request.payment_id),
            status=status,
            amount=request.amount,
            currency=request.currency,
        )

    def quote_conversion(self, ctx: CallContext, request: ConversionRequest) -> ConversionQuote:
        del ctx, request
        raise ToolError(
            "This Paystack adapter does not quote currency conversion. Use Flutterwave, or point PAYMENT_PLUGIN=http at the converter you use.",
            status_code=400,
        )

    def create_payment(self, ctx: CallContext, request: CreatePaymentRequest) -> PaymentCreated:
        del ctx, request
        raise ToolError(
            "Start the charge in your Paystack checkout. This adapter refunds an existing transaction and does not collect card details.",
            status_code=400,
        )

    def settlement(self, ctx: CallContext, *, capture: bool, now: datetime) -> SettlementReport:
        del now
        if capture:
            raise ToolError(
                "Paystack captures a charge when it succeeds. This adapter lists settlements and does not capture a second time.",
                status_code=400,
            )
        body = self.http.call(ctx, "GET", "/settlement", None)
        payouts = []
        for item in body.get("data") or []:
            currency = check_currency(str(item.get("currency", "NGN")))
            amount = item.get("total_amount", item.get("effective_amount", "0"))
            payouts.append(
                PayoutRecord(
                    id=str(item.get("id", "settlement")),
                    amount=from_minor(int(amount), currency) if str(amount).isdigit() else amount,
                    currency=currency,
                    status=str(item.get("status", "unknown")),
                )
            )
        return SettlementReport(unsettled=[], payouts=payouts, captured=[])


def _data(body: dict) -> dict:
    if body.get("status") is False:
        raise ToolError("payment provider rejected the refund", status_code=400)
    data = body.get("data") or {}
    if not isinstance(data, dict):
        raise ToolError("payment provider returned an unexpected response")
    return data
