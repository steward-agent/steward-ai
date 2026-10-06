"""Five request signals and the five observability dimensions, kept in memory."""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


@dataclass
class SignalRecord:
    ttft_ms: float
    e2e_ms: float
    fallback_attempted: bool
    fallback_recovered: bool
    rate_limited: bool
    tool_calls: int
    tool_successes: int
    retrieval_score: float | None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    queue_depth: int = 0
    queue_wait_ms: float | None = None


@dataclass
class SignalDraft:
    request_id: str
    ttft_ms: float | None = None
    e2e_ms: float | None = None
    fallback_attempted: bool = False
    fallback_recovered: bool = False
    rate_limited: bool = False
    tool_calls: int = 0
    tool_successes: int = 0
    retrieval_score: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    queue_depth: int = 0
    queue_wait_ms: float | None = None
    nodes: list[str] = field(default_factory=list)

    def freeze(self) -> SignalRecord:
        return SignalRecord(
            ttft_ms=self.ttft_ms or 0,
            e2e_ms=self.e2e_ms or 0,
            fallback_attempted=self.fallback_attempted,
            fallback_recovered=self.fallback_recovered,
            rate_limited=self.rate_limited,
            tool_calls=self.tool_calls,
            tool_successes=self.tool_successes,
            retrieval_score=self.retrieval_score,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
            queue_depth=self.queue_depth,
            queue_wait_ms=self.queue_wait_ms,
        )


class Observability:
    """Process-local SLIs. Restarting the process clears them. Nothing here is a customer record."""

    def __init__(self, limit: int = 1000) -> None:
        self.limit = limit
        self._records: list[SignalRecord] = []
        self._lock = threading.Lock()

    def record(self, draft: SignalDraft) -> None:
        frozen = draft.freeze()
        with self._lock:
            self._records.append(frozen)
            if len(self._records) > self.limit:
                self._records = self._records[-self.limit :]

    def snapshot(self) -> dict:
        with self._lock:
            records = list(self._records)
        return summarize(records)


def _rate(part: int, whole: int) -> float | None:
    if whole == 0:
        return None
    return part / whole


def summarize(records: list[SignalRecord]) -> dict:
    fallback_attempts = sum(1 for item in records if item.fallback_attempted)
    fallback_recovered = sum(1 for item in records if item.fallback_attempted and item.fallback_recovered)
    tool_calls = sum(item.tool_calls for item in records)
    tool_successes = sum(item.tool_successes for item in records)
    scores = [item.retrieval_score for item in records if item.retrieval_score is not None]
    costs = [item.cost_usd for item in records if item.cost_usd is not None]
    token_rates = [
        item.output_tokens / (item.e2e_ms / 1000)
        for item in records
        if item.output_tokens and item.e2e_ms > 0
    ]
    waits = [item.queue_wait_ms for item in records if item.queue_wait_ms is not None]
    return {
        "requests": len(records),
        "definitions": {
            "ttft": "Request to first visible reply text.",
            "end_to_end_latency": "Request to completed answer.",
            "fallback_success": "Router or return planner recovered after a failed primary attempt.",
            "rate_limit_errors": "Gateway or provider returned a quota error (HTTP 429, RPM/TPM).",
            "tool_call_success": "Planner call to the commerce or payment plugin completed.",
        },
        "signals": {
            "ttft_ms_p95": percentile([item.ttft_ms for item in records], 95),
            "end_to_end_latency_ms_p95": percentile([item.e2e_ms for item in records], 95),
            "fallback_success_rate": _rate(fallback_recovered, fallback_attempts),
            "rate_limit_error_rate": _rate(sum(1 for item in records if item.rate_limited), len(records)),
            "tool_call_success_rate": _rate(tool_successes, tool_calls),
        },
        "dimensions": {
            "latency": {
                "ttft_ms_p95": percentile([item.ttft_ms for item in records], 95),
                "end_to_end_latency_ms_p95": percentile([item.e2e_ms for item in records], 95),
                "queue_depth_last": records[-1].queue_depth if records else 0,
                "queue_wait_ms_p95": percentile(waits, 95),
            },
            "reliability": {
                "fallback_success_rate": _rate(fallback_recovered, fallback_attempts),
                "rate_limit_error_rate": _rate(sum(1 for item in records if item.rate_limited), len(records)),
                "tool_call_success_rate": _rate(tool_successes, tool_calls),
            },
            "performance": {
                "tokens_per_second": sum(token_rates) / len(token_rates) if token_rates else None,
                "gpu_utilization": None,
                "memory_bandwidth": None,
            },
            "cost": {
                "cost_per_request_usd": (sum(costs) / len(records)) if records and costs else None,
                "requests_with_token_cost": len(costs),
            },
            "user_experience": {
                "retrieval_quality": (sum(scores) / len(scores)) if scores else None,
            },
        },
    }


def new_request_id() -> str:
    return uuid.uuid4().hex
