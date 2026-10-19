## Why

## What changed

## Safety

See the safety checklist in `CONTRIBUTING.md`.

- [ ] Provider secrets are read from the environment at call time and are not stored on settings, traces, or error messages
- [ ] Card numbers and provider keys are redacted before text reaches a model, a log, or an approval webhook
- [ ] A model cannot call a payment or commerce tool
- [ ] Money movement stays behind the server token or an explicit approval decision
- [ ] Order ids and payment ids are validated before they are interpolated into a URL
- [ ] Refunds, captures, and payment creation send an idempotency key
- [ ] New provider calls have a mocked HTTP test; no live keys are committed
- [ ] Docs and the changelog are updated when behavior changes

## How to test
