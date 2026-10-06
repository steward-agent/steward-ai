"""Remove card numbers, secrets, and similar values from text before it is used."""

from __future__ import annotations

import re

EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
CARD_CANDIDATE = re.compile(r"(?:\d[ -]?){13,19}")
SECRET = re.compile(
    r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+\b|\bshpat_[A-Za-z0-9]+\b",
    re.IGNORECASE,
)
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]+=*")
CVV = re.compile(r"(?i)\b(?:cvv|cvc|cvn)\s*[:#-]?\s*\d{3,4}\b")


def luhn_ok(number: str) -> bool:
    total = 0
    for index, character in enumerate(reversed(number)):
        digit = int(character)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_cards(text: str) -> str:
    matches = list(CARD_CANDIDATE.finditer(text))
    for match in reversed(matches):
        digits = re.sub(r"[ -]", "", match.group())
        if digits.isdigit() and 13 <= len(digits) <= 19 and luhn_ok(digits):
            text = f"{text[: match.start()]}[REDACTED_CARD]{text[match.end() :]}"
    return text


def redact(text: str) -> str:
    """Return text that is safe to put in a model prompt, log, or approval request."""

    cleaned = SECRET.sub("[REDACTED_SECRET]", text)
    cleaned = BEARER.sub("[REDACTED_SECRET]", cleaned)
    cleaned = CVV.sub("[REDACTED_CVV]", cleaned)
    cleaned = EMAIL.sub("[REDACTED_EMAIL]", cleaned)
    return redact_cards(cleaned)
