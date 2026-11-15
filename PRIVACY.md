# Privacy

Public privacy overview for Ecommerce Agent and the product website.

## Running agent (shoppers and auditors)

Every deployment serves these pages without a token:

- `/v1/privacy` — machine-readable index
- `/data-protection` — where data lives and retention
- `/gdpr` — GDPR-oriented duties for the store
- `/pii` — how identifiers and free-text PII are handled
- `/payment-policy` — bring-your-own payments, no card collection

JSON copies live under `/v1/privacy/{id}`.

## Product website

The Steward marketing site publishes matching legal pages for visitors who are not hitting a store's agent URL. Contact-form messages on that site are covered there; store shoppers follow the store's privacy notice plus the agent pages above.

## Code

Runtime controls live in `src/ecommerce_agent/privacy.py` and `src/ecommerce_agent/redaction.py`, wired through the gateway workflow and public FastAPI routes.
