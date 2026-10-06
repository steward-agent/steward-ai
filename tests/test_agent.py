"""Behavioral tests for refunds, settlement, conversion, and safety boundaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from ecommerce_agent.errors import PluginConfigError
from ecommerce_agent.exporters import langfuse_batch
from ecommerce_agent.gateway import Gateway, sign_customer
from ecommerce_agent.logging import configure_logging, get_logger
from ecommerce_agent.models import Caller, Intent, Order, Outcome, PolicyDocument, Scope, UserRequest
from ecommerce_agent.observability import SignalRecord, summarize
from ecommerce_agent.plugins.approval import ThresholdApproval, WebhookApproval
from ecommerce_agent.plugins.commerce import HttpCommercePlugin, MockCommercePlugin
from ecommerce_agent.plugins.http_client import CallContext
from ecommerce_agent.plugins.money import to_minor
from ecommerce_agent.plugins.flutterwave import FlutterwavePaymentPlugin
from ecommerce_agent.plugins.paystack import PaystackPaymentPlugin
from ecommerce_agent.plugins.payments import HttpPaymentPlugin, MockPaymentPlugin, StripePaymentPlugin
from ecommerce_agent.plugins.shopify import ShopifyPaymentPlugin
from ecommerce_agent.plugins.support_alert import SupportAlert
from ecommerce_agent.redaction import redact
from ecommerce_agent.reference import create_byo_app
from ecommerce_agent.retrieval import KeywordRetriever
from ecommerce_agent.routing import keyword_route
from ecommerce_agent.secrets import MapSecrets
from ecommerce_agent.settings import Settings, load_settings
from ecommerce_agent.workflow import AgentApp

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
POLICY = PolicyDocument(
    id="returns",
    title="Return policy",
    text="You can return headphones and request a refund within 30 days of delivery.",
)
SHORT_POLICY = PolicyDocument(
    id="short",
    title="Return policy",
    text="You can return headphones and request a refund within 14 days of delivery.",
)
PAN = "4242424242424242"


def _order(days: int, amount: str = "80.00", order_id: str = "1001", customer: str = "cust_1") -> Order:
    return Order(
        id=order_id,
        customer_ref=customer,
        currency="USD",
        total=Decimal(amount),
        refundable=Decimal(amount),
        created_at=NOW - timedelta(days=days),
        payment_id="pay_1001",
        items=[{"sku": "hp-1", "name": "Headphones", "quantity": 1, "amount": Decimal(amount)}],
    )


def _agent(
    order: Order | None = None,
    approval=None,
    policies: list[PolicyDocument] | None = None,
    model=None,
    limit: str = "100.00",
    support_alert: SupportAlert | None = None,
) -> tuple[AgentApp, MockPaymentPlugin, MockCommercePlugin]:
    payment = MockPaymentPlugin()
    commerce = MockCommercePlugin()
    current = order or _order(5)
    commerce.orders[current.id] = current
    payment.payments["pay_1001"] = {
        "order_id": current.id,
        "amount": current.total,
        "refunded": Decimal("0"),
        "currency": "USD",
        "captured": True,
    }
    payment.payments["pay_auth"] = {
        "order_id": "1002",
        "amount": Decimal("20.00"),
        "refunded": Decimal("0"),
        "currency": "USD",
        "captured": False,
    }
    settings = Settings(auto_approve_below=Decimal(limit), return_window_days=30)
    agent = AgentApp(
        settings=settings,
        secrets=MapSecrets({}),
        payment=payment,
        commerce=commerce,
        approval=approval or WebhookApproval(None),
        retriever=KeywordRetriever(policies if policies is not None else [POLICY]),
        model=model,
        clock=lambda: NOW,
        support_alert=support_alert,
    )
    return agent, payment, commerce


def _refund(message: str = "I want to return my headphones", **updates) -> UserRequest:
    payload = {
        "message": message,
        "intent": Intent.REFUND,
        "order_id": "1001",
        "customer_ref": "cust_1",
        "order_access": True,
        "idempotency_key": "refund-key-1001",
    }
    payload.update(updates)
    return UserRequest(**payload)


def test_redaction_removes_card_secret_and_email() -> None:
    cleaned = redact(f"email me a@b.com card {PAN} key sk_test_abc123 Bearer sk_live_zzzz")
    assert PAN not in cleaned
    assert "sk_test_abc123" not in cleaned
    assert "sk_live_zzzz" not in cleaned
    assert "a@b.com" not in cleaned
    assert "[REDACTED_CARD]" in cleaned
    assert "[REDACTED_SECRET]" in cleaned
    assert "[REDACTED_EMAIL]" in cleaned


def test_settings_do_not_copy_provider_secrets() -> None:
    settings = load_settings(
        {
            "PAYMENT_API_KEY": "sk_test_secretvalue",
            "STRIPE_SECRET_KEY": "sk_test_stripevalue",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_stripevalue",
            "PAYSTACK_SECRET_KEY": "sk_test_paystackvalue",
            "FLUTTERWAVE_SECRET_KEY": "flw_secretvalue",
            "SHOPIFY_ADMIN_TOKEN": "shpat_secretvalue",
            "DEMO": "true",
            "PLUGIN_SERVER_TOKEN": "super-secret-server-token",
            "PAYMENT_PLUGIN": "stripe",
        }
    )
    dumped = settings.model_dump_json()
    assert "sk_test_secretvalue" not in dumped
    assert "sk_test_stripevalue" not in dumped
    assert "pk_test_stripevalue" not in dumped
    assert "sk_test_paystackvalue" not in dumped
    assert "flw_secretvalue" not in dumped
    assert "shpat_secretvalue" not in dumped
    assert "super-secret-server-token" not in dumped
    assert settings.stripe_secret_env == "STRIPE_SECRET_KEY"
    assert settings.policy_dir == "org_rules"


def test_each_provider_reads_its_own_key_name() -> None:
    from ecommerce_agent.plugins.registry import create_payment, payment_secret_env

    stripe = create_payment(Settings(payment_plugin="stripe"))
    paystack = create_payment(Settings(payment_plugin="paystack"))
    flutterwave = create_payment(Settings(payment_plugin="flutterwave"))
    shopify = create_payment(Settings(payment_plugin="shopify", shopify_shop="demo.myshopify.com"))
    other = create_payment(Settings(payment_plugin="http", payment_base_url="https://payments.example"))
    custom = create_payment(Settings(payment_plugin="stripe", payment_secret_env="CUSTOM_KEY"))
    assert stripe.http.secret_env == "STRIPE_SECRET_KEY"
    assert paystack.http.secret_env == "PAYSTACK_SECRET_KEY"
    assert flutterwave.http.secret_env == "FLUTTERWAVE_SECRET_KEY"
    assert shopify.client.secret_env == "SHOPIFY_ADMIN_TOKEN"
    assert other.http.secret_env == "PAYMENT_API_KEY"
    assert custom.http.secret_env == "CUSTOM_KEY"
    assert payment_secret_env(Settings(payment_plugin="stripe")) == "STRIPE_SECRET_KEY"


def test_public_and_server_tokens_must_differ() -> None:
    with pytest.raises(PluginConfigError):
        Gateway(
            Settings(),
            MapSecrets({"PLUGIN_PUBLIC_TOKEN": "same-token-value", "PLUGIN_SERVER_TOKEN": "same-token-value"}),
        )


def test_router_matches_the_store_workflows() -> None:
    assert keyword_route("I want to return my headphones") is Intent.REFUND
    assert keyword_route("What is your return policy?") is Intent.CUSTOMER_SERVICE
    assert keyword_route("How long do I have to return an item?") is Intent.CUSTOMER_SERVICE
    assert keyword_route("reconcile payouts") is Intent.SETTLEMENT
    assert keyword_route("How does settlement work?") is Intent.CUSTOMER_SERVICE
    assert keyword_route("Quote 80 USD in EUR") is Intent.CONVERSION
    assert keyword_route("How does currency conversion work?") is Intent.CUSTOMER_SERVICE


def test_server_refund_under_policy_calls_the_payment_plugin() -> None:
    agent, payment, commerce = _agent(order=_order(5, "40.00"))
    result = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.COMPLETED
    assert "re_mock_1" in result.message
    assert payment.payments["pay_1001"]["refunded"] == Decimal("40.00")
    assert commerce.calls == ["get_order", "record_return"]
    assert payment.calls == ["refund"]
    assert "guardrails" in result.trace["nodes"]
    assert "payment_tool" in result.trace["nodes"]


def test_repeating_the_idempotency_key_does_not_refund_twice() -> None:
    agent, payment, _commerce = _agent(order=_order(5, "40.00"))
    caller = Caller(scope=Scope.SERVER)
    agent.handle(_refund(), caller)
    agent.handle(_refund(), caller)
    assert payment.payments["pay_1001"]["refunded"] == Decimal("40.00")
    assert len(payment.refunds) == 1


def test_public_request_without_a_signed_order_does_not_touch_payment() -> None:
    agent, payment, commerce = _agent()
    result = agent.handle(_refund(order_access=False), Caller(scope=Scope.PUBLIC))
    assert result.outcome is Outcome.NEEDS_DETAILS
    assert payment.calls == []
    assert commerce.calls == []


def test_public_signed_request_waits_when_no_approver_is_configured() -> None:
    agent, payment, commerce = _agent()
    result = agent.handle(_refund(), Caller(scope=Scope.PUBLIC))
    assert result.outcome is Outcome.PENDING_APPROVAL
    assert "No refund was sent" in result.message
    assert payment.calls == []
    assert commerce.calls == ["get_order"]


def test_threshold_approval_completes_a_small_public_refund() -> None:
    agent, payment, _commerce = _agent(order=_order(5, "40.00"), approval=ThresholdApproval(Decimal("100")))
    result = agent.handle(_refund(), Caller(scope=Scope.PUBLIC))
    assert result.outcome is Outcome.COMPLETED
    assert payment.calls == ["refund"]


def test_amount_above_the_limit_stays_pending() -> None:
    agent, payment, _commerce = _agent(order=_order(5, "500.00"), limit="100.00")
    result = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.PENDING_APPROVAL
    assert payment.calls == []


def test_stricter_policy_window_denies_the_refund() -> None:
    agent, payment, _commerce = _agent(order=_order(20), policies=[SHORT_POLICY])
    result = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.DENIED
    assert "14-day" in result.message
    assert payment.calls == []


def test_customer_mismatch_is_denied() -> None:
    agent, payment, _commerce = _agent()
    result = agent.handle(_refund(customer_ref="cust_2"), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.DENIED
    assert payment.calls == []


def test_commerce_failure_blocks_the_payment_call() -> None:
    agent, payment, commerce = _agent(order=_order(5, "40.00"))
    commerce.fail_returns = True
    result = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.FAILED
    assert payment.calls == []
    assert commerce.calls == ["get_order", "record_return"]


def test_webhook_approval_receives_redacted_text_and_then_refunds() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"decision": "approved"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    agent, payment, _commerce = _agent(approval=WebhookApproval("https://approvals.example/refunds", client))
    result = agent.handle(
        _refund(reason=f"lost package {PAN}"),
        Caller(scope=Scope.PUBLIC),
    )
    assert result.outcome is Outcome.COMPLETED
    assert PAN not in seen["body"]
    assert "[REDACTED_CARD]" in seen["body"]
    assert payment.calls == ["refund"]
    assert CARD_WARNING_PRESENT(result.message)


def CARD_WARNING_PRESENT(message: str) -> bool:
    return "Card numbers" in message


def test_model_text_cannot_move_money() -> None:
    class Spy:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def classify(self, text: str) -> str:
            self.seen.append(text)
            raise RuntimeError("classifier down")

        def complete(self, system: str, user: str) -> str:
            self.seen.append(system)
            self.seen.append(user)
            return "I sent the refund."

    spy = Spy()
    agent, payment, _commerce = _agent(model=spy)
    result = agent.handle(
        UserRequest(message=f"What is your return policy? {PAN}", channel="web"),
        Caller(scope=Scope.PUBLIC),
    )
    assert result.outcome is Outcome.COMPLETED
    assert result.actions == []
    assert payment.calls == []
    assert PAN not in " ".join(spy.seen)
    assert result.trace["fallback_attempted"] is True
    assert result.trace["fallback_recovered"] is True


def test_settlement_reconcile_is_server_only_and_does_not_capture() -> None:
    agent, payment, _commerce = _agent()
    denied = agent.handle(
        UserRequest(message="reconcile payouts", intent=Intent.SETTLEMENT),
        Caller(scope=Scope.PUBLIC),
    )
    assert denied.outcome is Outcome.DENIED
    assert payment.calls == []
    report = agent.handle(
        UserRequest(message="reconcile payouts", intent=Intent.SETTLEMENT, order_access=True),
        Caller(scope=Scope.SERVER),
    )
    assert report.outcome is Outcome.COMPLETED
    assert "waiting for capture" in report.message
    assert payment.payments["pay_auth"]["captured"] is False


def test_conversion_quote_from_a_sentence_does_not_create_a_payment() -> None:
    agent, payment, _commerce = _agent()
    before = set(payment.payments)
    result = agent.handle(
        UserRequest(message="Quote 80 USD in EUR"),
        Caller(scope=Scope.PUBLIC),
    )
    assert result.outcome is Outcome.COMPLETED
    assert "73.60" in result.message
    assert "EUR" in result.message
    assert set(payment.payments) == before


def test_public_conversion_execute_does_not_create_a_payment() -> None:
    agent, payment, _commerce = _agent()
    before = set(payment.payments)
    result = agent.handle(
        UserRequest(
            message="convert",
            intent=Intent.CONVERSION,
            amount=Decimal("80.00"),
            from_currency="USD",
            to_currency="EUR",
            execute_conversion=True,
        ),
        Caller(scope=Scope.PUBLIC),
    )
    assert "No payment was created" in result.message
    assert set(payment.payments) == before


def test_order_id_is_not_interpolated_into_a_url() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("the commerce plugin should reject this before a request")

    plugin = HttpCommercePlugin("https://store.example", "COMMERCE_API_KEY", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PluginConfigError):
        plugin.get_order(CallContext("req", "idempotency-key", MapSecrets({})), "../admin")


def test_byo_contract_refunds_and_quotes_through_the_merchant_adapter() -> None:
    reference = create_byo_app("provider-secret")

    class AppTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            from fastapi.testclient import TestClient

            self.client = TestClient(reference)

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower() not in {"host", "content-length"}
            }
            response = self.client.request(request.method, request.url.path, content=request.content, headers=headers)
            return httpx.Response(response.status_code, content=response.content)

    client = httpx.Client(transport=AppTransport(), base_url="http://testserver")
    secrets = MapSecrets({"PAYMENT_API_KEY": "provider-secret", "COMMERCE_API_KEY": "provider-secret"})
    payment = HttpPaymentPlugin("http://testserver", "PAYMENT_API_KEY", client)
    commerce = HttpCommercePlugin("http://testserver", "COMMERCE_API_KEY", client)
    agent = AgentApp(
        settings=Settings(auto_approve_below=Decimal("100")),
        secrets=secrets,
        payment=payment,
        commerce=commerce,
        approval=WebhookApproval(None),
        retriever=KeywordRetriever([POLICY]),
        clock=lambda: datetime.now(timezone.utc),
    )
    result = agent.handle(_refund(amount=Decimal("40.00")), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.COMPLETED
    assert reference.state.payments["pay_1001"]["refunded"] == Decimal("40.00")
    quote = agent.handle(UserRequest(message="Quote 80 USD in EUR"), Caller(scope=Scope.PUBLIC))
    assert quote.outcome is Outcome.COMPLETED
    assert "73.60" in quote.message


def test_stripe_refund_uses_the_merchant_key_without_putting_it_in_the_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert request.headers["Authorization"] == "Bearer sk_test_abc123"
        assert request.headers["Idempotency-Key"] == "refund-key-1001"
        assert "sk_test_abc123" not in body
        assert "amount=8000" in body
        assert "payment_intent=pi_123" in body
        return httpx.Response(200, json={"id": "re_123", "status": "succeeded"})

    plugin = StripePaymentPlugin("PAYMENT_API_KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    from ecommerce_agent.models import RefundRequest

    result = plugin.refund(
        CallContext("req", "refund-key-1001", MapSecrets({"PAYMENT_API_KEY": "sk_test_abc123"})),
        RefundRequest(payment_id="pi_123", order_id="1001", amount=Decimal("80.00"), currency="USD", reason="requested_by_customer"),
    )
    assert result.id == "re_123"
    assert to_minor(Decimal("80.00"), "USD") == 8000
    assert to_minor(Decimal("1000"), "JPY") == 1000


def test_shopify_refund_uses_the_shop_token_as_a_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Shopify-Access-Token"] == "shpat_secret"
        if request.url.path.endswith("/transactions.json"):
            return httpx.Response(200, json={"transactions": [{"id": 55, "kind": "sale", "status": "success", "amount": "80.00"}]})
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"refund": {"id": 9}})

    plugin = ShopifyPaymentPlugin(
        shop=None,
        secret_env="COMMERCE_API_KEY",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://demo.myshopify.com",
    )
    from ecommerce_agent.models import RefundRequest

    result = plugin.refund(
        CallContext("req", "refund-key-1001", MapSecrets({"COMMERCE_API_KEY": "shpat_secret"})),
        RefundRequest(payment_id="55", order_id="1001", amount=Decimal("80.00"), currency="USD", reason="requested_by_customer"),
    )
    assert result.id == "9"
    assert "shpat_secret" not in seen["body"]


def test_logs_and_langfuse_payloads_omit_secrets(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging()
    with caplog.at_level("INFO", logger="ecommerce_agent"):
        get_logger().info("header %s", "sk_test_abc123")
    assert "sk_test_abc123" not in caplog.text
    assert "REDACTED_SECRET" in caplog.text
    payload = langfuse_batch(
        __import__("ecommerce_agent.observability", fromlist=["SignalDraft"]).SignalDraft(request_id="req"),
        __import__("ecommerce_agent.models", fromlist=["AgentResult"]).AgentResult(
            request_id="req",
            intent=Intent.REFUND,
            outcome=Outcome.COMPLETED,
            message=f"hidden {PAN}",
        ),
        include_order_id=False,
        order_id="1001",
    )
    encoded = str(payload)
    assert PAN not in encoded
    assert "hidden" not in encoded
    assert "1001" not in encoded


def test_signal_summary_uses_the_five_signals() -> None:
    summary = summarize(
        [
            SignalRecord(10, 20, True, True, False, 2, 2, 0.8),
            SignalRecord(30, 40, False, False, True, 1, 0, 0.4),
        ]
    )
    assert summary["signals"]["fallback_success_rate"] == 1
    assert summary["signals"]["tool_call_success_rate"] == 2 / 3
    assert summary["signals"]["rate_limit_error_rate"] == 0.5
    assert summary["dimensions"]["performance"]["gpu_utilization"] is None
    assert summary["dimensions"]["user_experience"]["retrieval_quality"] == pytest.approx(0.6)


def test_refund_above_50_alerts_support_and_does_not_move_money() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(202, json={"ok": True})

    alert = SupportAlert("https://support.example/alerts", httpx.Client(transport=httpx.MockTransport(handler)))
    agent, payment, _commerce = _agent(
        approval=ThresholdApproval(Decimal("100")),
        support_alert=alert,
    )
    result = agent.handle(_refund(reason=f"broken {PAN}"), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.PENDING_APPROVAL
    assert "Support was alerted" in result.message
    assert "support_alert" in result.trace["nodes"]
    assert payment.calls == []
    assert PAN not in seen["body"]
    assert "80.00" in seen["body"]
    assert "[REDACTED_CARD]" in seen["body"]


def test_support_approval_allows_a_refund_above_50() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "support.example":
            return httpx.Response(202, json={"ok": True})
        return httpx.Response(200, json={"decision": "approved"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    agent, payment, _commerce = _agent(
        approval=WebhookApproval("https://approvals.example/refunds", client),
        support_alert=SupportAlert("https://support.example/alerts", client),
    )
    result = agent.handle(_refund(), Caller(scope=Scope.PUBLIC))
    assert result.outcome is Outcome.COMPLETED
    assert payment.calls == ["refund"]


def test_paystack_refund_uses_the_merchant_key_in_kobo() -> None:
    from ecommerce_agent.models import RefundRequest

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert request.headers["Authorization"] == "Bearer sk_paystack_test"
        assert "sk_paystack_test" not in body
        assert '"amount": 8000' in body or '"amount":8000' in body
        assert "pi_or_ref" in body
        return httpx.Response(200, json={"status": True, "data": {"id": 99, "status": "processed"}})

    plugin = PaystackPaymentPlugin("PAYMENT_API_KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = plugin.refund(
        CallContext("req", "refund-key-1001", MapSecrets({"PAYMENT_API_KEY": "sk_paystack_test"})),
        RefundRequest(payment_id="pi_or_ref", order_id="1001", amount=Decimal("80.00"), currency="USD", reason="requested_by_customer"),
    )
    assert result.id == "99"
    assert result.status == "succeeded"


def test_flutterwave_refund_and_quote_use_the_merchant_key() -> None:
    from ecommerce_agent.models import ConversionRequest, RefundRequest

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer flw_secret"
        assert "flw_secret" not in (request.content.decode() if request.content else "")
        if request.url.path.endswith("/refund"):
            return httpx.Response(200, json={"status": "success", "data": {"id": 7, "status": "completed"}})
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"rate": 0.92, "destination": {"amount": 73.6, "currency": "EUR"}},
            },
        )

    plugin = FlutterwavePaymentPlugin("PAYMENT_API_KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    secrets = MapSecrets({"PAYMENT_API_KEY": "flw_secret"})
    refund = plugin.refund(
        CallContext("req", "refund-key-1001", secrets),
        RefundRequest(payment_id="txn_1001", order_id="1001", amount=Decimal("80.00"), currency="NGN", reason="requested_by_customer"),
    )
    quote = plugin.quote_conversion(
        CallContext("req", "quote-key-1001", secrets),
        ConversionRequest(amount=Decimal("80.00"), from_currency="USD", to_currency="EUR"),
    )
    assert refund.id == "7"
    assert quote.converted_amount == Decimal("73.60")
    assert quote.provider == "flutterwave"


REFUND_RULES = PolicyDocument(
    id="refunds",
    title="Refund policy",
    text=(
        "You can return headphones and request a refund within 30 days.\n"
        "```rules\n"
        "return_window_days: 10\n"
        "partial_refunds: no\n"
        "non_refundable: gift card, final sale\n"
        "support_alert_above: 40.00\n"
        "```\n"
        "Shipping updates can arrive within 2 days.\n"
    ),
)
PAYMENT_RULES = PolicyDocument(
    id="payments",
    title="Payment policy",
    text=(
        "```rules\n"
        "currency_conversion: no\n"
        "accepted_currencies: NGN\n"
        "```\n"
    ),
)
FAQS = PolicyDocument(
    id="faqs",
    title="Store FAQs",
    text=(
        "### Do you store my card number?\n"
        "No. Card numbers stay at the payment provider checkout.\n"
        "### How does currency conversion work?\n"
        "A conversion quote comes from the payment provider and is not a completed payment.\n"
    ),
)


def test_refund_rules_block_non_refundable_partial_and_a_tighter_window() -> None:
    gift = Order.model_validate(
        {
            **_order(5, "40.00").model_dump(),
            "items": [{"sku": "gc-1", "name": "Gift card", "quantity": 1, "amount": "40.00"}],
        }
    )
    agent, payment, _commerce = _agent(order=gift, policies=[REFUND_RULES])
    denied = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert denied.outcome is Outcome.DENIED
    assert "non-refundable" in denied.message
    assert payment.calls == []

    agent, payment, _commerce = _agent(order=_order(5, "40.00"), policies=[REFUND_RULES])
    partial = agent.handle(_refund(amount="10.00"), Caller(scope=Scope.SERVER))
    assert partial.outcome is Outcome.DENIED
    assert "full refund" in partial.message
    assert payment.calls == []

    agent, payment, _commerce = _agent(order=_order(12, "40.00"), policies=[REFUND_RULES])
    late = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert late.outcome is Outcome.DENIED
    assert "10-day" in late.message
    assert payment.calls == []


def test_policy_support_line_can_be_stricter_than_the_setting() -> None:
    agent, payment, _commerce = _agent(order=_order(5, "45.00"), policies=[REFUND_RULES])
    result = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert result.outcome is Outcome.PENDING_APPROVAL
    assert "above 40.00" in result.message
    assert payment.calls == []


def test_payment_rules_block_a_disallowed_currency_and_conversion() -> None:
    agent, payment, _commerce = _agent(order=_order(5, "40.00"), policies=[PAYMENT_RULES, POLICY])
    refund = agent.handle(_refund(), Caller(scope=Scope.SERVER))
    assert refund.outcome is Outcome.DENIED
    assert "does not accept USD" in refund.message
    assert payment.calls == []

    quote = agent.handle(
        UserRequest(
            message="Quote 80 USD in EUR",
            intent=Intent.CONVERSION,
            amount="80.00",
            from_currency="USD",
            to_currency="EUR",
        ),
        Caller(scope=Scope.PUBLIC),
    )
    assert quote.outcome is Outcome.DENIED
    assert "does not offer currency conversion" in quote.message
    assert payment.calls == []


def test_faq_answer_comes_from_the_matching_question() -> None:
    agent, payment, _commerce = _agent(policies=[FAQS, POLICY])
    result = agent.handle(UserRequest(message="Do you store my card number?"), Caller(scope=Scope.PUBLIC))
    assert result.intent is Intent.CUSTOMER_SERVICE
    assert result.outcome is Outcome.COMPLETED
    assert "Card numbers stay at the payment provider checkout." in result.message
    assert payment.calls == []


def test_bundled_policies_include_refund_payment_and_faq_rules() -> None:
    from ecommerce_agent.retrieval import parse_policy_rules
    from ecommerce_agent.workflow import bundled_policies

    documents = bundled_policies()
    titles = {document.id for document in documents}
    assert {"refunds", "payments", "faqs"} <= titles
    rules = parse_policy_rules(documents)
    assert rules.return_window_days == 30
    assert rules.partial_refunds is True
    assert "gift card" in rules.non_refundable
    assert rules.support_alert_above == Decimal("50.00")
    assert rules.currency_conversion is True
    assert "USD" in rules.accepted_currencies and "EUR" in rules.accepted_currencies
