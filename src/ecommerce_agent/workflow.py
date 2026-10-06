"""Agent workflow for support, refunds, settlement, and payment conversion."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

import httpx

from ecommerce_agent.errors import PluginConfigError, ToolError
from ecommerce_agent.gateway import check_currency, check_id, check_idempotency_key
from ecommerce_agent.logging import get_logger
from ecommerce_agent.models import (
    ActionRecord,
    AgentResult,
    ApprovalRequest,
    Caller,
    ConversionRequest,
    CreatePaymentRequest,
    Intent,
    Order,
    Outcome,
    PolicyDocument,
    RefundRequest,
    ReturnRequest,
    Scope,
    UserRequest,
)
from ecommerce_agent.observability import Observability, SignalDraft
from ecommerce_agent.plugins.approval import WebhookApproval
from ecommerce_agent.plugins.commerce import MockCommercePlugin
from ecommerce_agent.plugins.http_client import CallContext
from ecommerce_agent.plugins.payments import MockPaymentPlugin
from ecommerce_agent.plugins.registry import create_approval, create_commerce, create_payment
from ecommerce_agent.plugins.support_alert import SupportAlert
from ecommerce_agent.redaction import redact
from ecommerce_agent.retrieval import (
    KeywordRetriever,
    blocked_item_name,
    load_policy_dir,
    parse_policy_rules,
    parse_return_window_days,
    save_org_policy,
)
from ecommerce_agent.routing import Router, enrich_user_request
from ecommerce_agent.secrets import SecretSource
from ecommerce_agent.settings import Settings

logger = get_logger()
CARD_WARNING = " Card numbers and provider secrets are not accepted here. Use your payment provider's checkout."


class AgentApp:
    def __init__(
        self,
        settings: Settings,
        secrets: SecretSource,
        payment,
        commerce,
        approval,
        retriever: KeywordRetriever,
        observability: Observability | None = None,
        model: object | None = None,
        clock: Callable[[], datetime] | None = None,
        exporter: object | None = None,
        support_alert: SupportAlert | None = None,
    ) -> None:
        self.settings = settings
        self.secrets = secrets
        self.payment = payment
        self.commerce = commerce
        self.approval = approval
        self.retriever = retriever
        self.observability = observability or Observability()
        self.model = model
        self.router = Router(model)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.exporter = exporter
        self.support_alert = support_alert or SupportAlert(None)
        self.rules = parse_policy_rules(retriever.documents)
        self.policy_directory = Path(settings.policy_dir) if settings.policy_dir else Path("org_rules")
        self._in_flight = 0
        self._lock = threading.Lock()

    def handle(self, request: UserRequest, caller: Caller) -> AgentResult:
        started = time.perf_counter()
        draft = SignalDraft(request_id=uuid.uuid4().hex)
        draft.queue_wait_ms = request.queue_wait_ms
        with self._lock:
            self._in_flight += 1
            draft.queue_depth = self._in_flight
        draft.nodes.append("gateway")
        self.refresh_policies()
        try:
            redacted = redact(request.message)
            reason = redact(request.reason)
            try:
                request = enrich_user_request(request, redacted)
            except ValueError:
                result = self._result(
                    draft,
                    Intent.CONVERSION,
                    Outcome.NEEDS_DETAILS,
                    "Send a positive amount as a string, such as 80.00, plus the two currency codes. No payment was created.",
                    None,
                )
                self._finish(draft, result)
                return result.model_copy(update={"trace": self._trace(draft, result)})
            saw_sensitive = any(
                token in redacted or token in reason
                for token in ("REDACTED_CARD", "REDACTED_SECRET", "REDACTED_CVV")
            )
            route = self.router.route(redacted, explicit=request.intent)
            draft.nodes.append("router")
            if route.fallback:
                draft.fallback_attempted = True
            if route.intent == Intent.REFUND:
                result = self._refund(request, caller, redacted, reason, draft)
            elif route.intent == Intent.SETTLEMENT:
                result = self._settlement(request, caller, draft)
            elif route.intent == Intent.CONVERSION:
                result = self._conversion(request, caller, draft)
            else:
                result = self._support(request, caller, redacted, draft)
            if route.fallback and result.outcome != Outcome.FAILED:
                draft.fallback_recovered = True
            if saw_sensitive:
                result = result.model_copy(update={"message": result.message + CARD_WARNING})
            first_text = time.perf_counter()
            draft.ttft_ms = (first_text - started) * 1000
            draft.e2e_ms = draft.ttft_ms
            self._finish(draft, result)
            return result.model_copy(update={"trace": self._trace(draft, result)})
        except PluginConfigError as exc:
            result = self._result(draft, Intent.CUSTOMER_SERVICE, Outcome.FAILED, str(exc), None)
            self._finish(draft, result)
            return result.model_copy(update={"trace": self._trace(draft, result)})
        finally:
            with self._lock:
                self._in_flight -= 1

    def _finish(self, draft: SignalDraft, result: AgentResult) -> None:
        self.observability.record(draft)
        logger.info(
            "request_completed request_id=%s intent=%s outcome=%s",
            result.request_id,
            result.intent.value,
            result.outcome.value,
        )
        if self.exporter is None:
            return
        try:
            self.exporter.export(draft, result, include_order_id=self.settings.trace_order_ids)
        except Exception:
            logger.warning("observability_export_failed request_id=%s", result.request_id)

    def _trace(self, draft: SignalDraft, result: AgentResult) -> dict:
        return {
            "nodes": draft.nodes,
            "ttft_ms": draft.ttft_ms,
            "end_to_end_latency_ms": draft.e2e_ms,
            "fallback_attempted": draft.fallback_attempted,
            "fallback_recovered": draft.fallback_recovered,
            "rate_limited": draft.rate_limited,
            "retrieval_score": draft.retrieval_score,
            "outcome": result.outcome.value,
        }

    def _context(self, request_id: str, idempotency_key: str) -> CallContext:
        return CallContext(request_id, idempotency_key, self.secrets)

    def _key(self, request: UserRequest, action: str, parts: list[str]) -> str:
        if request.idempotency_key:
            return check_idempotency_key(request.idempotency_key)
        raw = ":".join([self.settings.merchant_id, action, *parts])
        compact = "".join(character if character.isalnum() else "-" for character in raw)[:80]
        if len(compact) < 8:
            compact = f"{compact}-request"
        return compact

    def _call_tool(self, draft: SignalDraft, plugin, fn):
        retry = bool(getattr(plugin, "supports_safe_retry", False))
        last: ToolError | None = None
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            draft.tool_calls += 1
            try:
                result = fn()
                draft.tool_successes += 1
                if attempt == 1:
                    draft.fallback_recovered = True
                return result
            except ToolError as exc:
                last = exc
                if exc.rate_limited:
                    draft.rate_limited = True
                if attempt == 0 and retry and (exc.rate_limited or exc.status_code is None):
                    draft.fallback_attempted = True
                    continue
                break
        assert last is not None
        raise last

    def _refund(
        self,
        request: UserRequest,
        caller: Caller,
        redacted: str,
        reason: str,
        draft: SignalDraft,
    ) -> AgentResult:
        draft.nodes.append("return_planner")
        if not request.order_id:
            return self._result(draft, Intent.REFUND, Outcome.NEEDS_DETAILS, "Send the return from the signed-in order page so the store can confirm the order. No refund was sent.", None)
        if caller.scope != Scope.SERVER and not request.order_access:
            return self._result(draft, Intent.REFUND, Outcome.NEEDS_DETAILS, "Start this return from the signed-in order page so the store can confirm the order. No refund was sent.", None)
        try:
            check_id(request.order_id, "order_id")
        except Exception:
            return self._result(draft, Intent.REFUND, Outcome.DENIED, "That order id cannot be used. No refund was sent.", None)
        key = self._key(request, "refund", [request.order_id, str(request.amount or "full")])
        ctx = self._context(draft.request_id, key)
        draft.nodes.append("commerce_tool")
        try:
            order = self._call_tool(draft, self.commerce, lambda: self.commerce.get_order(ctx, request.order_id))
        except ToolError:
            return self._result(draft, Intent.REFUND, Outcome.FAILED, "That order was not found in the store. No refund was sent.", key)
        if not _customer_ok(order, request, caller):
            return self._result(draft, Intent.REFUND, Outcome.DENIED, "That order does not match the signed-in customer. No refund was sent.", key)
        draft.nodes.append("retriever")
        hit = self.retriever.search(redacted or reason or "return refund")
        draft.retrieval_score = hit.score if hit else None
        window = self._window(hit.excerpt if hit else "")
        amount = request.amount or order.refundable
        currency = check_currency(request.currency or order.currency)
        support_line = self._support_line()
        decision = _guardrail(
            order=order,
            amount=amount,
            currency=currency,
            window_days=window,
            now=self.clock(),
            grounded=hit is not None and hit.score >= self.settings.grounding_score,
            caller=caller,
            limit=self.settings.auto_approve_below,
            support_alert_above=support_line,
            rules=self.rules,
        )
        draft.nodes.append("guardrails")
        if decision == "invalid_amount":
            return self._result(draft, Intent.REFUND, Outcome.DENIED, "The refund amount is not available on that order. No refund was sent.", key)
        if decision == "currency":
            return self._result(draft, Intent.REFUND, Outcome.DENIED, "The refund currency does not match the order. No refund was sent.", key)
        if decision == "currency_not_accepted":
            return self._result(draft, Intent.REFUND, Outcome.DENIED, f"The store payment policy does not accept {currency}. No refund was sent.", key)
        if decision == "window":
            return self._result(draft, Intent.REFUND, Outcome.DENIED, f"Order {order.id} is outside the {window}-day return window, so no refund was sent.", key)
        if decision == "non_refundable":
            blocked = blocked_item_name(order.items, self.rules.non_refundable) or "an item"
            return self._result(
                draft,
                Intent.REFUND,
                Outcome.DENIED,
                f"Order {order.id} includes {blocked}, which the refund policy lists as non-refundable. No refund was sent.",
                key,
            )
        if decision == "partial":
            return self._result(
                draft,
                Intent.REFUND,
                Outcome.DENIED,
                f"The refund policy allows only a full refund of the remaining {format(order.refundable, 'f')} {currency}. No refund was sent.",
                key,
            )
        items = _item_label(order)
        if decision == "auto":
            return self._execute_refund(ctx, draft, order, amount, currency, reason, key, items)
        approval_request = ApprovalRequest(
            action="refund",
            order_id=order.id,
            amount=amount,
            currency=currency,
            reason=reason,
            policy_window_days=window,
            retrieval_score=draft.retrieval_score,
        )
        if decision == "support":
            draft.nodes.append("support_alert")
            alert_status = self.support_alert.notify(ctx, approval_request)
            if isinstance(self.approval, WebhookApproval) and self.approval.url:
                draft.nodes.append("human_approval")
                approval = self.approval.decide(ctx, approval_request)
                if approval.status == "approved":
                    return self._execute_refund(ctx, draft, order, amount, currency, reason, key, items)
                if approval.status == "denied":
                    return self._result(
                        draft,
                        Intent.REFUND,
                        Outcome.DENIED,
                        f"Support denied the return for {items} on order {order.id}. No refund was sent to the payment provider.",
                        key,
                    )
            return self._result(
                draft,
                Intent.REFUND,
                Outcome.PENDING_APPROVAL,
                _support_wait_message(alert_status, items, order.id, amount, currency, support_line),
                key,
            )
        draft.nodes.append("human_approval")
        approval = self.approval.decide(
            ctx,
            ApprovalRequest(
                action="refund",
                order_id=order.id,
                amount=amount,
                currency=currency,
                reason=reason,
                policy_window_days=window,
                retrieval_score=draft.retrieval_score,
            ),
        )
        if approval.status == "approved":
            return self._execute_refund(ctx, draft, order, amount, currency, reason, key, items)
        if approval.status == "denied":
            return self._result(draft, Intent.REFUND, Outcome.DENIED, f"The return for {items} on order {order.id} was denied. No refund was sent to the payment provider.", key)
        return self._result(
            draft,
            Intent.REFUND,
            Outcome.PENDING_APPROVAL,
            f"The return for {items} on order {order.id} needs approval before any refund is sent. No refund was sent to the payment provider. The amount is {format(amount, 'f')} {currency}.",
            key,
        )

    def _execute_refund(self, ctx, draft, order: Order, amount: Decimal, currency: str, reason: str, key: str, items: str) -> AgentResult:
        draft.nodes.append("commerce_tool")
        try:
            recorded = self._call_tool(
                draft,
                self.commerce,
                lambda: self.commerce.record_return(
                    ctx,
                    ReturnRequest(order_id=order.id, amount=amount, currency=currency, reason=reason),
                ),
            )
        except ToolError:
            return self._result(draft, Intent.REFUND, Outcome.FAILED, "The store could not record the return. No refund was sent to the payment provider.", key, [ActionRecord(tool="commerce.record_return", ok=False, status="failed")])
        draft.nodes.append("payment_tool")
        try:
            refund = self._call_tool(
                draft,
                self.payment,
                lambda: self.payment.refund(
                    ctx,
                    RefundRequest(
                        payment_id=order.payment_id,
                        order_id=order.id,
                        amount=amount,
                        currency=currency,
                        reason=reason,
                    ),
                ),
            )
        except ToolError as exc:
            return self._result(
                draft,
                Intent.REFUND,
                Outcome.FAILED,
                f"The return was recorded ({recorded.id}) but the payment provider did not complete the refund: {exc}",
                key,
                [ActionRecord(tool="commerce.record_return", ok=True, status=recorded.status, reference=recorded.id)],
            )
        return self._result(
            draft,
            Intent.REFUND,
            Outcome.COMPLETED,
            f"The return for {items} on order {order.id} is recorded. A refund of {format(amount, 'f')} {currency} was sent to your payment provider. Provider reference: {refund.id}.",
            key,
            [
                ActionRecord(tool="commerce.record_return", ok=True, status=recorded.status, reference=recorded.id),
                ActionRecord(tool="payment.refund", ok=True, status=refund.status, reference=refund.id, amount=format(amount, "f"), currency=currency),
            ],
        )

    def _support(self, request: UserRequest, caller: Caller, redacted: str, draft: SignalDraft) -> AgentResult:
        draft.nodes.append("qa")
        draft.nodes.append("retriever")
        hit = self.retriever.search(redacted)
        draft.retrieval_score = hit.score if hit else None
        order_line = ""
        if request.order_id and (caller.scope == Scope.SERVER or request.order_access):
            try:
                check_id(request.order_id, "order_id")
                ctx = self._context(draft.request_id, self._key(request, "read", [request.order_id]))
                draft.nodes.append("commerce_tool")
                order = self._call_tool(draft, self.commerce, lambda: self.commerce.get_order(ctx, request.order_id))
                if _customer_ok(order, request, caller):
                    order_line = (
                        f" Order {order.id} totals {format(order.total, 'f')} {order.currency} "
                        f"and {format(order.refundable, 'f')} {order.currency} is still refundable."
                    )
            except (ToolError, Exception):
                order_line = " That order was not found in the store."
        if hit is None:
            excerpt = "No matching store policy or FAQ was found. Add your refund rules, payment rules, and FAQs to POLICY_DIR."
            message = f"{excerpt}{order_line}"
        elif hit.title.endswith("?"):
            excerpt = hit.excerpt
            message = f"{excerpt}{order_line}"
        else:
            excerpt = hit.excerpt
            message = f"Store policy: {excerpt}{order_line}"
        complete = getattr(self.model, "complete", None)
        if callable(complete) and hit is not None:
            try:
                drafted = complete(system=_qa_system(excerpt), user=redacted)
                text = drafted.text if hasattr(drafted, "text") else str(drafted)
                draft.input_tokens += int(getattr(drafted, "input_tokens", 0) or 0)
                draft.output_tokens += int(getattr(drafted, "output_tokens", 0) or 0)
                message = f"{text}{order_line}"
                self._apply_cost(draft)
            except Exception:
                draft.fallback_attempted = True
                draft.fallback_recovered = True
        return self._result(draft, Intent.CUSTOMER_SERVICE, Outcome.COMPLETED, message, None)

    def _settlement(self, request: UserRequest, caller: Caller, draft: SignalDraft) -> AgentResult:
        draft.nodes.append("settlement")
        if caller.scope != Scope.SERVER:
            return self._result(draft, Intent.SETTLEMENT, Outcome.DENIED, "Settlement runs from the store backend with the server token. No payment was captured.", None)
        capture = request.settlement_mode == "capture"
        key = self._key(request, "settle", [request.settlement_mode])
        ctx = self._context(draft.request_id, key)
        draft.nodes.append("payment_tool")
        try:
            report = self._call_tool(
                draft,
                self.payment,
                lambda: self.payment.settlement(ctx, capture=capture, now=self.clock()),
            )
        except ToolError as exc:
            return self._result(draft, Intent.SETTLEMENT, Outcome.FAILED, str(exc), key)
        if capture:
            message = f"Captured {len(report.captured)} authorized payments at your payment provider."
            if not report.captured:
                message = "No authorized payments were waiting for capture at your payment provider."
        else:
            message = (
                f"Reconciled payments with your payment provider. {len(report.unsettled)} are waiting for capture "
                f"and {len(report.payouts)} payouts were reported. No money was captured in this request."
            )
        return self._result(
            draft,
            Intent.SETTLEMENT,
            Outcome.COMPLETED,
            message,
            key,
            [ActionRecord(tool="payment.settlement", ok=True, status="captured" if capture else "reconciled")],
        )

    def _conversion(self, request: UserRequest, caller: Caller, draft: SignalDraft) -> AgentResult:
        draft.nodes.append("conversion")
        if not request.amount or not request.from_currency or not request.to_currency:
            return self._result(draft, Intent.CONVERSION, Outcome.NEEDS_DETAILS, "Send the amount, the currency you have, and the currency you want quoted. No payment was created.", None)
        source = check_currency(request.from_currency)
        target = check_currency(request.to_currency)
        if self.rules.currency_conversion is False:
            return self._result(
                draft,
                Intent.CONVERSION,
                Outcome.DENIED,
                "The payment policy does not offer currency conversion. No quote was requested from the payment provider.",
                None,
            )
        refused = _currency_outside_policy(source, target, self.rules.accepted_currencies)
        if refused:
            return self._result(
                draft,
                Intent.CONVERSION,
                Outcome.DENIED,
                f"The payment policy does not accept {refused}. No quote was requested from the payment provider.",
                None,
            )
        key = self._key(request, "fx", [format(request.amount, "f"), source, target])
        ctx = self._context(draft.request_id, key)
        draft.nodes.append("payment_tool")
        try:
            quote = self._call_tool(
                draft,
                self.payment,
                lambda: self.payment.quote_conversion(
                    ctx,
                    ConversionRequest(amount=request.amount, from_currency=source, to_currency=target),
                ),
            )
        except ToolError as exc:
            return self._result(draft, Intent.CONVERSION, Outcome.FAILED, str(exc), key)
        message = (
            f"Your payment provider quoted {format(quote.amount, 'f')} {quote.from_currency} as "
            f"{format(quote.converted_amount, 'f')} {quote.to_currency} at rate {_pretty(quote.rate)}. "
            "The quote is indicative and is not a completed payment."
        )
        actions = [
            ActionRecord(
                tool="payment.quote_conversion",
                ok=True,
                status="quoted",
                reference=quote.quote_id,
                amount=format(quote.converted_amount, "f"),
                currency=quote.to_currency,
            )
        ]
        if request.execute_conversion and caller.scope != Scope.SERVER:
            message += " Creating the converted payment requires the store backend. No payment was created."
            return self._result(draft, Intent.CONVERSION, Outcome.PENDING_APPROVAL, message, key, actions)
        if request.execute_conversion:
            created = self._call_tool(
                draft,
                self.payment,
                lambda: self.payment.create_payment(
                    ctx,
                    CreatePaymentRequest(
                        amount=quote.converted_amount,
                        currency=quote.to_currency,
                        order_id=request.order_id,
                        customer_ref=request.customer_ref,
                    ),
                ),
            )
            message += f" Payment {created.id} was created at {created.provider}. Confirm it in your checkout. Card details stay with the provider."
            actions.append(ActionRecord(tool="payment.create_payment", ok=True, status=created.status, reference=created.id, amount=format(quote.converted_amount, "f"), currency=quote.to_currency))
        return self._result(draft, Intent.CONVERSION, Outcome.COMPLETED, message, key, actions)

    def use_policies(self, documents: list[PolicyDocument]) -> None:
        self.retriever = KeywordRetriever(documents)
        self.rules = parse_policy_rules(documents)

    def refresh_policies(self) -> None:
        """Read organization rules added under POLICY_DIR. Samples stay until that folder has files."""

        if not self.settings.policy_dir:
            return
        loaded = load_policy_dir(self.policy_directory)
        if loaded:
            self.use_policies(loaded)

    def save_org_policy(self, name: str, text: str) -> PolicyDocument:
        if not self.settings.policy_dir:
            raise ValueError("Set POLICY_DIR to the folder that holds your organization rules.")
        saved = save_org_policy(self.policy_directory, name, text)
        self.refresh_policies()
        return saved

    def _window(self, excerpt: str) -> int:
        if self.rules.return_window_days is not None:
            return min(self.settings.return_window_days, self.rules.return_window_days)
        parsed = parse_return_window_days(excerpt) if excerpt else None
        if parsed is None:
            return self.settings.return_window_days
        return min(self.settings.return_window_days, parsed)

    def _support_line(self) -> Decimal:
        if self.rules.support_alert_above is None:
            return self.settings.support_alert_above
        return min(self.settings.support_alert_above, self.rules.support_alert_above)

    def _apply_cost(self, draft: SignalDraft) -> None:
        inbound = self.settings.usd_per_million_input_tokens
        outbound = self.settings.usd_per_million_output_tokens
        if inbound is None and outbound is None:
            return
        cost = Decimal("0")
        if inbound is not None:
            cost += (Decimal(draft.input_tokens) / Decimal(1_000_000)) * inbound
        if outbound is not None:
            cost += (Decimal(draft.output_tokens) / Decimal(1_000_000)) * outbound
        draft.cost_usd = float(cost)

    def _result(
        self,
        draft: SignalDraft,
        intent: Intent,
        outcome: Outcome,
        message: str,
        key: str | None,
        actions: list[ActionRecord] | None = None,
    ) -> AgentResult:
        return AgentResult(
            request_id=draft.request_id,
            intent=intent,
            outcome=outcome,
            message=message,
            actions=actions or [],
            idempotency_key=key,
        )


def _customer_ok(order: Order, request: UserRequest, caller: Caller) -> bool:
    if caller.scope == Scope.SERVER:
        if request.customer_ref and order.customer_ref and request.customer_ref != order.customer_ref:
            return False
        return True
    if not request.customer_ref or not order.customer_ref:
        return False
    return request.customer_ref == order.customer_ref


def _guardrail(
    *,
    order: Order,
    amount: Decimal,
    currency: str,
    window_days: int,
    now: datetime,
    grounded: bool,
    caller: Caller,
    limit: Decimal,
    support_alert_above: Decimal,
    rules,
) -> str:
    if amount <= 0 or amount > order.refundable:
        return "invalid_amount"
    if currency != order.currency.upper():
        return "currency"
    if rules.accepted_currencies and currency not in rules.accepted_currencies:
        return "currency_not_accepted"
    age = now - order.created_at
    if age.days > window_days:
        return "window"
    if blocked_item_name(order.items, rules.non_refundable):
        return "non_refundable"
    if rules.partial_refunds is False and amount < order.refundable:
        return "partial"
    if amount > support_alert_above:
        return "support"
    if caller.scope == Scope.SERVER and grounded and amount <= limit:
        return "auto"
    return "approval"


def _support_wait_message(
    alert_status: str,
    items: str,
    order_id: str,
    amount: Decimal,
    currency: str,
    threshold: Decimal,
) -> str:
    amount_text = f"{format(amount, 'f')} {currency}"
    line = f"{format(threshold, 'f')} {currency}"
    if alert_status == "support_alerted":
        lead = f"Support was alerted because the refund of {amount_text} is above {line}."
    elif alert_status == "support_alert_failed":
        lead = f"The refund of {amount_text} is above {line}. The support alert could not be delivered."
    else:
        lead = f"The refund of {amount_text} is above {line}. Add SUPPORT_ALERT_URL so your support team receives it."
    return (
        f"The return for {items} on order {order_id} is waiting for support. {lead} "
        "No refund was sent to the payment provider."
    )


def _currency_outside_policy(source: str, target: str, accepted: tuple[str, ...]) -> str | None:
    if not accepted:
        return None
    missing = [code for code in (source, target) if code not in accepted]
    if not missing:
        return None
    return " or ".join(missing)


def _pretty(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _item_label(order: Order) -> str:
    names = [item.name for item in order.items]
    return ", ".join(names) if names else "this order"


def _qa_system(excerpt: str) -> str:
    return (
        "Answer only from the store policy excerpt. Do not invent a refund, a balance, or a payment result. "
        "Do not ask for card numbers. Policy excerpt: "
        + excerpt
    )


def seed_demo(payment: MockPaymentPlugin, commerce: MockCommercePlugin, now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc)
    from datetime import timedelta

    order = Order(
        id="1001",
        customer_ref="cust_1",
        currency="USD",
        total=Decimal("80.00"),
        refundable=Decimal("80.00"),
        created_at=current - timedelta(days=5),
        payment_id="pay_1001",
        items=[{"sku": "hp-1", "name": "Headphones", "quantity": 1, "amount": Decimal("80.00")}],
    )
    commerce.orders[order.id] = order
    payment.payments["pay_1001"] = {
        "order_id": "1001",
        "amount": Decimal("80.00"),
        "refunded": Decimal("0"),
        "currency": "USD",
        "captured": True,
    }
    payment.payments["pay_auth"] = {
        "order_id": "1002",
        "amount": Decimal("20.00"),
        "refunded": Decimal("0"),
        "currency": "USD",
        "captured": False,
    }


def bundled_policies() -> list[PolicyDocument]:
    return load_policy_dir(Path(__file__).resolve().parent / "policies")


def build_agent(
    settings: Settings,
    *,
    secrets: SecretSource,
    client: httpx.Client | None = None,
    policies: list[PolicyDocument] | None = None,
    model: object | None = None,
    clock: Callable[[], datetime] | None = None,
    payment=None,
    commerce=None,
    approval=None,
    exporter: object | None = None,
    support_alert: SupportAlert | None = None,
) -> AgentApp:
    if settings.payment_plugin == "mock" and not settings.demo:
        logger.warning("PAYMENT_PLUGIN=mock is a local stand-in. Connect the payment system you use before production.")
    payment_plugin = payment if payment is not None else create_payment(settings, client)
    commerce_plugin = commerce if commerce is not None else create_commerce(settings, client)
    approval_plugin = approval if approval is not None else create_approval(settings, client)
    if policies is None:
        loaded = load_policy_dir(Path(settings.policy_dir)) if settings.policy_dir else []
        if not loaded and settings.demo:
            loaded = bundled_policies()
        policies = loaded
    if settings.demo and isinstance(payment_plugin, MockPaymentPlugin) and isinstance(commerce_plugin, MockCommercePlugin):
        seed_demo(payment_plugin, commerce_plugin, clock() if clock else None)
        logger.warning("Demo mode is on. It seeds a sample order and must stay off in production.")
    if exporter is None and settings.langfuse_host:
        from ecommerce_agent.exporters import LangfuseExporter

        exporter = LangfuseExporter(settings, secrets, client)
    if support_alert is None:
        support_alert = SupportAlert(settings.support_alert_url, client)
    return AgentApp(
        settings=settings,
        secrets=secrets,
        payment=payment_plugin,
        commerce=commerce_plugin,
        approval=approval_plugin,
        retriever=KeywordRetriever(policies),
        model=model,
        clock=clock,
        exporter=exporter,
        support_alert=support_alert,
    )
