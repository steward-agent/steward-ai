"""Intent routing. A model may classify support questions; money paths need keyword agreement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from ecommerce_agent.injection import MONEY_INTENTS, money_intent_allowed
from ecommerce_agent.models import Intent, UserRequest

REFUND = re.compile(r"\b(refund|return|money back)\b", re.IGNORECASE)
SETTLE = re.compile(r"\b(settle|settlement|payout|reconcile)\b", re.IGNORECASE)
CONVERT = re.compile(r"\b(convert|conversion|exchange|fx|quote)\b", re.IGNORECASE)
MONEY_PAIR = re.compile(
    r"(\d+(?:\.\d{1,2})?)\s*([A-Za-z]{3})\s+(?:to|in)\s+([A-Za-z]{3})",
    re.IGNORECASE,
)
ORDER_ID = re.compile(r"\border\s*#?\s*([A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)\b", re.IGNORECASE)
QUESTION = re.compile(r"\b(what|how|when|where|policy|policies|do you)\b", re.IGNORECASE)
ACTION = re.compile(r"\b(i want|i'd like|please|refund my|return my)\b", re.IGNORECASE)


@dataclass
class RouteDecision:
    intent: Intent
    fallback: bool
    strategy: str


def keyword_route(message: str) -> Intent:
    refund = bool(REFUND.search(message))
    settle = bool(SETTLE.search(message))
    convert = bool(CONVERT.search(message))
    question = bool(QUESTION.search(message))
    action = bool(ACTION.search(message))
    if refund and (action or not question):
        return Intent.REFUND
    if refund and question:
        return Intent.CUSTOMER_SERVICE
    if settle and not question:
        return Intent.SETTLEMENT
    if convert and (not question or MONEY_PAIR.search(message)):
        return Intent.CONVERSION
    return Intent.CUSTOMER_SERVICE


def enrich_user_request(request: UserRequest, message: str) -> UserRequest:
    """Fill structured fields from the shopper's words. The original text is not stored."""

    updates: dict = {}
    if request.order_id is None:
        found = ORDER_ID.search(message)
        if found:
            updates["order_id"] = found.group(1)
    pair = MONEY_PAIR.search(message)
    if pair:
        if request.amount is None:
            updates["amount"] = Decimal(pair.group(1))
        if request.from_currency is None:
            updates["from_currency"] = pair.group(2).upper()
        if request.to_currency is None:
            updates["to_currency"] = pair.group(3).upper()
    if not updates:
        return request
    return request.model_copy(update=updates)


class Router:
    def __init__(self, model: object | None = None) -> None:
        self.model = model

    def route(self, message: str, explicit: Intent | None = None) -> RouteDecision:
        # Explicit intents come from the merchant API (e.g. POST /v1/refunds), not from free text.
        if explicit is not None:
            return RouteDecision(intent=explicit, fallback=False, strategy="explicit")
        keywords = keyword_route(message)
        classify = getattr(self.model, "classify", None)
        if callable(classify):
            try:
                raw = classify(message)
                intent = raw if isinstance(raw, Intent) else Intent(str(raw))
                # Prompt injection that only fools the model cannot open a money path.
                if intent in MONEY_INTENTS and not money_intent_allowed(intent, keywords):
                    return RouteDecision(intent=keywords, fallback=True, strategy="keyword_over_model")
                # Shopper words that clearly ask to move money win over a model that refuses.
                if keywords in MONEY_INTENTS and intent not in MONEY_INTENTS:
                    return RouteDecision(intent=keywords, fallback=True, strategy="keyword_money")
                return RouteDecision(intent=intent, fallback=False, strategy="model")
            except Exception:
                return RouteDecision(intent=keywords, fallback=True, strategy="keyword_fallback")
        return RouteDecision(intent=keywords, fallback=False, strategy="keyword")
