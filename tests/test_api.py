"""HTTP API tests for the website plugin."""

from __future__ import annotations

import time
from decimal import Decimal

from fastapi.testclient import TestClient

from ecommerce_agent.api import create_api
from ecommerce_agent.gateway import Gateway, sign_customer
from ecommerce_agent.secrets import MapSecrets
from ecommerce_agent.settings import Settings
from ecommerce_agent.workflow import build_agent

PUBLIC = "public-token-value"
SERVER = "server-token-value"


def _client(rpm: int = 60, demo: bool = True) -> tuple[TestClient, object]:
    settings = Settings(demo=demo, approval_plugin="threshold", auto_approve_below=Decimal("100"), rate_limit_rpm=rpm)
    secrets = MapSecrets({"PLUGIN_PUBLIC_TOKEN": PUBLIC, "PLUGIN_SERVER_TOKEN": SERVER})
    agent = build_agent(settings, secrets=secrets)
    return TestClient(create_api(agent, Gateway(settings, secrets))), agent


def test_health_and_widget_script() -> None:
    client, _agent = _client()
    assert client.get("/health").json()["status"] == "ok"
    script = client.get("/ecommerce-agent.js")
    assert script.status_code == 200
    assert "EcommerceAgent" in script.text
    assert SERVER not in script.text


def test_demo_page_is_off_unless_demo_mode_is_on() -> None:
    client, _agent = _client(demo=False)
    assert client.get("/demo").status_code == 404
    demo_client, _agent = _client(demo=True)
    page = demo_client.get("/demo")
    assert page.status_code == 200
    assert "Headphones" in page.text
    assert "customerSignature" in page.text
    assert SERVER not in page.text


def test_missing_token_is_unauthorized() -> None:
    client, _agent = _client()
    response = client.post("/v1/messages", json={"message": "hello"})
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_public_widget_return_above_50_alerts_support() -> None:
    client, agent = _client()
    expires = int(time.time()) + 600
    signature = sign_customer(SERVER, "cust_1", "1001", expires)
    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {PUBLIC}"},
        json={
            "message": "I want to return my headphones",
            "customer_ref": "cust_1",
            "order_id": "1001",
            "customer_signature": signature,
            "customer_expires": expires,
            "idempotency_key": "widget-return-1001",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "pending_approval"
    assert "trace" not in body
    assert "above 50.00" in body["message"]
    assert "No refund was sent" in body["message"]
    assert agent.payment.payments["pay_1001"]["refunded"] == Decimal("0")


def test_server_trace_is_visible_and_slis_require_the_server_token() -> None:
    client, _agent = _client()
    public = client.get("/v1/slis", headers={"Authorization": f"Bearer {PUBLIC}"})
    assert public.status_code == 403
    denied = client.post(
        "/v1/settlements",
        headers={"Authorization": f"Bearer {PUBLIC}"},
        json={"mode": "reconcile"},
    )
    assert denied.status_code == 403
    allowed = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {SERVER}"},
        json={"message": "What is your return policy?"},
    )
    assert allowed.status_code == 200
    assert "trace" in allowed.json()
    slis = client.get("/v1/slis", headers={"Authorization": f"Bearer {SERVER}"})
    assert slis.status_code == 200
    assert "tool_call_success_rate" in slis.json()["signals"]


def test_callers_cannot_set_their_own_scope() -> None:
    client, _agent = _client()
    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {PUBLIC}"},
        json={"message": "hello", "scope": "server"},
    )
    assert response.status_code == 422


def test_rate_limit_is_a_429() -> None:
    client, _agent = _client(rpm=1)
    headers = {"Authorization": f"Bearer {PUBLIC}"}
    first = client.post("/v1/messages", headers=headers, json={"message": "What is your return policy?"})
    second = client.post("/v1/messages", headers=headers, json={"message": "What is your return policy?"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "1"


def test_provider_keys_report_names_without_values() -> None:
    settings = Settings(demo=True, payment_plugin="stripe", approval_plugin="threshold", policy_dir="")
    secrets = MapSecrets(
        {
            "PLUGIN_PUBLIC_TOKEN": PUBLIC,
            "PLUGIN_SERVER_TOKEN": SERVER,
            "STRIPE_SECRET_KEY": "sk_test_abc123",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_abc123",
            "PAYSTACK_SECRET_KEY": "sk_paystack_hidden",
            "FLUTTERWAVE_SECRET_KEY": "flw_hidden",
            "SHOPIFY_ADMIN_TOKEN": "shpat_hidden",
        }
    )
    client = TestClient(create_api(build_agent(settings, secrets=secrets), Gateway(settings, secrets)))
    hidden = client.get("/v1/keys", headers={"Authorization": f"Bearer {PUBLIC}"})
    assert hidden.status_code == 403
    listed = client.get("/v1/keys", headers={"Authorization": f"Bearer {SERVER}"})
    assert listed.status_code == 200
    assert "sk_test_abc123" not in listed.text
    assert "pk_test_abc123" not in listed.text
    assert "sk_paystack_hidden" not in listed.text
    assert "flw_hidden" not in listed.text
    assert "shpat_hidden" not in listed.text
    body = listed.json()
    assert body["active_payment_key"] == "STRIPE_SECRET_KEY"
    configured = {item["provider"]: item for item in body["keys"]}
    assert configured["stripe"]["configured"] is True
    assert configured["stripe_publishable"]["configured"] is True
    assert configured["paystack"]["configured"] is True
    assert configured["flutterwave"]["env"] == "FLUTTERWAVE_SECRET_KEY"
    assert configured["shopify"]["env"] == "SHOPIFY_ADMIN_TOKEN"
    assert configured["http"]["env"] == "PAYMENT_API_KEY"
    assert configured["http"]["configured"] is False


def test_uploaded_and_added_org_rules_are_what_the_agent_reads(tmp_path) -> None:
    settings = Settings(demo=True, approval_plugin="threshold", policy_dir=str(tmp_path))
    secrets = MapSecrets({"PLUGIN_PUBLIC_TOKEN": PUBLIC, "PLUGIN_SERVER_TOKEN": SERVER})
    agent = build_agent(settings, secrets=secrets)
    client = TestClient(create_api(agent, Gateway(settings, secrets)))
    server = {"Authorization": f"Bearer {SERVER}"}
    public = {"Authorization": f"Bearer {PUBLIC}"}
    org_rules = (
        "You can return headphones and request a refund within 7 days.\n"
        "### How long do I have to return an item?\n"
        "The organization allows a refund within 7 days.\n"
        "```rules\n"
        "return_window_days: 7\n"
        "partial_refunds: yes\n"
        "support_alert_above: 50.00\n"
        "```\n"
    )
    blocked = client.post("/v1/policies", headers=public, json={"name": "org-refunds", "text": org_rules})
    assert blocked.status_code == 403
    uploaded = client.post("/v1/policies", headers=server, json={"name": "org-refunds", "text": org_rules})
    assert uploaded.status_code == 200
    assert uploaded.json()["id"] == "org-refunds"
    assert (tmp_path / "org-refunds.md").is_file()
    asked = client.post( "/v1/messages", headers=public, json={"message": "How long do I have to return an item?"})
    assert asked.status_code == 200
    assert "within 7 days" in asked.json()["message"]
    leaked = client.post(
        "/v1/policies",
        headers=server,
        json={"name": "secrets", "text": "Use key sk_test_abc123 for refunds."},
    )
    assert leaked.status_code == 422
    assert not (tmp_path / "secrets.md").exists()
    (tmp_path / "desk-rules.md").write_text(
        "### Where does the refund go?\nOrganization refunds go back to the original payment.\n",
        encoding="utf-8",
    )
    added = client.post("/v1/messages", headers=public, json={"message": "Where does the refund go?"})
    assert "Organization refunds go back to the original payment." in added.json()["message"]
    listed = client.get("/v1/policies", headers=server)
    assert listed.status_code == 200
    assert {"org-refunds", "desk-rules"} <= {item["id"] for item in listed.json()["documents"]}


def test_conversion_quote_endpoint() -> None:
    client, agent = _client()
    before = set(agent.payment.payments)
    response = client.post(
        "/v1/conversions/quote",
        headers={"Authorization": f"Bearer {PUBLIC}"},
        json={"amount": "80.00", "from_currency": "USD", "to_currency": "EUR"},
    )
    assert response.status_code == 200
    assert "73.60" in response.json()["message"]
    execute = client.post(
        "/v1/conversions/quote",
        headers={"Authorization": f"Bearer {PUBLIC}"},
        json={"amount": "80.00", "from_currency": "USD", "to_currency": "EUR", "execute": True},
    )
    assert execute.status_code == 403
    assert set(agent.payment.payments) == before
