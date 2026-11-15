"""Remove card numbers, secrets, and similar values from text before it is used."""

from __future__ import annotations

import re

EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
CARD_CANDIDATE = re.compile(r"(?:\d[ -]?){13,19}")
SECRET = re.compile(
    r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]+\b"
    r"|\bshpat_[A-Za-z0-9]+\b"
    r"|\bFLWSECK[A-Za-z0-9_-]*\b"
    r"|\b(?:sk_test_|sk_live_)[A-Za-z0-9]+\b"
    r"|\b(?:whsec_|rk_live_|rk_test_)[A-Za-z0-9]+\b",
    re.IGNORECASE,
)
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]+=*")
CVV = re.compile(r"(?i)\b(?:cvv|cvc|cvn)\s*[:#-]?\s*\d{3,4}\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}(?!\w)")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")


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


def redact_phones(text: str) -> str:
    """Redact phone-like digit runs that are not card numbers (cards already handled)."""

    def _replace(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        # Avoid chewing short order ids or amounts; require a plausible phone length.
        if 10 <= len(digits) <= 15 and not (13 <= len(digits) <= 19 and luhn_ok(digits)):
            return "[REDACTED_PHONE]"
        return match.group()

    return PHONE.sub(_replace, text)


def redact(text: str) -> str:
    """Return text that is safe to put in a model prompt, log, or approval request."""

    cleaned = SECRET.sub("[REDACTED_SECRET]", text)
    cleaned = BEARER.sub("[REDACTED_SECRET]", cleaned)
    cleaned = CVV.sub("[REDACTED_CVV]", cleaned)
    cleaned = EMAIL.sub("[REDACTED_EMAIL]", cleaned)
    cleaned = IBAN.sub("[REDACTED_IBAN]", cleaned)
    cleaned = redact_cards(cleaned)
    return redact_phones(cleaned)
