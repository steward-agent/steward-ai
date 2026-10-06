"""Flutterwave adapter. The secret key is the one Flutterwave issued to the merchant."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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
    UnsettledPayment,
)
from ecommerce_agent.plugins.http_client import CallContext, JsonClient


class FlutterwavePaymentPlugin:
    """Refunds, quotes, and settlement reads through the merchant's Flutterwave secret key."""

    name = "flutterwave"
    supports_safe_retry = True

    def __init__(
        self,
        secret_env: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.flutterwave.com",
    ) -> None:
        self.http = JsonClient(base_url, secret_env, client)

    def refund(self, ctx: CallContext, request: RefundRequest) -> RefundResult:
        check_id(request.payment_id, "payment_id")
        body = self.http.call(
            ctx,
            "POST",
            f"/v3/transactions/{request.payment_id}/refund",
            {"amount": format(request.amount, "f"), "comments": request.reason[:180]},
        )
        data = _success_data(body)
        raw = str(data.get("status", "completed")).lower()
        status = "pending" if raw in {"pending", "processing"} else "succeeded"
        return RefundResult(
            id=str(data.get("id") or request.payment_id),
            status=status,
            amount=request.amount,
            currency=request.currency,
        )

    def quote_conversion(self, ctx: CallContext, request: ConversionRequest) -> ConversionQuote:
        source = check_currency(request.from_currency)
        target = check_currency(request.to_currency)
        amount = format(request.amount, "f")
        body = self.http.call(
            ctx,
            "GET",
            f"/v3/transfers/rates?amount={amount}&source_currency={source}&destination_currency={target}",
            None,
        )
        data = _success_data(body)
        destination = data.get("destination") or {}
        converted = _number_text(destination.get("amount", amount))
        return ConversionQuote(
            quote_id=f"flw_{source}_{target}",
            rate=_number_text(data.get("rate", "1"), places="0.000001"),
            amount=request.amount,
            from_currency=source,
            converted_amount=converted,
            to_currency=target,
            fee="0.00",
            provider="flutterwave",
        )

    def create_payment(self, ctx: CallContext, request: CreatePaymentRequest) -> PaymentCreated:
        del ctx, request
        raise ToolError(
            "Start the charge in your Flutterwave checkout. This adapter quotes, refunds, and settles. Card details stay at Flutterwave.",
            status_code=400,
        )

    def settlement(self, ctx: CallContext, *, capture: bool, now: datetime) -> SettlementReport:
        del now
        body = self.http.call(ctx, "GET", "/v3/settlements", None)
        if str(body.get("status", "")).lower() not in {"success", "successful"}:
            raise ToolError("payment provider rejected the settlement request", status_code=400)
        payouts = []
        captured: list[str] = []
        unsettled: list[UnsettledPayment] = []
        for item in body.get("data") or []:
            currency = check_currency(str(item.get("currency", "NGN")))
            status = str(item.get("status", "unknown")).lower()
            payment_id = str(item.get("id", ""))
            raw_amount = item.get("amount_settled", item.get("amount"))
            if raw_amount is None or not payment_id:
                continue
            amount = _number_text(raw_amount)
            if capture and status in {"pending", "authorized"} and payment_id:
                check_id(payment_id, "payment_id")
                self.http.call(ctx, "POST", f"/v3/charges/{payment_id}/capture", {"amount": amount})
                captured.append(payment_id)
                continue
            if status in {"pending", "authorized"} and payment_id:
                unsettled.append(
                    UnsettledPayment(
                        payment_id=check_id(payment_id, "payment_id"),
                        order_id=None,
                        amount=amount,
                        currency=currency,
                        captured=False,
                    )
                )
                continue
            payouts.append(
                PayoutRecord(id=payment_id or "settlement", amount=amount, currency=currency, status=status or "unknown")
            )
        return SettlementReport(unsettled=unsettled, payouts=payouts, captured=captured)


def _success_data(body: dict) -> dict:
    if str(body.get("status", "")).lower() not in {"success", "successful"}:
        raise ToolError("payment provider rejected the request", status_code=400)
    data = body.get("data") or {}
    if not isinstance(data, dict):
        raise ToolError("payment provider returned an unexpected response")
    return data


def _number_text(value: object, places: str = "0.01") -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ToolError("payment provider returned an unreadable amount")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(str(value)).quantize(Decimal(places)), "f")
    raise ToolError("payment provider returned an unreadable amount")
