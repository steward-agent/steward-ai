# Data protection

This document is public. Anyone who installs or evaluates Ecommerce Agent can read how store and shopper data is handled.

It is not legal advice. A merchant should align their own privacy notice with local law before going live.

## Roles

| Role | Who |
| --- | --- |
| Merchant (controller for shoppers) | The store that hosts the plugin |
| Processors | The payment provider, commerce platform, and optional approval or support webhooks the merchant configures |
| Project maintainers | Publish this open-source code. They do not operate a payment account for the store and do not receive live shopper payment data |

## Where data lives

- Shopper messages are handled in memory for that request. This project does not ship a shopper message database.
- Order and customer ids come from the merchant's commerce plugin for the duration of the request.
- Payment keys stay in the merchant's environment or secret manager.
- Card numbers stay on the payment provider's checkout. The widget and agent redact card numbers, CVV values, emails, and provider secrets before logs, models, approvals, or support alerts see the text.

## What the agent may read

For a signed-in return or support request: customer reference, order id, currency, refundable balance, return window signals, and the merchant's policy documents.

## What the agent must not receive

Card primary account numbers, CVV/CVC values, full bank account numbers, or live provider secret keys in free text. If those strings appear in a message, they are redacted.

## Retention

The merchant decides how long to keep transcripts, audit logs, and approval records in their own systems. Delete or anonymize shopper data under the merchant's privacy notice and legal duties.

## Cross-border transfers

The merchant chooses where the agent runs and which providers to call. Providers may process data in other regions under the merchant's contract with them.

## Related pages

- [GDPR](GDPR.md)
- [PII handling](PII.md)
- [Payment policy](PAYMENT_POLICY.md)
- [Privacy (website)](PRIVACY.md) for the product site contact form
- [Security](SECURITY.md)
- [Terms](TERMS.md)
