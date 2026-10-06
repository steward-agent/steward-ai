# Security

## Report a vulnerability

Open a private security advisory on the repository host, or email the maintainers if a private address is listed there. Please include the version, the request path, and whether money movement is involved. Give the maintainers time to release a fix before a public write-up.

Do not include live provider keys or card numbers in the report. A redacted request is enough.

## What this project protects

- Provider secrets stay in the merchant environment and are redacted if they appear in a log line.
- Card numbers and card verification values in free text are redacted before a model, a webhook, or a tool description sees the text.
- The public token cannot capture payments or create a converted payment.
- Shopper order access from the widget requires an HMAC signed by the server token, limited to 15 minutes.
- Order ids are rejected when they could change a URL path.
- Provider error bodies are not returned to the shopper.
- The language model is not given a tool handle.

## What you configure

- Different values for `PLUGIN_PUBLIC_TOKEN` and `PLUGIN_SERVER_TOKEN`.
- `DEMO` unset in production.
- `APPROVAL_PLUGIN=threshold` only when you intend small refunds to proceed without a person.
- An approval webhook that authenticates the caller and returns `approved` only for refunds you want sent.
- CORS origins listed explicitly. A wildcard is rejected.
- Network access so the process can reach only your payment adapter, your commerce adapter, and the approval webhook you set.

## Out of scope

This software does not replace your payment provider's PCI validation, your store login, or your fraud tools. The server token is powerful. Keep it on the backend.
