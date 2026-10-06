"""Register built-in plugins. Third-party packages can add entry points with the same group names."""

from __future__ import annotations

import httpx

from ecommerce_agent.errors import PluginConfigError
from ecommerce_agent.plugins.approval import ThresholdApproval, WebhookApproval
from ecommerce_agent.plugins.commerce import HttpCommercePlugin, MockCommercePlugin
from ecommerce_agent.plugins.flutterwave import FlutterwavePaymentPlugin
from ecommerce_agent.plugins.paystack import PaystackPaymentPlugin
from ecommerce_agent.plugins.payments import HttpPaymentPlugin, MockPaymentPlugin, StripePaymentPlugin
from ecommerce_agent.plugins.shopify import ShopifyCommercePlugin, ShopifyPaymentPlugin
from ecommerce_agent.settings import Settings


def payment_secret_env(settings: Settings) -> str:
    """Env var name for the selected payment plugin. The secret value is not read here."""

    if settings.payment_secret_env != "PAYMENT_API_KEY":
        return settings.payment_secret_env
    names = {
        "stripe": settings.stripe_secret_env,
        "paystack": settings.paystack_secret_env,
        "flutterwave": settings.flutterwave_secret_env,
        "shopify": settings.shopify_secret_env,
        "http": settings.payment_secret_env,
    }
    return names.get(settings.payment_plugin, settings.payment_secret_env)


def commerce_secret_env(settings: Settings) -> str:
    if settings.commerce_plugin == "shopify" and settings.commerce_secret_env == "COMMERCE_API_KEY":
        return settings.shopify_secret_env
    return settings.commerce_secret_env


def provider_key_names(settings: Settings) -> list[tuple[str, str, str]]:
    """Provider, environment variable name, and what the key is for. Values stay out."""

    return [
        ("stripe", settings.stripe_secret_env, "Stripe secret key"),
        ("stripe_publishable", settings.stripe_publishable_env, "Stripe publishable key"),
        ("paystack", settings.paystack_secret_env, "Paystack secret key"),
        ("paystack_public", settings.paystack_public_env, "Paystack public key"),
        ("flutterwave", settings.flutterwave_secret_env, "Flutterwave secret key"),
        ("flutterwave_public", settings.flutterwave_public_env, "Flutterwave public key"),
        ("shopify", settings.shopify_secret_env, "Shopify Admin API token"),
        ("http", settings.payment_secret_env, "Key for any other payment provider"),
        ("commerce", commerce_secret_env(settings), "Commerce API key"),
    ]


def create_payment(settings: Settings, client: httpx.Client | None = None):
    name = settings.payment_plugin
    secret_env = payment_secret_env(settings)
    if name == "mock":
        return MockPaymentPlugin()
    if name == "http":
        return HttpPaymentPlugin(settings.payment_base_url, secret_env, client)
    if name == "stripe":
        return StripePaymentPlugin(secret_env, client=client, base_url=settings.stripe_base_url)
    if name == "paystack":
        return PaystackPaymentPlugin(secret_env, client=client, base_url=settings.paystack_base_url)
    if name == "flutterwave":
        return FlutterwavePaymentPlugin(
            secret_env,
            client=client,
            base_url=settings.flutterwave_base_url,
        )
    if name == "shopify":
        return ShopifyPaymentPlugin(
            settings.shopify_shop,
            secret_env,
            settings.shopify_api_version,
            client=client,
        )
    external = _entry_point("ecommerce_agent.payment_plugins", name)
    if external is not None:
        return external()
    raise PluginConfigError(
        f"Unknown payment plugin '{name}'. Use mock, http, stripe, paystack, flutterwave, or shopify. Any other provider uses http."
    )


def create_commerce(settings: Settings, client: httpx.Client | None = None):
    name = settings.commerce_plugin
    secret_env = commerce_secret_env(settings)
    if name == "mock":
        return MockCommercePlugin()
    if name == "http":
        return HttpCommercePlugin(settings.commerce_base_url, secret_env, client)
    if name == "shopify":
        return ShopifyCommercePlugin(
            settings.shopify_shop,
            secret_env,
            settings.shopify_api_version,
            client=client,
        )
    external = _entry_point("ecommerce_agent.commerce_plugins", name)
    if external is not None:
        return external()
    raise PluginConfigError(
        f"Unknown commerce plugin '{name}'. Use mock, http, or shopify, or register an entry point."
    )


def create_approval(settings: Settings, client: httpx.Client | None = None):
    if settings.approval_plugin == "threshold":
        return ThresholdApproval(settings.auto_approve_below)
    if settings.approval_plugin == "webhook":
        return WebhookApproval(settings.approval_webhook_url, client=client)
    raise PluginConfigError("approval_plugin must be webhook or threshold")


def _entry_point(group: str, name: str):
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return None
    discovered = entry_points()
    selected = discovered.select(group=group) if hasattr(discovered, "select") else discovered.get(group, [])
    for item in selected:
        if item.name == name:
            return item.load()
    return None
