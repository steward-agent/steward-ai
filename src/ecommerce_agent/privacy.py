"""Public data-protection, GDPR, PII, and payment notices, plus runtime PII guards.

These notices are served without auth so shoppers and reviewers can read them on the
merchant's agent URL. Merchants remain the controller for their shoppers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ecommerce_agent.redaction import CARD_CANDIDATE, CVV, EMAIL, IBAN, PHONE, SECRET, luhn_ok, redact

PRIVACY_VERSION = "2026-11-15"


@dataclass(frozen=True)
class PolicyPage:
    id: str
    title: str
    path: str
    summary: str
    sections: tuple[tuple[str, str], ...]


DATA_PROTECTION = PolicyPage(
    id="data-protection",
    title="Data protection",
    path="/data-protection",
    summary=(
        "Shopper messages stay in memory for the request. Payment keys stay on the merchant server. "
        "Card numbers stay with the payment provider. This deployment does not ship a shopper database."
    ),
    sections=(
        (
            "Roles",
            "The store that hosts this plugin is the controller for shopper data. "
            "Payment and commerce providers are processors under the store's contracts. "
            "Open-source maintainers do not operate a payment account for the store.",
        ),
        (
            "Where data lives",
            "Order and customer ids are read through the store's plugins for that request. "
            "Conversation text is not written to a built-in database. "
            "Provider secrets stay in environment variables or a secret manager.",
        ),
        (
            "Retention",
            "The store decides how long to keep transcripts and audit logs in its own systems "
            "and deletes or anonymizes them under its privacy notice.",
        ),
        (
            "Security controls",
            "Card numbers, CVV values, emails, and provider secrets in free text are redacted "
            "before models, tools, logs, approvals, or support alerts see them.",
        ),
    ),
)

GDPR = PolicyPage(
    id="gdpr",
    title="GDPR and similar privacy laws",
    path="/gdpr",
    summary=(
        "Shoppers exercise privacy rights with the store, not with the open-source maintainers. "
        "This page explains how the plugin maps to common GDPR duties."
    ),
    sections=(
        (
            "Lawful basis",
            "The store states the lawful basis in its own privacy notice. "
            "Support and returns usually rely on contract performance or legitimate interests.",
        ),
        (
            "Data subject rights",
            "Access, correction, erasure, restriction, and objection are handled in the store's "
            "commerce and support systems. This plugin does not keep a separate shopper profile store.",
        ),
        (
            "Processors",
            "Payment, commerce, approval, and support webhooks are chosen and contracted by the store.",
        ),
        (
            "Breach",
            "The store follows its incident process. Code vulnerabilities are reported under SECURITY.md.",
        ),
        (
            "Children",
            "Do not use this plugin to collect children's data without the store's lawful basis.",
        ),
    ),
)

PII = PolicyPage(
    id="pii",
    title="Personally identifiable information (PII)",
    path="/pii",
    summary=(
        "Stable customer and order ids are accepted. Emails, cards, CVV values, and secret tokens "
        "in free text are redacted. customer_ref must not be an email address."
    ),
    sections=(
        (
            "Accepted identifiers",
            "customer_ref and order_id are opaque ids. Email addresses are rejected as customer_ref.",
        ),
        (
            "Redacted in free text",
            "Emails become [REDACTED_EMAIL]. Phones become [REDACTED_PHONE]. "
            "Card numbers become [REDACTED_CARD]. CVV values become [REDACTED_CVV]. "
            "IBAN-like values become [REDACTED_IBAN]. Provider keys and Bearer tokens become [REDACTED_SECRET].",
        ),
        (
            "Logs and exports",
            "Application logs use a redacting filter. Optional observability export omits shopper free text, "
            "card data, and provider secrets. SLIs require the server token.",
        ),
        (
            "Widget",
            "The widget refuses card entry and sends a public token plus a short-lived HMAC shopper grant. "
            "The server token never appears in the page.",
        ),
    ),
)

PAYMENT_POLICY = PolicyPage(
    id="payment-policy",
    title="Payment policy",
    path="/payment-policy",
    summary=(
        "Bring your own payment provider. This plugin does not take cards, hold funds, or store PANs. "
        "Refunds and captures go through the provider the store already uses."
    ),
    sections=(
        (
            "Merchant of record",
            "The store (or its licensed merchant) remains merchant of record with its payment provider.",
        ),
        (
            "No card collection",
            "Shoppers enter cards on the provider checkout. Requests that contain a card number or CVV "
            "are blocked or redacted before money-moving tools run.",
        ),
        (
            "Refunds",
            "Refunds follow the store's return window, partial-refund rules, and support-alert threshold. "
            "Amounts above the alert line wait for the store's approval step.",
        ),
        (
            "Keys",
            "Provider secret keys stay in named environment variables on the store's server. "
            "They are never returned by the public API and are redacted from logs.",
        ),
        (
            "PCI",
            "This software does not replace the store's PCI DSS obligations with its payment provider.",
        ),
    ),
)

PRIVACY_PAGES: tuple[PolicyPage, ...] = (DATA_PROTECTION, GDPR, PII, PAYMENT_POLICY)


def privacy_index() -> dict[str, Any]:
    """Machine-readable index for `/v1/privacy` (no auth)."""
    return {
        "version": PRIVACY_VERSION,
        "controller": "merchant",
        "maintainer_role": "open_source_publisher",
        "holds_card_data": False,
        "holds_shopper_database": False,
        "redacts_pii_in_free_text": True,
        "pages": [
            {
                "id": page.id,
                "title": page.title,
                "path": page.path,
                "json_path": f"/v1/privacy/{page.id}",
                "summary": page.summary,
            }
            for page in PRIVACY_PAGES
        ],
    }


def page_payload(page: PolicyPage) -> dict[str, Any]:
    return {
        "version": PRIVACY_VERSION,
        "id": page.id,
        "title": page.title,
        "path": page.path,
        "summary": page.summary,
        "sections": [{"heading": heading, "body": body} for heading, body in page.sections],
        "related": [item.path for item in PRIVACY_PAGES if item.id != page.id],
    }


def get_page(page_id: str) -> PolicyPage | None:
    for page in PRIVACY_PAGES:
        if page.id == page_id:
            return page
    return None


def render_html(page: PolicyPage) -> str:
    sections = "".join(
        f"<section><h2>{_escape(heading)}</h2><p>{_escape(body)}</p></section>" for heading, body in page.sections
    )
    nav = " · ".join(f'<a href="{item.path}">{_escape(item.title)}</a>' for item in PRIVACY_PAGES)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{_escape(page.title)} · Store agent</title>
  <style>
    body {{ font: 1rem/1.5 system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; color: #1c1915; }}
    h1 {{ font-size: 1.75rem; }} h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
    .lede {{ color: #5c564c; }} nav {{ margin: 1rem 0 2rem; }} a {{ color: #1f4d3a; }}
    .fine {{ color: #8a8278; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <p class="fine">Public policy · version {_escape(PRIVACY_VERSION)}</p>
  <h1>{_escape(page.title)}</h1>
  <p class="lede">{_escape(page.summary)}</p>
  <nav aria-label="Privacy pages">{nav}</nav>
  {sections}
  <p class="fine">JSON: <a href="/v1/privacy/{page.id}">/v1/privacy/{page.id}</a> · Index: <a href="/v1/privacy">/v1/privacy</a></p>
</body>
</html>
"""


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def find_card_numbers(text: str) -> list[str]:
    found: list[str] = []
    for match in CARD_CANDIDATE.finditer(text):
        digits = "".join(character for character in match.group() if character.isdigit())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            found.append(digits)
    return found


def pii_findings(text: str) -> dict[str, bool]:
    """Report which PII categories appear in free text before redaction."""
    return {
        "card_number": bool(find_card_numbers(text)),
        "cvv": bool(CVV.search(text)),
        "email": bool(EMAIL.search(text)),
        "secret_token": bool(SECRET.search(text)),
        "phone": bool(PHONE.search(text)),
        "iban": bool(IBAN.search(text)),
    }


def contains_payment_instrument(text: str) -> bool:
    findings = pii_findings(text)
    return findings["card_number"] or findings["cvv"]


def sanitize_for_processing(text: str) -> str:
    """Redact PII so downstream models, tools, and logs never see raw values."""
    return redact(text)


def refuse_payment_instrument_message() -> str:
    return (
        "Do not type card numbers or security codes here. "
        "Pay on the store's payment provider checkout. No payment details were stored."
    )
