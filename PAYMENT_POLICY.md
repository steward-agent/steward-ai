# Payment policy

Public policy for anyone who evaluates or runs Ecommerce Agent.

This software does not take cards, hold funds, or store primary account numbers. The store connects the payment provider it already uses. That provider charges, refunds, settles, and quotes currency under the store's merchant agreement.

## Rules enforced in code

- Free-text card numbers and CVV values are detected and blocked before refund, conversion, or settlement tools run.
- Remaining PII in messages is redacted before models, logs, approvals, and support alerts.
- Provider secret keys stay in named environment variables and are never returned on public endpoints.
- The public token cannot capture payments or create a converted payment.

## Shopper-facing URLs on a running agent

| Page | Path |
| --- | --- |
| Index (JSON) | `/v1/privacy` |
| Payment policy | `/payment-policy` and `/v1/privacy/payment-policy` |
| Data protection | `/data-protection` |
| GDPR | `/gdpr` |
| PII | `/pii` |

These routes need no auth so shoppers and reviewers can open them.

## Related

- [DATA_PROTECTION.md](DATA_PROTECTION.md)
- [GDPR.md](GDPR.md)
- [PII.md](PII.md)
- [SECURITY.md](SECURITY.md)
- [TERMS.md](TERMS.md)
