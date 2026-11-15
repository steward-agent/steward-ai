# Personally identifiable information (PII)

How Ecommerce Agent treats personal data in requests, logs, and outbound calls. This page is public so reviewers and shoppers' advocates can see the controls.

## Categories

| Category | Examples | Treatment |
| --- | --- | --- |
| Identifiers | `customer_ref`, `order_id` | Accepted as stable ids. Email addresses are not valid as `customer_ref` |
| Contact in free text | Emails, phone numbers | `[REDACTED_EMAIL]`, `[REDACTED_PHONE]` before models, tools, logs, and webhooks |
| Payment | Card PAN, CVV, IBAN-like values | Redacted. Never stored by this plugin |
| Secrets | Stripe/Paystack/Flutterwave/Shopify keys, Bearer tokens | Redacted. Live values stay in env vars |
| Message body | Support text | Held in memory for the request; redacted before export |

## Redaction

`ecommerce_agent.redaction.redact` runs on shopper messages and reasons before routing, retrieval, approvals, support alerts, and logging. Organization policy files that contain cards, emails, or secrets are rejected at load time.

## Logs and observability

Application logs pass through a redacting filter. Optional Langfuse export omits shopper free text, card data, and provider secrets. SLI endpoints require the server token.

## Widget

The website widget refuses card entry. It sends a public token and a short-lived HMAC shopper grant signed by the server token. The server token never appears in the page.

## Merchant duties

- Publish a privacy notice that covers support chat and returns
- Prefer opaque customer ids over emails in `customer_ref`
- Keep transcripts only as long as the store's policy allows
- Restrict who can read server-token responses and SLIs

See also [DATA_PROTECTION.md](DATA_PROTECTION.md) and [GDPR.md](GDPR.md).
