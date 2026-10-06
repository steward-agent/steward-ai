# Observability

The plugin records five signals on each request and rolls them into five dimensions. The rollup lives in process memory, capped at the last 1,000 requests. Restarting the process clears it. It is not a shopper database.

`GET /v1/slis` with the server token returns the current rollup.

## Signals

| Signal | Definition | Suggested SLO |
| --- | --- | --- |
| Time to first reply | Request start until the shopper-visible text is ready | p95 under 800 ms for policy answers |
| End-to-end latency | Request start until the completed answer | p95 under 8 s when a provider call is required |
| Fallback success | The router or a tool retry recovered after the primary attempt failed | At least 99% of fallback attempts |
| Rate-limit errors | The gateway or a provider returned a quota error (HTTP 429) | Alert on a rising rate. This is capacity, not a refund result |
| Tool-call success | A commerce or payment call completed | At least 99.5% of tool calls |

A tool success rate is omitted when the process has not made a tool call. A fallback rate is omitted when nothing has fallen back. Empty traffic is not reported as 100% success.

## Dimensions

| Dimension | What is recorded |
| --- | --- |
| Latency | p95 time to first reply, p95 end-to-end latency, last in-flight depth, p95 queue wait when the caller supplies `queue_wait_ms` |
| Reliability | Fallback success, rate-limit error rate, tool-call success |
| Performance | Output tokens per second when a model reports token counts. GPU utilization and memory bandwidth stay unset unless a model host you connect reports them |
| Cost | Cost per request when you set `USD_PER_MILLION_INPUT_TOKENS` and `USD_PER_MILLION_OUTPUT_TOKENS` |
| User experience | Average policy-retrieval score |

The plugin does not invent GPU or bandwidth numbers.

## Tracing

Node names follow the workflow: `gateway`, `router`, `qa`, `return_planner`, `retriever`, `guardrails`, `human_approval`, `commerce_tool`, `payment_tool`, `settlement`, `conversion`.

Server-token responses include those names and the timings. Public responses omit the trace.

Langfuse export is off unless `LANGFUSE_HOST` is set. The batch then contains intent, outcome, node names, and timings. It omits the shopper message, the customer id, and provider secrets. Set `TRACE_ORDER_IDS=1` only if your Langfuse project should store order ids. An export failure is logged as `observability_export_failed` and does not change the shopper's refund result.

LangSmith and other collectors are optional and are not required to run the plugin.
