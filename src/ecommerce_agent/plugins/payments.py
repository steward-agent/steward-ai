"""Payment plugins. Money movement happens at the merchant's provider."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import httpx

from ecommerce_agent.errors import PluginConfigError, ToolError
from ecommerce_agent.gateway import check_currency, check_id
from ecommerce_agent.models import (
    CaptureResult,
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
from ecommerce_agent.plugins.money import from_minor, to_minor

ZERO = Decimal("0")


class MockPaymentPlugin:
    """Local stand-in. It does not move real money."""

    name = "mock"
    supports_safe_retry = True

    def __init__(self) -> None:
        self.payments: dict[str, dict] = {}
        self.refunds: list[dict] = []
        self.quotes = {
            ("USD", "EUR"): Decimal("0.92"),
            ("EUR", "USD"): Decimal("1.09"),
            ("USD", "GBP"): Decimal("0.78"),
            ("GBP", "USD"): Decimal("1.28"),
        }
        self.calls: list[str] = []
        self._idempotent: dict[str, object] = {}

    def refund(self, ctx: CallContext, request: RefundRequest) -> RefundResult:
        self.calls.append("refund")
        cached = self._idempotent.get(ctx.idempotency_key)
        if isinstance(cached, RefundResult):
            return cached
        payment = self.payments.get(request.payment_id)
        if payment is None:
            raise ToolError("payment not found", status_code=404)
        remaining = Decimal(payment["amount"]) - Decimal(payment["refunded"])
        if request.amount > remaining:
            raise ToolError("amount exceeds refundable balance", status_code=400)
        if request.currency != payment["currency"]:
            raise ToolError("currency does not match the payment", status_code=400)
        payment["refunded"] = Decimal(payment["refunded"]) + request.amount
        result = RefundResult(
            id=f"re_mock_{len(self.refunds) + 1}",
            status="succeeded",
            amount=request.amount,
            currency=request.currency,
        )
        self.refunds.append({"id": result.id, "payment_id": request.payment_id, "amount": request.amount})
        self._idempotent[ctx.idempotency_key] = result
        return result

    def quote_conversion(self, ctx: CallContext, request: ConversionRequest) -> ConversionQuote:
        self.calls.append("quote_conversion")
        if request.from_currency == request.to_currency:
            rate = Decimal("1")
        else:
            rate = self.quotes.get((request.from_currency, request.to_currency))
        if rate is None:
            raise ToolError("conversion is not available from the mock provider", status_code=400)
        converted = (request.amount * rate).quantize(Decimal("0.01"))
        return ConversionQuote(
            quote_id=f"qx_mock_{request.from_currency}_{request.to_currency}",
            rate=rate,
            amount=request.amount,
            from_currency=request.from_currency,
            converted_amount=converted,
            to_currency=request.to_currency,
            fee=ZERO,
            provider="mock",
        )

    def create_payment(self, ctx: CallContext, request: CreatePaymentRequest) -> PaymentCreated:
        self.calls.append("create_payment")
        cached = self._idempotent.get(f"pay:{ctx.idempotency_key}")
        if isinstance(cached, PaymentCreated):
            return cached
        payment_id = f"pay_mock_{len(self.payments) + 1}"
        self.payments[payment_id] = {
            "order_id": request.order_id,
            "amount": request.amount,
            "refunded": ZERO,
            "currency": request.currency,
            "captured": False,
        }
        created = PaymentCreated(id=payment_id, status="requires_confirmation", provider="mock")
        self._idempotent[f"pay:{ctx.idempotency_key}"] = created
        return created

    def settlement(self, ctx: CallContext, *, capture: bool, now: datetime) -> SettlementReport:
        del ctx, now
        self.calls.append("capture" if capture else "reconcile")
        unsettled: list[UnsettledPayment] = []
        captured: list[str] = []
        for payment_id, payment in self.payments.items():
            if payment["captured"]:
                continue
            if capture:
                payment["captured"] = True
                captured.append(payment_id)
                continue
            unsettled.append(
                UnsettledPayment(
                    payment_id=payment_id,
                    order_id=payment.get("order_id"),
                    amount=payment["amount"],
                    currency=payment["currency"],
                    captured=False,
                )
            )
        return SettlementReport(unsettled=unsettled, payouts=[], captured=captured)


class HttpPaymentPlugin:
    """Speaks the byo-v1 contract. Point it at the adapter you run in front of your provider."""

    name = "http"
    supports_safe_retry = True

    def __init__(self, base_url: str | None, secret_env: str, client: httpx.Client | None = None) -> None:
        if not base_url:
            raise PluginConfigError("Set PAYMENT_BASE_URL to the payment system you use.")
        self.http = JsonClient(base_url, secret_env, client)

    def refund(self, ctx: CallContext, request: RefundRequest) -> RefundResult:
        check_id(request.payment_id, "payment_id")
        check_id(request.order_id, "order_id")
        body = self.http.call(
            ctx,
            "POST",
            "/v1/refunds",
            {
                "payment_id": request.payment_id,
                "order_id": request.order_id,
                "amount": format(request.amount, "f"),
                "currency": check_currency(request.currency),
                "reason": request.reason,
                "idempotency_key": ctx.idempotency_key,
            },
        )
        return RefundResult(
            id=str(body["id"]),
            status=str(body.get("status", "succeeded")),
            amount=request.amount,
            currency=request.currency,
        )

    def quote_conversion(self, ctx: CallContext, request: ConversionRequest) -> ConversionQuote:
        body = self.http.call(
            ctx,
            "POST",
            "/v1/conversions/quote",
            {
                "amount": format(request.amount, "f"),
                "from_currency": check_currency(request.from_currency),
                "to_currency": check_currency(request.to_currency),
            },
        )
        return ConversionQuote(
            quote_id=str(body["quote_id"]),
            rate=body["rate"],
            amount=request.amount,
            from_currency=request.from_currency,
            converted_amount=body["converted_amount"],
            to_currency=request.to_currency,
            fee=body.get("fee", "0.00"),
            provider=str(body.get("provider", "byo")),
        )

    def create_payment(self, ctx: CallContext, request: CreatePaymentRequest) -> PaymentCreated:
        body = self.http.call(
            ctx,
            "POST",
            "/v1/payments",
            {
                "amount": format(request.amount, "f"),
                "currency": check_currency(request.currency),
                "order_id": request.order_id,
                "customer_ref": request.customer_ref,
                "idempotency_key": ctx.idempotency_key,
            },
        )
        return PaymentCreated(id=str(body["id"]), status=str(body.get("status", "requires_confirmation")), provider=str(body.get("provider", "byo")))

    def settlement(self, ctx: CallContext, *, capture: bool, now: datetime) -> SettlementReport:
        listed = self.http.call(ctx, "GET", "/v1/settlements/unsettled", None)
        items = []
        captured: list[str] = []
        for raw in listed.get("items", []):
            payment_id = check_id(str(raw["payment_id"]), "payment_id")
            if capture and not raw.get("captured", False):
                capture_ctx = CallContext(ctx.request_id, _scoped_key(ctx.idempotency_key, payment_id), ctx.secrets)
                result = self.http.call(
                    capture_ctx,
                    "POST",
                    f"/v1/payments/{payment_id}/capture",
                    {"idempotency_key": capture_ctx.idempotency_key},
                )
                if result.get("captured") or result.get("status") == "succeeded":
                    captured.append(payment_id)
                continue
            if not raw.get("captured", False):
                items.append(
                    UnsettledPayment(
                        payment_id=payment_id,
                        order_id=raw.get("order_id"),
                        amount=raw["amount"],
                        currency=str(raw["currency"]).upper(),
                        captured=False,
                    )
                )
        del now
        return SettlementReport(unsettled=items, payouts=[], captured=captured)


class StripePaymentPlugin:
    """Stripe adapter. Uses the secret key already issued to the merchant. Card data stays at Stripe."""

    name = "stripe"
    supports_safe_retry = True

    def __init__(
        self,
        secret_env: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.stripe.com",
    ) -> None:
        self.http = JsonClient(base_url, secret_env, client)

    def refund(self, ctx: CallContext, request: RefundRequest) -> RefundResult:
        check_id(request.payment_id, "payment_id")
        form = {
            "payment_intent": request.payment_id,
            "amount": str(to_minor(request.amount, request.currency)),
            "reason": "requested_by_customer",
        }
        body = self._form(ctx, "POST", "/v1/refunds", form)
        status = {"succeeded": "succeeded", "pending": "pending", "failed": "failed"}.get(str(body.get("status")), "pending")
        return RefundResult(id=str(body["id"]), status=status, amount=request.amount, currency=request.currency)

    def quote_conversion(self, ctx: CallContext, request: ConversionRequest) -> ConversionQuote:
        del ctx, request
        raise ToolError(
            "This Stripe adapter does not quote currency conversion. Ask the payment system you use, or point PAYMENT_PLUGIN=http at your own converter.",
            status_code=400,
        )

    def create_payment(self, ctx: CallContext, request: CreatePaymentRequest) -> PaymentCreated:
        form = {
            "amount": str(to_minor(request.amount, request.currency)),
            "currency": request.currency.lower(),
            "automatic_payment_methods[enabled]": "true",
        }
        if request.order_id:
            form["metadata[order_id]"] = request.order_id
        body = self._form(ctx, "POST", "/v1/payment_intents", form)
        return PaymentCreated(id=str(body["id"]), status=str(body.get("status", "requires_confirmation")), provider="stripe")

    def settlement(self, ctx: CallContext, *, capture: bool, now: datetime) -> SettlementReport:
        del now
        intents = self.http.call(ctx, "GET", "/v1/payment_intents?limit=20", None)
        payouts_body = self.http.call(ctx, "GET", "/v1/payouts?limit=20", None)
        unsettled: list[UnsettledPayment] = []
        captured: list[str] = []
        for item in intents.get("data", []):
            if item.get("status") != "requires_capture":
                continue
            payment_id = check_id(str(item["id"]), "payment_id")
            if capture:
                capture_ctx = CallContext(ctx.request_id, _scoped_key(ctx.idempotency_key, payment_id), ctx.secrets)
                self._form(capture_ctx, "POST", f"/v1/payment_intents/{payment_id}/capture", {})
                captured.append(payment_id)
                continue
            currency = str(item.get("currency", "usd")).upper()
            unsettled.append(
                UnsettledPayment(
                    payment_id=payment_id,
                    order_id=(item.get("metadata") or {}).get("order_id"),
                    amount=from_minor(int(item["amount"]), currency),
                    currency=currency,
                    captured=False,
                )
            )
        payouts = []
        for item in payouts_body.get("data", []):
            currency = str(item.get("currency", "usd")).upper()
            payouts.append(
                PayoutRecord(
                    id=str(item["id"]),
                    amount=from_minor(int(item["amount"]), currency),
                    currency=currency,
                    status=str(item.get("status", "unknown")),
                )
            )
        return SettlementReport(unsettled=unsettled, payouts=payouts, captured=captured)

    def _form(self, ctx: CallContext, method: str, path: str, form: dict[str, str]) -> dict:
        from ecommerce_agent.secrets import require_secret

        secret = require_secret(ctx.secrets, self.http.secret_env)
        headers = {"Authorization": f"Bearer {secret}", "Idempotency-Key": ctx.idempotency_key}
        try:
            response = self.http.client.request(method, f"{self.http.base_url}{path}", data=form, headers=headers)
        except httpx.HTTPError:
            raise ToolError("payment provider request failed") from None
        if response.status_code == 429:
            raise ToolError("payment provider rate limited", status_code=429, rate_limited=True)
        if response.status_code >= 400:
            raise ToolError(f"payment provider returned {response.status_code}", status_code=response.status_code)
        try:
            body = response.json()
        except Exception:
            raise ToolError("payment provider returned an unreadable response") from None
        if not isinstance(body, dict):
            raise ToolError("payment provider returned an unexpected response")
        return body


def _scoped_key(base: str, payment_id: str) -> str:
    return f"{base}-{payment_id}"[:80]
