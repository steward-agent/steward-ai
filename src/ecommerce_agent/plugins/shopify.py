"""Shopify adapters. The shop's own Admin API token is read from the merchant environment."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

import httpx

from ecommerce_agent.errors import PluginConfigError, ToolError
from ecommerce_agent.gateway import check_id
from ecommerce_agent.models import (
    CaptureResult,
    ConversionQuote,
    ConversionRequest,
    CreatePaymentRequest,
    Order,
    OrderItem,
    PaymentCreated,
    RefundRequest,
    RefundResult,
    ReturnRequest,
    ReturnResult,
    SettlementReport,
)
from ecommerce_agent.plugins.http_client import CallContext
from ecommerce_agent.secrets import require_secret

SHOP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


def shop_base(shop: str) -> str:
    cleaned = shop.strip().removeprefix("https://").removeprefix("http://").strip("/")
    if not SHOP.fullmatch(cleaned):
        raise PluginConfigError("SHOPIFY_SHOP must be your shop domain, such as your-store.myshopify.com")
    return f"https://{cleaned}"


class _ShopifyClient:
    def __init__(self, base_url: str, secret_env: str, api_version: str, client: httpx.Client | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret_env = secret_env
        self.api_version = api_version
        self.client = client or httpx.Client(timeout=20)

    def call(self, ctx: CallContext, method: str, path: str, payload: dict | None = None) -> dict:
        secret = require_secret(ctx.secrets, self.secret_env)
        headers = {"X-Shopify-Access-Token": secret, "Accept": "application/json", "Content-Type": "application/json"}
        url = f"{self.base_url}/admin/api/{self.api_version}{path}"
        try:
            response = self.client.request(method, url, json=payload, headers=headers)
        except httpx.HTTPError:
            raise ToolError("commerce provider request failed") from None
        if response.status_code == 429:
            raise ToolError("commerce provider rate limited", status_code=429, rate_limited=True)
        if response.status_code >= 400:
            raise ToolError(f"commerce provider returned {response.status_code}", status_code=response.status_code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            body = response.json()
        except Exception:
            raise ToolError("commerce provider returned an unreadable response") from None
        if not isinstance(body, dict):
            raise ToolError("commerce provider returned an unexpected response")
        return body


class ShopifyCommercePlugin:
    """Reads orders and writes a return note. It does not refund by itself."""

    name = "shopify"
    supports_safe_retry = False

    def __init__(
        self,
        shop: str | None,
        secret_env: str,
        api_version: str = "2024-10",
        client: httpx.Client | None = None,
        base_url: str | None = None,
    ) -> None:
        resolved = base_url or (shop_base(shop) if shop else None)
        if not resolved:
            raise PluginConfigError("Set SHOPIFY_SHOP to your shop domain.")
        self.client = _ShopifyClient(resolved, secret_env, api_version, client)

    def get_order(self, ctx: CallContext, order_id: str) -> Order:
        check_id(order_id, "order_id")
        body = self.client.call(ctx, "GET", f"/orders/{order_id}.json")
        order = body["order"]
        transactions = self.client.call(ctx, "GET", f"/orders/{order_id}/transactions.json").get("transactions", [])
        payment_id = _sale_transaction_id(transactions) or str(order.get("id"))
        items = [
            OrderItem(
                sku=str(item.get("sku") or item.get("product_id") or "item"),
                name=str(item.get("title") or "Item"),
                quantity=int(item.get("quantity") or 1),
                amount=item.get("price") or "0.01",
            )
            for item in order.get("line_items", [])
        ]
        refunded = Decimal("0")
        for refund in order.get("refunds", []):
            for transaction in refund.get("transactions", []):
                if str(transaction.get("kind")) == "refund" and str(transaction.get("status")) == "success":
                    refunded += Decimal(str(transaction.get("amount", "0")))
        total = Decimal(str(order["total_price"]))
        created = datetime.fromisoformat(str(order["created_at"]).replace("Z", "+00:00"))
        customer = order.get("customer") or {}
        customer_ref = str(customer["id"]) if customer.get("id") is not None else None
        return Order(
            id=str(order["id"]),
            customer_ref=customer_ref,
            currency=str(order["currency"]),
            total=total,
            refundable=max(total - refunded, Decimal("0")),
            created_at=created,
            payment_id=str(payment_id),
            items=items,
        )

    def record_return(self, ctx: CallContext, request: ReturnRequest) -> ReturnResult:
        check_id(request.order_id, "order_id")
        note = f"Return recorded by ecommerce-agent for {format(request.amount, 'f')} {request.currency}. {request.reason}"
        self.client.call(
            ctx,
            "PUT",
            f"/orders/{request.order_id}.json",
            {"order": {"id": request.order_id, "note": note[:500], "tags": "agent-return"}},
        )
        return ReturnResult(id=f"shopify-note-{request.order_id}", status="recorded")


class ShopifyPaymentPlugin:
    """Refunds and captures through the shop's Shopify Payments transactions."""

    name = "shopify"
    supports_safe_retry = False

    def __init__(
        self,
        shop: str | None,
        secret_env: str,
        api_version: str = "2024-10",
        client: httpx.Client | None = None,
        base_url: str | None = None,
    ) -> None:
        resolved = base_url or (shop_base(shop) if shop else None)
        if not resolved:
            raise PluginConfigError("Set SHOPIFY_SHOP to your shop domain.")
        self.client = _ShopifyClient(resolved, secret_env, api_version, client)

    def refund(self, ctx: CallContext, request: RefundRequest) -> RefundResult:
        check_id(request.order_id, "order_id")
        transactions = self.client.call(ctx, "GET", f"/orders/{request.order_id}/transactions.json").get("transactions", [])
        parent = _matching_transaction(transactions, request.payment_id)
        payload = {
            "refund": {
                "note": request.reason[:200],
                "notify": False,
                "transactions": [
                    {
                        "parent_id": parent,
                        "amount": format(request.amount, "f"),
                        "kind": "refund",
                        "gateway": "shopify_payments",
                    }
                ],
            }
        }
        body = self.client.call(ctx, "POST", f"/orders/{request.order_id}/refunds.json", payload)
        refund = body.get("refund", {})
        return RefundResult(
            id=str(refund.get("id", request.order_id)),
            status="succeeded",
            amount=request.amount,
            currency=request.currency,
        )

    def quote_conversion(self, ctx: CallContext, request: ConversionRequest) -> ConversionQuote:
        del ctx, request
        raise ToolError(
            "Shopify Payments does not provide a conversion quote through this adapter. Use the payment system that converts currency for you, via PAYMENT_PLUGIN=http.",
            status_code=400,
        )

    def create_payment(self, ctx: CallContext, request: CreatePaymentRequest) -> PaymentCreated:
        del ctx, request
        raise ToolError("Create Shopify checkout in your store. This adapter refunds and captures existing orders.", status_code=400)

    def settlement(self, ctx: CallContext, *, capture: bool, now: datetime) -> SettlementReport:
        del ctx, capture, now
        raise ToolError(
            "Shopify settles payouts in the Shopify admin. This adapter can refund an order; it does not list Shopify payouts.",
            status_code=400,
        )


def _sale_transaction_id(transactions: list[dict]) -> str | None:
    for transaction in reversed(transactions):
        if transaction.get("status") == "success" and transaction.get("kind") in {"sale", "capture"}:
            return str(transaction["id"])
    return None


def _matching_transaction(transactions: list[dict], payment_id: str) -> int | str:
    for transaction in transactions:
        if str(transaction.get("id")) == payment_id and transaction.get("status") == "success":
            raw = transaction["id"]
            return int(raw) if str(raw).isdigit() else raw
    found = _sale_transaction_id(transactions)
    if found is None:
        raise ToolError("no captured Shopify transaction was found for that order", status_code=404)
    return int(found) if found.isdigit() else found
