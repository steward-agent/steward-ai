# Changelog

Release prep copies each `feat` and `fix` squash subject from `main` into **Unreleased**, then renames that heading to the new version. See [Releases](docs/git-strategy.md#releases).

Entry format: `- <type>: <subject> (#<pull request>)`, grouped under **Added** for `feat` and **Fixed** for `fix`.

## Unreleased

### Added

- feat: accept the `Idempotency-Key` header on refund and message requests
- feat: return a `decision` code with every guardrail refusal
- feat: refund only the refundable lines of an order that also holds non-refundable items

### Fixed

- fix: make the Langfuse redaction test independent of random event ids

## 0.1.0

First open-source release.

- Customer questions from merchant-supplied policy documents.
- Refunds through the merchant's payment plugin, after guardrails and an optional approval step.
- Refunds above 50 in the order currency alert the merchant's support channel and wait.
- Refund rules, payment rules, and FAQs are checked before a refund or a conversion quote.
- Stripe, Paystack, Flutterwave, Shopify, and bring-your-own providers each use their own key variable. Key values are not returned by the API.
- Organization rules added under `POLICY_DIR` or uploaded with the server token are what the agent reads.
- Stripe, Paystack, and Flutterwave adapters, plus the bring-your-own HTTP contract for every other provider.
- Settlement reconcile and capture through the merchant's payment plugin.
- Currency quotes, and converted payment creation for the server token.
- Bring-your-own HTTP contract `byo-v1`, plus Stripe and Shopify adapters.
- Website widget that uses a public token and a short-lived server signature.
- In-memory SLIs for time to first reply, end-to-end latency, fallback recovery, rate limits, and tool-call success.
