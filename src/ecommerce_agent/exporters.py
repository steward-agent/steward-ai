"""Optional Langfuse export. Payloads omit shopper text, card data, and provider secrets."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

import httpx

from ecommerce_agent.models import AgentResult
from ecommerce_agent.observability import SignalDraft
from ecommerce_agent.secrets import SecretSource, require_secret
from ecommerce_agent.settings import Settings


def langfuse_batch(draft: SignalDraft, result: AgentResult, *, include_order_id: bool, order_id: str | None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "intent": result.intent.value,
        "outcome": result.outcome.value,
        "nodes": draft.nodes,
        "fallback_attempted": draft.fallback_attempted,
        "fallback_recovered": draft.fallback_recovered,
        "rate_limited": draft.rate_limited,
        "tool_calls": draft.tool_calls,
        "tool_successes": draft.tool_successes,
        "retrieval_score": draft.retrieval_score,
        "ttft_ms": draft.ttft_ms,
        "end_to_end_latency_ms": draft.e2e_ms,
    }
    if include_order_id and order_id:
        metadata["order_id"] = order_id
    return {
        "batch": [
            {
                "id": uuid.uuid4().hex,
                "type": "trace-create",
                "timestamp": now,
                "body": {
                    "id": draft.request_id,
                    "timestamp": now,
                    "name": "ecommerce-agent",
                    "metadata": metadata,
                    "tags": [result.intent.value],
                },
            }
        ]
    }


class LangfuseExporter:
    def __init__(self, settings: Settings, secrets: SecretSource, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.secrets = secrets
        self.client = client or httpx.Client(timeout=5)

    def export(self, draft: SignalDraft, result: AgentResult, include_order_id: bool = False) -> None:
        if not self.settings.langfuse_host:
            return
        public_key = require_secret(self.secrets, self.settings.langfuse_public_key_env)
        secret_key = require_secret(self.secrets, self.settings.langfuse_secret_key_env)
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        payload = langfuse_batch(draft, result, include_order_id=include_order_id, order_id=None)
        self.client.post(
            f"{self.settings.langfuse_host.rstrip('/')}/api/public/ingestion",
            json=payload,
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        )
