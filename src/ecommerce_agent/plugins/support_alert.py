"""Alerts the merchant's support channel. The payload is the refund summary, already redacted."""

from __future__ import annotations

import httpx

from ecommerce_agent.logging import get_logger
from ecommerce_agent.models import ApprovalRequest
from ecommerce_agent.plugins.http_client import CallContext
from ecommerce_agent.redaction import redact

logger = get_logger()


class SupportAlert:
    def __init__(self, url: str | None, client: httpx.Client | None = None) -> None:
        self.url = url
        self.client = client or httpx.Client(timeout=10)

    def notify(self, ctx: CallContext, request: ApprovalRequest) -> str:
        logger.info(
            "support_alert request_id=%s order_id=%s amount=%s currency=%s",
            ctx.request_id,
            request.order_id,
            format(request.amount, "f"),
            request.currency,
        )
        if not self.url:
            return "support_alert_not_configured"
        body = request.model_dump(mode="json")
        body["type"] = "refund_above_threshold"
        body["request_id"] = ctx.request_id
        body["reason"] = redact(str(body.get("reason", "")))
        try:
            response = self.client.post(
                self.url,
                json=body,
                headers={"Idempotency-Key": ctx.idempotency_key, "Content-Type": "application/json"},
            )
        except httpx.HTTPError:
            return "support_alert_failed"
        if response.status_code >= 400:
            return "support_alert_failed"
        return "support_alerted"
