"""HTTP calls that send a bearer token and never include the token in errors."""

from __future__ import annotations

import httpx

from ecommerce_agent.errors import PluginConfigError, ToolError
from ecommerce_agent.secrets import SecretSource, require_secret


class CallContext:
    def __init__(self, request_id: str, idempotency_key: str, secrets: SecretSource) -> None:
        self.request_id = request_id
        self.idempotency_key = idempotency_key
        self.secrets = secrets


class JsonClient:
    supports_safe_retry = True

    def __init__(self, base_url: str, secret_env: str, client: httpx.Client | None = None) -> None:
        if not base_url or not base_url.startswith(("https://", "http://")):
            raise PluginConfigError("base_url must be an absolute http(s) URL on your payment or commerce system")
        self.base_url = base_url.rstrip("/")
        self.secret_env = secret_env
        self.client = client or httpx.Client(timeout=20)

    def call(self, ctx: CallContext, method: str, path: str, payload: dict | None = None) -> dict:
        if not path.startswith("/") or ".." in path:
            raise PluginConfigError("invalid provider path")
        secret = require_secret(ctx.secrets, self.secret_env)
        headers = {
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if ctx.idempotency_key:
            headers["Idempotency-Key"] = ctx.idempotency_key
        try:
            response = self.client.request(method, f"{self.base_url}{path}", json=payload, headers=headers)
        except httpx.HTTPError:
            raise ToolError("payment provider request failed") from None
        if response.status_code == 429:
            raise ToolError("payment provider rate limited", status_code=429, rate_limited=True)
        if response.status_code >= 400:
            raise ToolError(
                f"payment provider returned {response.status_code}",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except Exception:
            raise ToolError("payment provider returned an unreadable response") from None
        if not isinstance(body, dict):
            raise ToolError("payment provider returned an unexpected response")
        return body
