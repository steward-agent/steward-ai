"""Process configuration. Secret values are named here and read elsewhere."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = "merchant"
    demo: bool = False
    payment_plugin: str = "mock"
    commerce_plugin: str = "mock"
    approval_plugin: str = "webhook"
    payment_base_url: str | None = None
    commerce_base_url: str | None = None
    payment_secret_env: str = "PAYMENT_API_KEY"
    commerce_secret_env: str = "COMMERCE_API_KEY"
    stripe_secret_env: str = "STRIPE_SECRET_KEY"
    stripe_publishable_env: str = "STRIPE_PUBLISHABLE_KEY"
    paystack_secret_env: str = "PAYSTACK_SECRET_KEY"
    paystack_public_env: str = "PAYSTACK_PUBLIC_KEY"
    flutterwave_secret_env: str = "FLUTTERWAVE_SECRET_KEY"
    flutterwave_public_env: str = "FLUTTERWAVE_PUBLIC_KEY"
    shopify_secret_env: str = "SHOPIFY_ADMIN_TOKEN"
    public_token_env: str = "PLUGIN_PUBLIC_TOKEN"
    server_token_env: str = "PLUGIN_SERVER_TOKEN"
    shopify_shop: str | None = None
    shopify_api_version: str = "2024-10"
    stripe_base_url: str = "https://api.stripe.com"
    paystack_base_url: str = "https://api.paystack.co"
    flutterwave_base_url: str = "https://api.flutterwave.com"
    approval_webhook_url: str | None = None
    support_alert_url: str | None = None
    support_alert_above: Decimal = Decimal("50.00")
    auto_approve_below: Decimal = Decimal("100.00")
    return_window_days: int = 30
    grounding_score: float = 0.34
    rate_limit_rpm: int = 60
    policy_dir: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    host: str = "127.0.0.1"
    port: int = 8000
    langfuse_host: str | None = None
    langfuse_public_key_env: str = "LANGFUSE_PUBLIC_KEY"
    langfuse_secret_key_env: str = "LANGFUSE_SECRET_KEY"
    usd_per_million_input_tokens: Decimal | None = None
    usd_per_million_output_tokens: Decimal | None = None
    trace_order_ids: bool = False

    @field_validator("merchant_id")
    @classmethod
    def merchant_id_safe(cls, value: str) -> str:
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("merchant_id must contain only letters, numbers, _ and -")
        return value

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS origins must be explicit. A wildcard is not accepted.")
        return value

    @field_validator("approval_plugin")
    @classmethod
    def known_approval(cls, value: str) -> str:
        if value not in {"webhook", "threshold"}:
            raise ValueError("approval_plugin must be webhook or threshold")
        return value

    @field_validator("auto_approve_below")
    @classmethod
    def positive_limit(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("auto_approve_below must be zero or greater")
        return value


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _decimal(value: str | None) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    return Decimal(value)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build settings from names and flags. Provider secret values are not copied in."""

    source = os.environ if env is None else env
    origins = [item.strip() for item in source.get("CORS_ORIGINS", "").split(",") if item.strip()]
    return Settings(
        merchant_id=source.get("MERCHANT_ID", "merchant"),
        demo=_flag(source, "DEMO"),
        payment_plugin=source.get("PAYMENT_PLUGIN", "mock"),
        commerce_plugin=source.get("COMMERCE_PLUGIN", "mock"),
        approval_plugin=source.get("APPROVAL_PLUGIN", "webhook"),
        payment_base_url=source.get("PAYMENT_BASE_URL") or None,
        commerce_base_url=source.get("COMMERCE_BASE_URL") or None,
        payment_secret_env=source.get("PAYMENT_SECRET_ENV", "PAYMENT_API_KEY"),
        commerce_secret_env=source.get("COMMERCE_SECRET_ENV", "COMMERCE_API_KEY"),
        stripe_secret_env=source.get("STRIPE_SECRET_ENV", "STRIPE_SECRET_KEY"),
        stripe_publishable_env=source.get("STRIPE_PUBLISHABLE_ENV", "STRIPE_PUBLISHABLE_KEY"),
        paystack_secret_env=source.get("PAYSTACK_SECRET_ENV", "PAYSTACK_SECRET_KEY"),
        paystack_public_env=source.get("PAYSTACK_PUBLIC_ENV", "PAYSTACK_PUBLIC_KEY"),
        flutterwave_secret_env=source.get("FLUTTERWAVE_SECRET_ENV", "FLUTTERWAVE_SECRET_KEY"),
        flutterwave_public_env=source.get("FLUTTERWAVE_PUBLIC_ENV", "FLUTTERWAVE_PUBLIC_KEY"),
        shopify_secret_env=source.get("SHOPIFY_SECRET_ENV", "SHOPIFY_ADMIN_TOKEN"),
        public_token_env=source.get("PUBLIC_TOKEN_ENV", "PLUGIN_PUBLIC_TOKEN"),
        server_token_env=source.get("SERVER_TOKEN_ENV", "PLUGIN_SERVER_TOKEN"),
        shopify_shop=source.get("SHOPIFY_SHOP") or None,
        stripe_base_url=source.get("STRIPE_BASE_URL", "https://api.stripe.com"),
        paystack_base_url=source.get("PAYSTACK_BASE_URL", "https://api.paystack.co"),
        flutterwave_base_url=source.get("FLUTTERWAVE_BASE_URL", "https://api.flutterwave.com"),
        approval_webhook_url=source.get("APPROVAL_WEBHOOK_URL") or None,
        support_alert_url=source.get("SUPPORT_ALERT_URL") or None,
        support_alert_above=Decimal(source.get("SUPPORT_ALERT_ABOVE", "50.00")),
        auto_approve_below=Decimal(source.get("AUTO_APPROVE_BELOW", "100.00")),
        return_window_days=int(source.get("RETURN_WINDOW_DAYS", "30")),
        rate_limit_rpm=int(source.get("RATE_LIMIT_RPM", "60")),
        policy_dir=source.get("POLICY_DIR", "org_rules"),
        cors_origins=origins,
        host=source.get("HOST", "127.0.0.1"),
        port=int(source.get("PORT", "8000")),
        langfuse_host=source.get("LANGFUSE_HOST") or None,
        langfuse_public_key_env=source.get("LANGFUSE_PUBLIC_KEY_ENV", "LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key_env=source.get("LANGFUSE_SECRET_KEY_ENV", "LANGFUSE_SECRET_KEY"),
        usd_per_million_input_tokens=_decimal(source.get("USD_PER_MILLION_INPUT_TOKENS")),
        usd_per_million_output_tokens=_decimal(source.get("USD_PER_MILLION_OUTPUT_TOKENS")),
        trace_order_ids=_flag(source, "TRACE_ORDER_IDS"),
    )
