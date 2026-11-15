"""Stop prompt and tool injection from steering money movement.

The language model never receives payment or commerce tool handles. This module
adds a second line of defense: untrusted shopper text cannot look like system
or tool instructions, and model classification alone cannot authorize a refund,
settlement, or conversion.
"""

from __future__ import annotations

import re

from ecommerce_agent.models import Intent

MONEY_INTENTS = frozenset({Intent.REFUND, Intent.SETTLEMENT, Intent.CONVERSION})

# Phrases that try to override the agent, the model, or a tool. Matched case-insensitively.
_INJECTION = re.compile(
    r"("
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?|prompts?)"
    r"|disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?)"
    r"|system\s*:\s*"
    r"|<\s*/?\s*system\s*>"
    r"|you\s+are\s+now\s+(?:a|an|the)\b"
    r"|new\s+instructions?\s*:"
    r"|override\s+(?:the\s+)?(?:policy|guardrails?|approval)"
    r"|call\s+the\s+(?:payment|refund|commerce)\s+tool"
    r"|tool\s*call\s*:"
    r"|assistant\s*:\s*approved"
    r")",
    re.IGNORECASE,
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_untrusted_text(text: str) -> str:
    """Remove control characters and neutralize common injection markers in shopper text."""
    cleaned = _CONTROL.sub(" ", text)
    cleaned = _INJECTION.sub("[REDACTED_INJECTION]", cleaned)
    return cleaned


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


def money_intent_allowed(model_intent: Intent, keyword_intent: Intent) -> bool:
    """A model may not open a money path unless the keyword router agrees.

    Prompt injection that only fools the classifier cannot start a refund.
    Structured API calls still pass an explicit intent and skip this check.
    """
    if model_intent not in MONEY_INTENTS:
        return True
    return model_intent == keyword_intent
