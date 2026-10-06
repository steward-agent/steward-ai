"""Approval steps the merchant controls. Pending and denied decisions do not move money."""

from __future__ import annotations

from decimal import Decimal

import httpx

from ecommerce_agent.models import ApprovalDecision, ApprovalRequest
from ecommerce_agent.plugins.http_client import CallContext
from ecommerce_agent.redaction import redact


class ThresholdApproval:
    """Approves amounts at or under the merchant's limit. This is their rule, turned on explicitly."""

    name = "threshold"

    def __init__(self, limit: Decimal) -> None:
        self.limit = limit

    def decide(self, ctx: CallContext, request: ApprovalRequest) -> ApprovalDecision:
        del ctx
        if request.amount <= self.limit:
            return ApprovalDecision(status="approved", id=f"apr_{request.order_id}", reason="under_threshold")
        return ApprovalDecision(status="pending", id=f"apr_{request.order_id}", reason="above_threshold")


class WebhookApproval:
    """Asks the merchant's own approval URL. No URL means the refund waits."""

    name = "webhook"

    def __init__(self, url: str | None, client: httpx.Client | None = None) -> None:
        self.url = url
        self.client = client or httpx.Client(timeout=10)

    def decide(self, ctx: CallContext, request: ApprovalRequest) -> ApprovalDecision:
        approval_id = f"apr_{request.order_id}"
        if not self.url:
            return ApprovalDecision(status="pending", id=approval_id, reason="no_approval_webhook")
        body = request.model_dump(mode="json")
        body["reason"] = redact(str(body.get("reason", "")))
        body["request_id"] = ctx.request_id
        try:
            response = self.client.post(self.url, json=body, headers={"Idempotency-Key": ctx.idempotency_key})
        except httpx.HTTPError:
            return ApprovalDecision(status="pending", id=approval_id, reason="approval_webhook_unreachable")
        if response.status_code >= 400:
            return ApprovalDecision(status="pending", id=approval_id, reason="approval_webhook_rejected")
        try:
            payload = response.json()
        except Exception:
            return ApprovalDecision(status="pending", id=approval_id, reason="approval_webhook_unreadable")
        decision = str(payload.get("decision", "")).lower()
        if decision == "approved":
            return ApprovalDecision(status="approved", id=approval_id, reason="webhook_approved")
        if decision == "denied":
            return ApprovalDecision(status="denied", id=approval_id, reason="webhook_denied")
        return ApprovalDecision(status="pending", id=approval_id, reason="webhook_pending")
