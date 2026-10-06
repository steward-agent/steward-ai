# Plugins

You add the payment system and the commerce system you already use. This repository does not open a payment account for you.

## Choose a plugin

```bash
export PAYMENT_PLUGIN=http
export PAYMENT_BASE_URL=https://payments.yourstore.com
export PAYMENT_SECRET_ENV=PAYMENT_API_KEY
export PAYMENT_API_KEY=the-key-your-provider-gave-you

export COMMERCE_PLUGIN=http
export COMMERCE_BASE_URL=https://commerce.yourstore.com
export COMMERCE_SECRET_ENV=COMMERCE_API_KEY
export COMMERCE_API_KEY=the-key-your-store-uses
```

The `*_SECRET_ENV` values are names of variables. The keys themselves stay in the host environment.

| Your stack | `PAYMENT_PLUGIN` | `COMMERCE_PLUGIN` |
| --- | --- | --- |
| Your own provider behind a small adapter | `http` | `http` |
| Stripe for money, your platform for orders | `stripe` | `http` |
| Paystack for money, your platform for orders | `paystack` | `http` |
| Flutterwave for money and conversion quotes | `flutterwave` | `http` |
| Stripe for money, Shopify for orders | `stripe` | `shopify` |
| Shopify Payments for money and orders | `shopify` | `shopify` |

Set `PAYMENT_PLUGIN` to `stripe`, `paystack`, or `flutterwave` and put that provider's secret in its own variable: `STRIPE_SECRET_KEY`, `PAYSTACK_SECRET_KEY`, or `FLUTTERWAVE_SECRET_KEY`. Publishable keys (`STRIPE_PUBLISHABLE_KEY`, `PAYSTACK_PUBLIC_KEY`, `FLUTTERWAVE_PUBLIC_KEY`) stay available for your checkout page. This plugin does not send them on a refund. Paystack refunds a transaction reference and lists settlements. Flutterwave refunds a transaction id and quotes currency conversion from Flutterwave's rate API. Any provider without a built-in adapter uses `PAYMENT_PLUGIN=http` and `PAYMENT_API_KEY`.

Set `SHOPIFY_SHOP` to `your-store.myshopify.com` and `SHOPIFY_ADMIN_TOKEN` for the Shopify plugins. `GET /v1/keys` with the server token lists every key name and whether it is set. The response does not contain the key.

Stripe and Paystack do not quote currency conversion in these adapters. Flutterwave does. A store whose converter is a different system uses `PAYMENT_PLUGIN=http`.

## Refund rules, payment rules, and FAQs

Put your organization's Markdown files in `POLICY_DIR` (default `org_rules`). Each file can contain a `rules` block and `###` FAQ headings. The agent reads that folder on startup and again on each request, so a file you add there is picked up without a restart. You can also upload a file with the server token:

```bash
curl -X POST http://127.0.0.1:8000/v1/policies \
  -H "Authorization: Bearer $PLUGIN_SERVER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"org-refunds","text":"You can request a refund within 14 days.\nreturn_window_days: 14\n"}'
```

The website token cannot upload rules. A file that contains a card number or a provider secret is rejected. Demo mode loads the samples in `src/ecommerce_agent/policies/` (`refunds.md`, `payments.md`, and `faqs.md`) only while `POLICY_DIR` has no files.

The agent enforces `return_window_days`, `partial_refunds`, `non_refundable`, `support_alert_above`, `currency_conversion`, and `accepted_currencies`. A rule that is stricter than the matching environment setting wins. Customer match, currency match with the order, and the refusal to store card numbers stay on even when a file omits them.

Shopper questions are answered from the FAQ whose heading matches. A question about settlement or conversion, with no amount to quote, stays a question.

```rules
return_window_days: 30
partial_refunds: yes
non_refundable: gift card, digital download, final sale
support_alert_above: 50.00
currency_conversion: yes
accepted_currencies: USD, EUR, GBP, NGN
```

## Support alerts

A refund above `SUPPORT_ALERT_ABOVE` (default `50.00` in the order currency) is posted to `SUPPORT_ALERT_URL` and is not sent to the payment provider until `APPROVAL_WEBHOOK_URL` returns `{"decision": "approved"}`. The alert contains the order id, amount, currency, and a redacted reason. It does not contain card numbers or provider secrets.

## byo-v1 contract

Version: `byo-v1`.

Your adapter holds the provider SDK and the provider secret. Ecommerce Agent calls your adapter with a bearer token you issued for the agent. Amounts are decimal strings. Ids match `^[A-Za-z0-9_-]{1,64}$`.

Send `Idempotency-Key` through to the provider on refunds, captures, and payment creation. A repeated key returns the original result and does not move money again.

### `POST /v1/refunds`

```json
{
  "payment_id": "pay_1001",
  "order_id": "1001",
  "amount": "80.00",
  "currency": "USD",
  "reason": "requested_by_customer",
  "idempotency_key": "refund-1001-80"
}
```

```json
{ "id": "re_1", "status": "succeeded", "amount": "80.00", "currency": "USD" }
```

### `POST /v1/conversions/quote`

```json
{ "amount": "80.00", "from_currency": "USD", "to_currency": "EUR" }
```

```json
{
  "quote_id": "qx_1",
  "rate": "0.92",
  "amount": "80.00",
  "from_currency": "USD",
  "converted_amount": "73.60",
  "to_currency": "EUR",
  "fee": "0.00",
  "provider": "your-psp"
}
```

The quote is indicative. Creating a payment is a separate call.

### `POST /v1/payments`

```json
{
  "amount": "73.60",
  "currency": "EUR",
  "order_id": "1001",
  "customer_ref": "cust_1",
  "idempotency_key": "fx-1001"
}
```

```json
{ "id": "pay_new", "status": "requires_confirmation", "provider": "your-psp" }
```

Confirm the payment in your provider's checkout so card data goes to the provider.

### `GET /v1/settlements/unsettled`

```json
{
  "items": [
    {
      "payment_id": "pay_auth",
      "order_id": "1002",
      "amount": "20.00",
      "currency": "USD",
      "captured": false
    }
  ]
}
```

### `POST /v1/payments/{payment_id}/capture`

```json
{ "id": "pay_auth", "status": "succeeded", "captured": true }
```

### `GET /v1/orders/{order_id}`

```json
{
  "id": "1001",
  "customer_ref": "cust_1",
  "currency": "USD",
  "total": "80.00",
  "refundable": "80.00",
  "created_at": "2026-10-01T12:00:00+00:00",
  "payment_id": "pay_1001",
  "items": [
    { "sku": "hp-1", "name": "Headphones", "quantity": 1, "amount": "80.00" }
  ]
}
```

`customer_ref` is your stable customer id, not an email address.

### `POST /v1/returns`

This records a return. It does not move money.

```json
{ "order_id": "1001", "amount": "80.00", "currency": "USD", "reason": "requested_by_customer" }
```

```json
{ "id": "ret_1", "status": "recorded" }
```

`src/ecommerce_agent/reference.py` is an in-memory copy of this contract for local tests. Replace the ledger with your provider SDK before any real store uses it.

## Website widget

```html
<script src="https://your-agent.example/ecommerce-agent.js"></script>
<script>
  window.EcommerceAgent.mount({
    endpoint: "https://your-agent.example",
    publicToken: "PLUGIN_PUBLIC_TOKEN",
    customerRef: "cust_1",
    orderId: "1001",
    customerExpires: 1700000000,
    customerSignature: "hex hmac from your backend"
  });
</script>
```

Create the signature on the server after login:

```python
import time
from ecommerce_agent import sign_customer

expires = int(time.time()) + 600
signature = sign_customer(server_token, customer_ref, order_id, expires)
```

The signature covers that customer, that order, and that expiry. Expiry more than 15 minutes ahead is rejected.

## Register an external plugin

```toml
[project.entry-points."ecommerce_agent.payment_plugins"]
mollie = "your_package.mollie:MolliePaymentPlugin"
```

Set `PAYMENT_PLUGIN=mollie`. The class is constructed with no arguments today, so read configuration from the environment inside the class. A later minor release may pass `Settings` into external constructors; until then, keep the constructor empty.
