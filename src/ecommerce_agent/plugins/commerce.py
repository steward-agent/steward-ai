"""Commerce plugins. These read orders and record returns. They do not replace your store database."""

from __future__ import annotations

from datetime import datetime

import httpx

from ecommerce_agent.errors import ToolError
from ecommerce_agent.gateway import check_currency, check_id
from ecommerce_agent.models import Order, OrderItem, ReturnRequest, ReturnResult
from ecommerce_agent.plugins.http_client import CallContext, JsonClient


class MockCommercePlugin:
    name = "mock"
    supports_safe_retry = True

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self.returns: list[ReturnResult] = []
        self.calls: list[str] = []
        self.fail_returns = False
        self._idempotent: dict[str, ReturnResult] = {}

    def get_order(self, ctx: CallContext, order_id: str) -> Order:
        del ctx
        self.calls.append("get_order")
        check_id(order_id, "order_id")
        order = self.orders.get(order_id)
        if order is None:
            raise ToolError("order not found", status_code=404)
        return order

    def record_return(self, ctx: CallContext, request: ReturnRequest) -> ReturnResult:
        self.calls.append("record_return")
        cached = self._idempotent.get(ctx.idempotency_key)
        if cached is not None:
            return cached
        if self.fail_returns:
            raise ToolError("commerce system could not record the return", status_code=503)
        result = ReturnResult(id=f"ret_mock_{len(self.returns) + 1}", status="recorded")
        self.returns.append(result)
        self._idempotent[ctx.idempotency_key] = result
        del request
        return result


class HttpCommercePlugin:
    """byo-v1 commerce contract. Implement it on your store, or in a small adapter beside it."""

    name = "http"
    supports_safe_retry = True

    def __init__(self, base_url: str | None, secret_env: str, client: httpx.Client | None = None) -> None:
        if not base_url:
            raise ToolError("Set COMMERCE_BASE_URL to the commerce system you use.")
        self.http = JsonClient(base_url, secret_env, client)

    def get_order(self, ctx: CallContext, order_id: str) -> Order:
        body = self.http.call(ctx, "GET", f"/v1/orders/{check_id(order_id, 'order_id')}", None)
        return _order_from_body(body)

    def record_return(self, ctx: CallContext, request: ReturnRequest) -> ReturnResult:
        check_id(request.order_id, "order_id")
        body = self.http.call(
            ctx,
            "POST",
            "/v1/returns",
            {
                "order_id": request.order_id,
                "amount": format(request.amount, "f"),
                "currency": check_currency(request.currency),
                "reason": request.reason,
                "idempotency_key": ctx.idempotency_key,
            },
        )
        return ReturnResult(id=str(body["id"]), status=str(body.get("status", "recorded")))


def _order_from_body(body: dict) -> Order:
    items = [
        OrderItem(
            sku=str(item.get("sku", "item")),
            name=str(item.get("name", "Item")),
            quantity=int(item.get("quantity", 1)),
            amount=item["amount"],
        )
        for item in body.get("items", [])
    ]
    created = body["created_at"]
    if isinstance(created, str):
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
    else:
        created_at = created
    return Order(
        id=check_id(str(body["id"]), "order_id"),
        customer_ref=body.get("customer_ref"),
        currency=check_currency(str(body["currency"])),
        total=body["total"],
        refundable=body["refundable"],
        created_at=created_at,
        payment_id=check_id(str(body["payment_id"]), "payment_id"),
        items=items,
    )
