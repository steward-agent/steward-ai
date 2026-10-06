"""Auth, shopper signatures, and rate limits for one merchant deployment."""

from __future__ import annotations

import hashlib
import hmac
import re
import time

from ecommerce_agent.errors import Forbidden, PluginConfigError, RateLimited, Unauthorized
from ecommerce_agent.models import Caller, Scope
from ecommerce_agent.secrets import SecretSource
from ecommerce_agent.settings import Settings

MAX_SIGNATURE_TTL_SECONDS = 15 * 60
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CUSTOMER_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def check_id(value: str, label: str = "id") -> str:
    if not ID_PATTERN.fullmatch(value):
        raise PluginConfigError(f"invalid {label}")
    return value


def check_customer_ref(value: str) -> str:
    if not CUSTOMER_PATTERN.fullmatch(value):
        raise PluginConfigError("customer_ref must be your stable customer id, not an email address")
    return value


def check_currency(value: str) -> str:
    currency = value.upper()
    if not CURRENCY_PATTERN.fullmatch(currency):
        raise PluginConfigError("currency must be a 3-letter code")
    return currency


def check_idempotency_key(value: str) -> str:
    if not IDEMPOTENCY_PATTERN.fullmatch(value):
        raise PluginConfigError("invalid idempotency_key")
    return value


def sign_customer(server_token: str, customer_ref: str, order_id: str, expires_at: int) -> str:
    """Sign a short-lived shopper grant with the server token. The website backend calls this."""

    if not server_token:
        raise PluginConfigError("server token is required to sign a shopper grant")
    check_customer_ref(customer_ref)
    check_id(order_id, "order_id")
    payload = f"{customer_ref}:{order_id}:{int(expires_at)}".encode()
    return hmac.new(server_token.encode(), payload, hashlib.sha256).hexdigest()


def verify_customer_signature(
    server_token: str,
    customer_ref: str,
    order_id: str,
    expires_at: int,
    signature: str,
    now: int | None = None,
) -> bool:
    current = int(time.time()) if now is None else now
    if expires_at < current - 30:
        return False
    if expires_at > current + MAX_SIGNATURE_TTL_SECONDS:
        return False
    if not re.fullmatch(r"[a-f0-9]{64}", signature):
        return False
    expected = sign_customer(server_token, customer_ref, order_id, expires_at)
    return hmac.compare_digest(expected, signature)


def _matches(candidate: str, expected: str | None) -> bool:
    if not expected or not candidate or len(candidate) != len(expected):
        return False
    return hmac.compare_digest(candidate, expected)


class RateLimiter:
    """Token bucket. One deployment, one merchant, separate buckets per token scope."""

    def __init__(self, rpm: int) -> None:
        self.capacity = max(rpm, 1)
        self.tokens = float(self.capacity)
        self.refill_per_sec = self.capacity / 60
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.updated
        self.updated = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Gateway:
    def __init__(self, settings: Settings, secrets: SecretSource) -> None:
        self.settings = settings
        self.secrets = secrets
        self._limiters = {
            Scope.PUBLIC: RateLimiter(settings.rate_limit_rpm),
            Scope.SERVER: RateLimiter(settings.rate_limit_rpm),
        }
        public = secrets.get(settings.public_token_env)
        server = secrets.get(settings.server_token_env)
        if public and server and public == server:
            raise PluginConfigError("PLUGIN_PUBLIC_TOKEN and PLUGIN_SERVER_TOKEN must be different")

    def authenticate(self, authorization: str | None) -> Caller:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise Unauthorized("unauthorized")
        token = authorization.split(" ", 1)[1].strip()
        server = self.secrets.get(self.settings.server_token_env)
        public = self.secrets.get(self.settings.public_token_env)
        if server is None and public is None:
            raise PluginConfigError(
                "Set PLUGIN_PUBLIC_TOKEN and PLUGIN_SERVER_TOKEN on your server before serving traffic."
            )
        if _matches(token, server):
            return Caller(scope=Scope.SERVER)
        if _matches(token, public):
            return Caller(scope=Scope.PUBLIC)
        raise Unauthorized("unauthorized")

    def enforce_rate_limit(self, caller: Caller) -> None:
        limiter = self._limiters[caller.scope]
        if not limiter.allow():
            raise RateLimited(retry_after=1)

    def require_server(self, caller: Caller) -> None:
        if caller.scope != Scope.SERVER:
            raise Forbidden("server_token_required")
