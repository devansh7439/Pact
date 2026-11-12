"""The buyer's purchase-and-recovery loop (doc 01 flows B and C).

    purchase-time checks -> checkout -> [402 offer -> scan -> guard -> accept | escalate | reject]*

This is the only caller of `PRPClient.checkout` and `PRPClient.accept`. An
autonomous accept happens only when `guard()` returns ACCEPT. The one
non-guard accept is a PAYER_ACTION accept on escalation: it moves no money and
only fetches the PayPal approve link for the human to tap.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from buyer_agent import notify
from buyer_agent.db import BuyerDB
from buyer_agent.guard import GuardInput, GuardResult, PurchaseRecord, guard
from buyer_agent.mandate import check_purchase, period_start, preferred_funding
from buyer_agent.prp_client import PRPClient, PRPResponse
from buyer_agent.scanner import scan
from shared.prp.models import Mandate

MAX_ROUNDS = 5  # hard stop on offer ping-pong, independent of the mandate


@dataclass
class Deps:
    db: BuyerDB
    client: PRPClient
    mandate: Mandate
    principal_id: str
    merchant_id: str
    merchant_name: str
    merchant_domains: tuple[str, ...] = ()
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


@dataclass
class BuyResult:
    purchase_id: str | None
    status: str  # PAID | PENDING_APPROVAL | ESCALATED | REJECTED | BLOCKED | FAILED
    outcome: str | None = None  # ORGANIC | RECOVERED | None
    intent_id: str | None = None
    guard_results: list[GuardResult] = field(default_factory=list)
    detail: str = ""


def _spent(d: Deps) -> int:
    return d.db.spent_since(d.mandate.mandate_id, period_start(d.mandate.budget.period, d.clock()))


def _record(d: Deps, pid: str) -> PurchaseRecord:
    row = d.db.purchase(pid)
    assert row is not None
    return PurchaseRecord(
        purchase_id=pid,
        merchant_id=row["merchant_id"],
        intent_id=row["intent_id"] or "",
        amount_minor=row["amount_minor"],
        currency_code=row["currency_code"],
        funding_alias=row["funding_alias"],
        autonomous_recoveries=row["autonomous_recoveries"],
        failed_aliases=frozenset(row["failed_aliases"]),
    )


async def buy(d: Deps, *, sku: str, category: str, amount_minor: int, currency_code: str, quantity: int = 1) -> BuyResult:
    check = check_purchase(
        d.mandate, merchant_id=d.merchant_id, category=category, amount_minor=amount_minor,
        currency_code=currency_code, spent_this_period_minor=_spent(d), now=d.clock(), paused=d.db.is_paused(),
    )
    if not check.ok:
        d.db.add_inbox(principal_id=d.principal_id, kind="INFO",
                       text=f"I didn't place the order: {check.detail}.")
        return BuyResult(None, "BLOCKED", detail=check.reason)

    alias = preferred_funding(d.mandate)
    pid = d.db.create_purchase(merchant_id=d.merchant_id, sku=sku, category=category,
                               amount_minor=amount_minor, currency_code=currency_code, funding_alias=alias)
    resp = await d.client.checkout({
        "prp_version": "0.1",
        "mandate_id": d.mandate.mandate_id,
        "sku": sku,
        "quantity": quantity,
        "amount": {"currency_code": currency_code, "value_minor": amount_minor},
        "funding_alias": alias,
        "idempotency_key": f"chk_{pid}",
    })
    d.db.update_purchase(pid, status="CHECKOUT_SENT")
    return await _drive(d, pid, resp, attempted_alias=alias)


async def _drive(d: Deps, pid: str, resp: PRPResponse, *, attempted_alias: str | None) -> BuyResult:
    results: list[GuardResult] = []
    recovered = False
    for _ in range(MAX_ROUNDS):
        row = d.db.purchase(pid)
        assert row is not None

        if resp.signature_ok and resp.status == 200:
            body = resp.body or {}
            outcome = "RECOVERED" if recovered else "ORGANIC"
            d.db.update_purchase(pid, status="PAID", outcome=outcome, intent_id=row["intent_id"] or body.get("intent_id"))
            d.db.record_spend(mandate_id=d.mandate.mandate_id,
                              period_start=period_start(d.mandate.budget.period, d.clock()),
                              amount_minor=row["amount_minor"], purchase_id=pid)
            last = results[-1] if results else None
            src = d.mandate.funding_by_alias(last.alias) if last and last.alias else None
            d.db.add_inbox(principal_id=d.principal_id, kind="RECEIPT", purchase_id=pid, text=notify.receipt_text(
                d.merchant_name, row["amount_minor"], row["currency_code"], alias=last.alias if last else None,
                failure_class=_last_failure_class(d, pid), recovered=recovered,
                alias_kind=src.kind if src else None))
            return BuyResult(pid, "PAID", outcome, row["intent_id"] or body.get("intent_id"), results)

        if resp.signature_ok and resp.status == 202:
            body = resp.body if isinstance(resp.body, dict) else {}
            url = body.get("approve_url")
            if url:
                d.db.update_purchase(pid, status="PENDING_APPROVAL", outcome="PENDING")
                d.db.add_inbox(principal_id=d.principal_id, kind="ESCALATION", approve_url=url, purchase_id=pid,
                               text=f"Please approve your {d.merchant_name} payment on PayPal.")
                return BuyResult(pid, "PENDING_APPROVAL", "PENDING", row["intent_id"], results)
            # Merchant accepted the request but executes later: review-first mode
            # (PENDING_REVIEW) or a RETRY_AFTER (SCHEDULED). Wait for the callback / poll.
            waiting = "SCHEDULED" if body.get("status") == "SCHEDULED" else "PENDING_MERCHANT"
            d.db.update_purchase(pid, status=waiting, outcome="PENDING")
            when = f" after {body['not_before']}" if body.get("not_before") else ""
            d.db.add_inbox(principal_id=d.principal_id, kind="INFO", purchase_id=pid,
                           text=f"{d.merchant_name} accepted the recovery and will process it{when}. "
                                f"I'll confirm once it's paid.")
            return BuyResult(pid, waiting, "PENDING", row["intent_id"], results)

        if resp.status == 402 or not resp.signature_ok:
            if attempted_alias and resp.signature_ok:
                d.db.add_failed_alias(pid, attempted_alias)  # our own record of what declined
            gr, next_resp, next_alias = await _handle_offer(d, pid, resp)
            results.append(gr)
            if next_resp is None:
                status = {"ESCALATE": "ESCALATED", "REJECT": "REJECTED"}.get(gr.decision, "FAILED")
                return BuyResult(pid, status, None, d.db.purchase(pid)["intent_id"], results, gr.reason)  # type: ignore[index]
            if gr.decision == "ACCEPT":
                recovered = True
            resp, attempted_alias = next_resp, next_alias
            continue

        d.db.update_purchase(pid, status="FAILED")
        err = (resp.body or {}).get("error", {}) if isinstance(resp.body, dict) else {}
        return BuyResult(pid, "FAILED", None, row["intent_id"], results, err.get("code", f"http_{resp.status}"))

    d.db.update_purchase(pid, status="ESCALATED")
    return BuyResult(pid, "ESCALATED", None, None, results, "too_many_rounds")


def _last_failure_class(d: Deps, pid: str) -> str | None:
    for o in reversed(d.db.offers_for(pid)):
        if o["signature_ok"]:
            try:
                return json.loads(o["body_json"])["failure"]["class"]
            except (KeyError, ValueError, TypeError):
                return None
    return None


async def _handle_offer(d: Deps, pid: str, resp: PRPResponse) -> tuple[GuardResult, PRPResponse | None, str | None]:
    """Guard one offer. Returns (result, the merchant's next response if we accepted, alias used)."""
    offer: dict[str, Any] | None = resp.body if resp.signature_ok and isinstance(resp.body, dict) else None
    offer_id = str(offer.get("offer_id")) if offer else "unverified"

    if offer and not d.db.purchase(pid)["intent_id"] and isinstance(offer.get("intent_id"), str):  # type: ignore[index]
        d.db.update_purchase(pid, intent_id=offer["intent_id"])

    flags: list[str] = []
    if offer:
        text = (offer.get("display") or {}).get("text", "") if isinstance(offer.get("display"), dict) else ""
        flags = scan(text, d.merchant_domains)
    d.db.store_offer(offer_id=offer_id, purchase_id=pid, raw=resp.raw, signature_ok=resp.signature_ok,
                     signature_error=resp.signature_error, scanner_flags=flags)
    if flags:
        d.db.add_inbox(principal_id=d.principal_id, kind="SECURITY", purchase_id=pid,
                       text=notify.security_text(d.merchant_name, flags))

    rec = _record(d, pid)
    gr = guard(GuardInput(
        offer=offer, signature_ok=resp.signature_ok, mandate=d.mandate, purchase=rec,
        spent_this_period_minor=_spent(d), now=d.clock(), paused=d.db.is_paused(),
        merchant_name=d.merchant_name,
    ))
    gd_id = d.db.store_guard_decision(
        offer_id=offer_id if offer else None, purchase_id=pid, result=gr.decision, rule_fired=gr.rule_fired,
        option_id=gr.option_id, alias=gr.alias, reason=gr.reason,
        checks=[{"rule": c.rule, "status": c.status, "label": c.label} for c in gr.checks],
    )

    if gr.decision == "ACCEPT" and offer:
        d.db.bump_recoveries(pid)
        d.db.update_purchase(pid, status="RECOVERING")
        nxt = await d.client.accept(offer_id, _acceptance(d, offer_id, gr.option_id, gr.alias, gd_id))
        return gr, nxt, gr.alias

    amount, cur = rec.amount_minor, rec.currency_code
    if gr.decision == "REJECT":
        d.db.update_purchase(pid, status="OFFER_REJECTED")
        d.db.add_inbox(principal_id=d.principal_id, kind="SECURITY" if gr.rule_fired in ("G1", "G2") else "INFO",
                       purchase_id=pid, text=notify.rejection_text(gr, d.merchant_name))
        return gr, None, None

    # ESCALATE: if the merchant offered PAYER_ACTION, fetch the approve link for the human.
    approve_url = None
    if gr.option_id and offer:
        payer = await d.client.accept(offer_id, _acceptance(d, offer_id, gr.option_id, None, gd_id))
        if payer.signature_ok and payer.status == 202:
            approve_url = (payer.body or {}).get("approve_url")
    d.db.update_purchase(pid, status="ESCALATED", outcome="PENDING" if approve_url else None)
    failure_class = ((offer or {}).get("failure") or {}).get("class") if offer else None
    d.db.add_inbox(principal_id=d.principal_id, kind="ESCALATION", purchase_id=pid, approve_url=approve_url,
                   text=notify.escalation_text(gr, d.merchant_name, amount, cur, failure_class, bool(approve_url)))
    return gr, None, None


def _acceptance(d: Deps, offer_id: str, option_id: str | None, alias: str | None, gd_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prp_version": "0.1",
        "offer_id": offer_id,
        "option_id": option_id,
        "mandate_id": d.mandate.mandate_id,
        "agent_decision_ref": gd_id,
        "idempotency_key": f"acc_{offer_id}_{option_id}",
    }
    if alias:
        body["funding_alias"] = alias
    return body
