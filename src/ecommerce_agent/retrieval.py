"""Policy retrieval over documents the merchant supplies. No hosted vector database."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ecommerce_agent.models import PolicyDocument, PolicyHit
from ecommerce_agent.redaction import redact

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "for",
    "how",
    "i",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "you",
    "your",
}
TOKEN = re.compile(r"[a-z0-9]+")
POLICY_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_POLICY_CHARS = 100_000
WINDOW = re.compile(r"(\d+)\s*-?\s*days?")
RULES_FENCE = re.compile(r"```rules\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
YES = {"yes", "true", "allowed", "allow", "on"}
NO = {"no", "false", "denied", "deny", "off", "disabled"}


def tokens(text: str) -> set[str]:
    return {token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS and len(token) > 1}


def parse_return_window_days(text: str) -> int | None:
    match = WINDOW.search(text.lower())
    if not match:
        return None
    return int(match.group(1))


@dataclass(frozen=True)
class PolicyRules:
    """Rules parsed from merchant policy files. Missing fields stay unset."""

    return_window_days: int | None = None
    partial_refunds: bool | None = None
    non_refundable: tuple[str, ...] = ()
    support_alert_above: Decimal | None = None
    currency_conversion: bool | None = None
    accepted_currencies: tuple[str, ...] = ()


def parse_policy_rules(documents: list[PolicyDocument]) -> PolicyRules:
    window: int | None = None
    partial: bool | None = None
    blocked: list[str] = []
    alert: Decimal | None = None
    conversion: bool | None = None
    currencies: tuple[str, ...] | None = None
    for document in documents:
        for block in RULES_FENCE.findall(document.text):
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip().lower().replace(" ", "_")
                value = value.strip()
                if key == "return_window_days":
                    days = _positive_int(value)
                    if days is not None:
                        window = days if window is None else min(window, days)
                elif key == "partial_refunds":
                    flag = _yes_no(value)
                    if flag is not None:
                        partial = flag if partial is None else partial and flag
                elif key == "non_refundable":
                    blocked.extend(part for part in _csv(value) if len(part) >= 3)
                elif key == "support_alert_above":
                    amount = _money(value)
                    if amount is not None:
                        alert = amount if alert is None else min(alert, amount)
                elif key == "currency_conversion":
                    flag = _yes_no(value)
                    if flag is not None:
                        conversion = flag if conversion is None else conversion and flag
                elif key == "accepted_currencies":
                    found = tuple(part.upper() for part in _csv(value) if len(part) == 3 and part.isalpha())
                    if currencies is None:
                        currencies = found
                    else:
                        currencies = tuple(code for code in currencies if code in found)
    return PolicyRules(
        return_window_days=window,
        partial_refunds=partial,
        non_refundable=tuple(dict.fromkeys(term.lower() for term in blocked)),
        support_alert_above=alert,
        currency_conversion=conversion,
        accepted_currencies=currencies or (),
    )


def blocked_item_name(order_items: list, terms: tuple[str, ...]) -> str | None:
    if not terms:
        return None
    for item in order_items:
        haystack = f"{getattr(item, 'name', '')} {getattr(item, 'sku', '')}".lower()
        for term in terms:
            if term in haystack:
                return str(getattr(item, "name", term))
    return None


def _chunks(document: PolicyDocument) -> list[PolicyDocument]:
    prose = RULES_FENCE.sub("", document.text).strip()
    if not prose:
        return []
    pieces = re.split(r"(?m)^###\s+", prose)
    chunks: list[PolicyDocument] = []
    intro = pieces[0].strip()
    if intro:
        chunks.append(PolicyDocument(id=document.id, title=document.title, text=intro))
    for piece in pieces[1:]:
        question, _, answer = piece.partition("\n")
        body = f"{question.strip()}\n{answer.strip()}".strip()
        if body:
            chunks.append(PolicyDocument(id=document.id, title=question.strip() or document.title, text=body))
    return chunks


def _yes_no(value: str) -> bool | None:
    token = value.strip().lower()
    if token in YES:
        return True
    if token in NO:
        return False
    return None


def _positive_int(value: str) -> int | None:
    try:
        number = int(value)
    except ValueError:
        return None
    if number < 0:
        return None
    return number


def _money(value: str) -> Decimal | None:
    try:
        amount = Decimal(value)
    except Exception:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class KeywordRetriever:
    def __init__(self, documents: list[PolicyDocument]) -> None:
        self.documents = documents
        self.chunks = [chunk for document in documents for chunk in _chunks(document)]

    def search(self, query: str) -> PolicyHit | None:
        query_tokens = tokens(query)
        if not query_tokens or not self.chunks:
            return None
        best: PolicyHit | None = None
        for document in self.chunks:
            haystack = tokens(f"{document.title} {document.text}")
            score = len(query_tokens & haystack) / len(query_tokens)
            if best is None or score > best.score:
                excerpt = document.text.strip().replace("\n", " ")
                best = PolicyHit(
                    document_id=document.id,
                    title=document.title,
                    excerpt=excerpt[:400],
                    score=round(score, 4),
                )
        if best is None or best.score <= 0:
            return None
        return best


def save_org_policy(directory: Path, name: str, text: str) -> PolicyDocument:
    """Write one organization rule file. The name cannot leave the folder."""

    if not POLICY_NAME.fullmatch(name):
        raise ValueError("Policy name must use letters, numbers, _ and -.")
    if "\x00" in text or not text.strip():
        raise ValueError("Policy text is empty.")
    if len(text) > MAX_POLICY_CHARS:
        raise ValueError("Policy text is too long.")
    if redact(text) != text:
        raise ValueError("Organization rules cannot contain card numbers, emails, or provider secrets.")
    directory.mkdir(parents=True, exist_ok=True)
    root = directory.resolve()
    target = (directory / f"{name}.md").resolve()
    if target.parent != root:
        raise ValueError("Policy name cannot leave the organization rules folder.")
    target.write_text(text if text.endswith("\n") else f"{text}\n", encoding="utf-8")
    return PolicyDocument(id=name, title=name.replace("-", " ").title(), text=text)


def load_policy_dir(path: Path) -> list[PolicyDocument]:
    if not path.exists() or not path.is_dir():
        return []
    documents: list[PolicyDocument] = []
    for file in sorted(path.glob("*")):
        if file.suffix.lower() not in {".md", ".txt"} or not file.is_file():
            continue
        documents.append(PolicyDocument(id=file.stem, title=file.stem.replace("-", " ").title(), text=file.read_text()))
    return documents
