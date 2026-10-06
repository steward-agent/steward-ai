# Contributing

Thank you for improving Ecommerce Agent. Contributions are licensed under the [MIT License](LICENSE). There is no contributor license agreement.

The [terms](TERMS.md) explain how a store may run the software. The [git strategy](docs/git-strategy.md) explains branches, commits, and releases.

## Set up

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Use Python 3.11 or newer.

## What we merge

- A bug fix with a test that failed before the fix.
- A payment or commerce plugin that talks to a provider the merchant already uses, with a mocked HTTP test.
- Documentation that makes the plugin boundary clearer.
- Observability that records the existing signals without storing shopper text.

## Safety checklist

Every change that touches payments, prompts, logs, or traces needs all of these:

- Provider secrets are read from the environment at call time and are not stored on settings, traces, or error messages.
- Card numbers and provider keys are redacted before text reaches a model, a log, or an approval webhook.
- A model cannot call a payment or commerce tool. Tools run in workflow code after guardrails.
- Money movement stays behind the server token or an explicit approval decision.
- Order ids and payment ids are validated before they are interpolated into a URL.
- Refunds, captures, and payment creation send an idempotency key.
- Tests cover the new path with a fake transport. Live provider keys are not required and must not be committed.

## Add a payment plugin

1. Implement `refund`, `quote_conversion`, `create_payment`, and `settlement` on a class in your package.
2. Register it with the entry point group `ecommerce_agent.payment_plugins`.
3. Read the merchant's secret from `CallContext.secrets` inside each call.
4. Honor `Idempotency-Key` on the provider request.
5. Raise `ToolError` with a fixed message. Do not attach the provider body if it may contain a customer record or a secret.
6. Add a `MockTransport` test that asserts the secret is a header and is absent from the body and the URL.

Commerce plugins use the group `ecommerce_agent.commerce_plugins` and the methods `get_order` and `record_return`. `record_return` records the return. The payment plugin is what moves the money, so a commerce plugin must not also refund unless it is explicitly the payment plugin.

If your provider is easier to wrap in a small service you already run, implement the [byo-v1 HTTP contract](docs/plugins.md) instead of an in-tree class.

## Commits and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add mollie payment plugin
fix: keep refunds pending when the approval webhook times out
docs: describe the byo-v1 capture call
```

Open the pull request against `main`. Fill in the checklist in the pull request template. Keep the change focused enough for one reviewer to follow.

## Secrets

Do not commit `.env` files, access tokens, or shopper exports. If a secret lands in a commit, rotate it at the provider. Rewriting git history on `main` is a maintainer action described in the git strategy, and it does not replace rotation.

## Conduct

Be direct and respectful. Harassment, personal attacks, and unwelcome sexual attention are not accepted. Reports can be opened as a private security or conduct issue with the maintainers. This project uses the [Contributor Covenant](CODE_OF_CONDUCT.md).
