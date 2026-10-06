# Architecture

Ecommerce Agent is a library and a small HTTP API that a merchant runs beside their store. It is not a payment service and it is not multi-tenant.

## Invariants

1. The merchant's payment provider moves money.
2. The merchant's commerce system is the source of orders and return records.
3. Provider secrets are read from the merchant environment at call time. Stripe, Paystack, Flutterwave, Shopify, and any other provider each have their own variable name.
4. Card numbers are redacted and are not forwarded.
5. The language model cannot call payment or commerce tools.
6. Public widget credentials cannot capture funds or create a payment. A refund from the widget runs only after the merchant's approval step allows that request.
7. Order and payment ids are validated before they are placed in a URL.
8. The process does not keep a shopper database. Metrics are an in-memory ring of timings and counts.

## Request path

1. **Gateway.** The bearer token is either the public website token or the server token. The two values must differ. A token bucket limits each scope. Free text is redacted.
2. **Router.** An optional model may classify the turn. If it fails, keyword routing recovers and the fallback signal is recorded. An explicit API intent skips classification.
3. **Q&A.** Policy documents the merchant supplied are searched locally. The answer quotes that text. Optional model phrasing sees only the redacted question and the excerpt.
4. **Return planner.** The commerce plugin loads the order. Guardrails check the customer, the currency, the refundable balance, the stricter return window, non-refundable items, whether a partial refund is allowed, and the accepted currencies in the organization rules. Those rules are the Markdown files in `POLICY_DIR`, including files uploaded with the server token. FAQs in those same files answer shopper questions.
5. **Approval.** A server caller under the auto-approve limit, with a grounded policy, can refund without a person when the amount is at or under the support alert line. Every other allowed refund waits for the approval plugin. `webhook` with no URL leaves the refund pending. `threshold` approves amounts at or under the merchant's limit and at or under the support alert line. Pending and denied decisions do not call the payment plugin.
6. **Support alert.** A refund above `SUPPORT_ALERT_ABOVE` (50.00 in the order currency by default) posts a redacted alert to `SUPPORT_ALERT_URL` and waits. The server fast path and the threshold approver do not send that refund. An approval webhook that returns `approved` is support allowing it.
7. **Tools.** The commerce plugin records the return first. The payment plugin refunds only after that record succeeds. Both calls receive the same idempotency key.
8. **Settlement.** Server token only. `reconcile` reports unsettled authorizations and payouts. `capture` captures authorizations at the payment provider, one idempotency key per payment.
9. **Conversion.** A quote is safe for the public token. Creating the converted payment requires the server token. The provider returns the payment id. Card confirmation stays in the provider's checkout.

## Plugins

Built-in payment plugins are `mock`, `http`, `stripe`, `paystack`, `flutterwave`, and `shopify`. Built-in commerce plugins are `mock`, `http`, and `shopify`. Packages can register more through entry points:

- `ecommerce_agent.payment_plugins`
- `ecommerce_agent.commerce_plugins`

`http` speaks the byo-v1 contract in [plugins.md](plugins.md). That is how a store adds a provider this repository does not ship.

Shopify commerce records a return note and tags. Shopify payments, when selected as the payment plugin, sends the refund transaction. Using Shopify for both does not refund twice, because the commerce call does not create a refund transaction.

## Tokens

| Token | Where it lives | What it can do |
| --- | --- | --- |
| `PLUGIN_PUBLIC_TOKEN` | Website | Questions, quotes, and return requests |
| `PLUGIN_SERVER_TOKEN` | Store backend | Refunds under the limit, settlement, creating a converted payment, SLIs |

A signed shopper grant is `HMAC(server token, customer_ref:order_id:expires)`. It lasts at most 15 minutes. The widget sends the signature. It does not receive the server token.

## Demo mode

`DEMO=1` seeds one headphones order and loads the sample policies. It logs a warning. Leave it off in production.
