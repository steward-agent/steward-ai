"""In-memory byo-v1 server.

Copy this module into your service and replace the ledger with calls to the
payment provider you already use. The sample ledger is not a payment account
and must not be used in production.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException

RATES = {
    ("USD", "EUR"): Decimal("0.92"),
    ("EUR", "USD"): Decimal("1.09"),
    ("USD", "GBP"): Decimal("0.78"),
}


def create_byo_app(expected_token: str, *, seed: bool = True) -> FastAPI:
    app = FastAPI(title="BYO payment contract reference", version="byo-v1")
    app.state.expected_token = expected_token
    app.state.payments = {}
    app.state.orders = {}
    app.state.refunds = {}
    app.state.idempotency = {}
    if seed:
        created = datetime.now(timezone.utc) - timedelta(days=5)
        app.state.orders["1001"] = {
            "id": "1001",
            "customer_ref": "cust_1",
            "currency": "USD",
            "total": "80.00",
            "refundable": "80.00",
            "created_at": created.isoformat(),
            "payment_id": "pay_1001",
            "items": [{"sku": "hp-1", "name": "Headphones", "quantity": 1, "amount": "80.00"}],
        }
        app.state.payments["pay_1001"] = {
            "order_id": "1001",
            "amount": Decimal("80.00"),
            "refunded": Decimal("0"),
            "currency": "USD",
            "captured": True,
        }
        app.state.payments["pay_auth"] = {
            "order_id": "1002",
            "amount": Decimal("20.00"),
            "refunded": Decimal("0"),
            "currency": "USD",
            "captured": False,
        }

    def authorized(authorization: str | None) -> None:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="unauthorized")
        token = authorization.split(" ", 1)[1].strip()
        expected = app.state.expected_token
        if len(token) != len(expected) or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.post("/v1/refunds")
    def refund(body: dict, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        authorized(authorization)
        key = idempotency_key or body.get("idempotency_key")
        if key and key in app.state.idempotency:
            return app.state.idempotency[key]
        payment = app.state.payments.get(body["payment_id"])
        if payment is None:
            raise HTTPException(status_code=404, detail="payment not found")
        amount = Decimal(str(body["amount"]))
        if amount > payment["amount"] - payment["refunded"]:
            raise HTTPException(status_code=400, detail="amount exceeds refundable balance")
        payment["refunded"] += amount
        order = app.state.orders.get(body.get("order_id"))
        if order is not None:
            order["refundable"] = format(Decimal(order["refundable"]) - amount, "f")
        result = {"id": f"re_{uuid4().hex[:8]}", "status": "succeeded", "amount": format(amount, "f"), "currency": body["currency"]}
        app.state.refunds[result["id"]] = result
        if key:
            app.state.idempotency[key] = result
        return result

    @app.post("/v1/conversions/quote")
    def quote(body: dict, authorization: str | None = Header(default=None)):
        authorized(authorization)
        source = body["from_currency"].upper()
        target = body["to_currency"].upper()
        rate = Decimal("1") if source == target else RATES.get((source, target))
        if rate is None:
            raise HTTPException(status_code=400, detail="conversion unavailable")
        amount = Decimal(str(body["amount"]))
        converted = (amount * rate).quantize(Decimal("0.01"))
        return {
            "quote_id": f"qx_{uuid4().hex[:8]}",
            "rate": format(rate, "f"),
            "amount": format(amount, "f"),
            "from_currency": source,
            "converted_amount": format(converted, "f"),
            "to_currency": target,
            "fee": "0.00",
            "provider": "byo-reference",
        }

    @app.post("/v1/payments")
    def create_payment(body: dict, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        authorized(authorization)
        key = idempotency_key or body.get("idempotency_key")
        if key and key in app.state.idempotency:
            return app.state.idempotency[key]
        payment_id = f"pay_{uuid4().hex[:8]}"
        app.state.payments[payment_id] = {
            "order_id": body.get("order_id"),
            "amount": Decimal(str(body["amount"])),
            "refunded": Decimal("0"),
            "currency": body["currency"].upper(),
            "captured": False,
        }
        result = {"id": payment_id, "status": "requires_confirmation", "provider": "byo-reference"}
        if key:
            app.state.idempotency[key] = result
        return result

    @app.get("/v1/settlements/unsettled")
    def unsettled(authorization: str | None = Header(default=None)):
        authorized(authorization)
        items = [
            {
                "payment_id": payment_id,
                "order_id": payment.get("order_id"),
                "amount": format(payment["amount"], "f"),
                "currency": payment["currency"],
                "captured": payment["captured"],
            }
            for payment_id, payment in app.state.payments.items()
            if not payment["captured"]
        ]
        return {"items": items}

    @app.post("/v1/payments/{payment_id}/capture")
    def capture(payment_id: str, authorization: str | None = Header(default=None)):
        authorized(authorization)
        payment = app.state.payments.get(payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="payment not found")
        payment["captured"] = True
        return {"id": payment_id, "status": "succeeded", "captured": True}

    @app.get("/v1/orders/{order_id}")
    def get_order(order_id: str, authorization: str | None = Header(default=None)):
        authorized(authorization)
        order = app.state.orders.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        return order

    @app.post("/v1/returns")
    def record_return(body: dict, authorization: str | None = Header(default=None)):
        authorized(authorization)
        if body.get("order_id") not in app.state.orders:
            raise HTTPException(status_code=404, detail="order not found")
        return {"id": f"ret_{uuid4().hex[:8]}", "status": "recorded"}

    return app
