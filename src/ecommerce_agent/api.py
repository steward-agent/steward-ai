"""HTTP API mounted by the merchant. One deployment serves one store."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ecommerce_agent.errors import Forbidden, PluginConfigError, RateLimited, ToolError, Unauthorized
from ecommerce_agent.gateway import (
    Gateway,
    check_currency,
    check_customer_ref,
    check_id,
    check_idempotency_key,
    sign_customer,
    verify_customer_signature,
)
from ecommerce_agent.models import Intent, Scope, UserRequest, parse_positive_money
from ecommerce_agent.observability import SignalDraft
from ecommerce_agent.plugins.registry import commerce_secret_env, payment_secret_env, provider_key_names
from ecommerce_agent.workflow import AgentApp

WIDGET_PATH = Path(__file__).with_name("static").joinpath("widget.js")


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    channel: str = "web"
    customer_ref: str | None = None
    order_id: str | None = None
    customer_signature: str | None = None
    customer_expires: int | None = None
    idempotency_key: str | None = None
    queue_wait_ms: float | None = Field(default=None, ge=0, le=60000)

    @field_validator("channel")
    @classmethod
    def channel_label(cls, value: str) -> str:
        if not value.isidentifier() or len(value) > 32:
            raise ValueError("invalid channel")
        return value

    @field_validator("customer_ref")
    @classmethod
    def customer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return check_customer_ref(value)
        except PluginConfigError as exc:
            raise ValueError(str(exc)) from None

    @field_validator("order_id")
    @classmethod
    def order(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return check_id(value, "order_id")
        except PluginConfigError as exc:
            raise ValueError(str(exc)) from None

    @field_validator("idempotency_key")
    @classmethod
    def idem(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return check_idempotency_key(value)
        except PluginConfigError as exc:
            raise ValueError(str(exc)) from None

    @field_validator("customer_signature")
    @classmethod
    def signature(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64:
            raise ValueError("invalid signature")
        return value


class RefundIn(MessageIn):
    message: str = "I want to return this order"
    amount: str | None = None
    currency: str | None = None
    reason: str = Field(default="requested_by_customer", max_length=500)


class SettlementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "reconcile"
    idempotency_key: str | None = None

    @field_validator("mode")
    @classmethod
    def mode_ok(cls, value: str) -> str:
        if value not in {"reconcile", "capture"}:
            raise ValueError("mode must be reconcile or capture")
        return value


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=100_000)


class ConversionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str
    from_currency: str
    to_currency: str
    execute: bool = False
    order_id: str | None = None
    customer_ref: str | None = None
    idempotency_key: str | None = None


def create_api(agent: AgentApp, gateway: Gateway) -> FastAPI:
    app = FastAPI(
        title="Ecommerce Agent",
        version="0.1.0",
        description="Store plugin for support, refunds, settlement, and payment conversion on the merchant's own systems.",
    )
    if agent.settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=agent.settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "demo": agent.settings.demo}

    @app.get("/ecommerce-agent.js")
    def widget_script() -> Response:
        with WIDGET_PATH.open(encoding="utf-8") as handle:
            script = handle.read()
        return Response(script, media_type="application/javascript")

    @app.get("/demo", response_class=HTMLResponse)
    def demo() -> HTMLResponse:
        if not agent.settings.demo:
            raise HTTPException(status_code=404, detail="demo_disabled")
        server = gateway.secrets.get(agent.settings.server_token_env)
        public = gateway.secrets.get(agent.settings.public_token_env)
        if not server or not public:
            raise HTTPException(status_code=503, detail="plugin_tokens_not_configured")
        expires = int(time.time()) + 600
        signature = sign_customer(server, "cust_1", "1001", expires)
        page = _demo_page(public, signature, expires)
        return HTMLResponse(page)

    @app.get("/v1/slis")
    def slis(authorization: str | None = Header(default=None)) -> dict:
        caller = _admit(gateway, authorization)
        gateway.require_server(caller)
        return agent.observability.snapshot()

    @app.post("/v1/messages")
    def messages(body: MessageIn, authorization: str | None = Header(default=None)):
        caller = _admit(gateway, authorization)
        access = _order_access(agent, gateway, caller.scope, body)
        result = agent.handle(_user_request(body, access, intent=None), caller)
        return _public_body(result, caller.scope)

    @app.post("/v1/refunds")
    def refunds(body: RefundIn, authorization: str | None = Header(default=None)):
        caller = _admit(gateway, authorization)
        access = _order_access(agent, gateway, caller.scope, body)
        try:
            amount = parse_positive_money(body.amount) if body.amount else None
            currency = check_currency(body.currency) if body.currency else None
        except (ValueError, PluginConfigError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        request = _user_request(body, access, intent=Intent.REFUND)
        request = request.model_copy(update={"amount": amount, "currency": currency, "reason": body.reason})
        result = agent.handle(request, caller)
        return _public_body(result, caller.scope)

    @app.post("/v1/settlements")
    def settlements(body: SettlementIn, authorization: str | None = Header(default=None)):
        caller = _admit(gateway, authorization)
        gateway.require_server(caller)
        result = agent.handle(
            UserRequest(
                message="reconcile settlement",
                intent=Intent.SETTLEMENT,
                settlement_mode=body.mode,
                idempotency_key=body.idempotency_key,
                order_access=True,
            ),
            caller,
        )
        return result.model_dump(mode="json")

    @app.post("/v1/conversions/quote")
    def quote(body: ConversionIn, authorization: str | None = Header(default=None)):
        caller = _admit(gateway, authorization)
        if body.execute:
            gateway.require_server(caller)
        try:
            amount = parse_positive_money(body.amount)
            source = check_currency(body.from_currency)
            target = check_currency(body.to_currency)
        except (ValueError, PluginConfigError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        result = agent.handle(
            UserRequest(
                message="quote conversion",
                intent=Intent.CONVERSION,
                amount=amount,
                from_currency=source,
                to_currency=target,
                execute_conversion=body.execute,
                order_id=body.order_id,
                customer_ref=body.customer_ref,
                idempotency_key=body.idempotency_key,
                order_access=caller.scope == Scope.SERVER,
            ),
            caller,
        )
        return _public_body(result, caller.scope)

    @app.get("/v1/keys")
    def keys(authorization: str | None = Header(default=None)) -> dict:
        caller = _admit(gateway, authorization)
        gateway.require_server(caller)
        listed = []
        for provider, env_name, purpose in provider_key_names(agent.settings):
            listed.append(
                {
                    "provider": provider,
                    "env": env_name,
                    "purpose": purpose,
                    "configured": agent.secrets.get(env_name) is not None,
                }
            )
        return {
            "payment_plugin": agent.settings.payment_plugin,
            "active_payment_key": payment_secret_env(agent.settings),
            "active_commerce_key": commerce_secret_env(agent.settings),
            "keys": listed,
        }

    @app.get("/v1/policies")
    def policies(authorization: str | None = Header(default=None)) -> dict:
        caller = _admit(gateway, authorization)
        gateway.require_server(caller)
        agent.refresh_policies()
        return {
            "directory": agent.settings.policy_dir or "",
            "documents": [{"id": document.id, "title": document.title} for document in agent.retriever.documents],
        }

    @app.post("/v1/policies")
    def upload_policy(body: PolicyIn, authorization: str | None = Header(default=None)) -> dict:
        caller = _admit(gateway, authorization)
        gateway.require_server(caller)
        try:
            saved = agent.save_org_policy(body.name, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {
            "id": saved.id,
            "title": saved.title,
            "documents": [document.id for document in agent.retriever.documents],
        }

    @app.exception_handler(Unauthorized)
    def unauthorized(_request, _exc: Unauthorized) -> JSONResponse:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    @app.exception_handler(Forbidden)
    def forbidden(_request, exc: Forbidden) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=403)

    @app.exception_handler(RateLimited)
    def rate_limited(_request, exc: RateLimited) -> JSONResponse:
        draft = SignalDraft(request_id="rate-limit")
        draft.rate_limited = True
        draft.ttft_ms = 0
        draft.e2e_ms = 0
        agent.observability.record(draft)
        return JSONResponse(
            {"error": "rate_limited", "retry_after_seconds": exc.retry_after},
            status_code=429,
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(PluginConfigError)
    def bad_config(_request, exc: PluginConfigError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(ToolError)
    def tool_failed(_request, exc: ToolError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=502)

    return app


def _admit(gateway: Gateway, authorization: str | None):
    caller = gateway.authenticate(authorization)
    gateway.enforce_rate_limit(caller)
    return caller


def _order_access(agent: AgentApp, gateway: Gateway, scope: Scope, body: MessageIn) -> bool:
    if scope == Scope.SERVER:
        return True
    if not (body.customer_ref and body.order_id and body.customer_signature and body.customer_expires):
        return False
    server = gateway.secrets.get(agent.settings.server_token_env)
    if not server:
        return False
    return verify_customer_signature(
        server,
        body.customer_ref,
        body.order_id,
        body.customer_expires,
        body.customer_signature,
    )


def _user_request(body: MessageIn, order_access: bool, intent: Intent | None) -> UserRequest:
    return UserRequest(
        message=body.message,
        intent=intent,
        channel=body.channel,
        customer_ref=body.customer_ref,
        order_id=body.order_id,
        idempotency_key=body.idempotency_key,
        queue_wait_ms=body.queue_wait_ms,
        order_access=order_access,
    )


def _public_body(result, scope: Scope) -> dict:
    payload = result.model_dump(mode="json")
    if scope != Scope.SERVER:
        payload.pop("trace", None)
    return payload


def _demo_page(public_token: str, signature: str, expires: int) -> str:
    public_js = json.dumps(public_token)
    signature_js = json.dumps(signature)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Demo store</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 0; background: #f4f1ea; color: #1c1915; }}
    main {{ max-width: 40rem; margin: 0 auto; padding: 3rem 1.5rem 8rem; }}
    h1 {{ font-weight: 500; font-size: 2.4rem; margin-bottom: 0.25rem; }}
    p {{ font-size: 1.1rem; line-height: 1.5; }}
  </style>
</head>
<body>
  <main>
    <p>Demo store</p>
    <h1>Headphones</h1>
    <p>Order 1001 · 80.00 USD · Signed in as cust_1</p>
    <p>Use the support button to ask about a return. A refund above 50.00 in the order currency alerts support and waits. This sample is 80.00 USD, so no refund is sent until support approves it.</p>
  </main>
  <script src="/ecommerce-agent.js"></script>
  <script>
    window.EcommerceAgent.mount({{
      endpoint: "",
      publicToken: {public_js},
      customerRef: "cust_1",
      orderId: "1001",
      customerExpires: {expires},
      customerSignature: {signature_js}
    }});
  </script>
</body>
</html>
"""
