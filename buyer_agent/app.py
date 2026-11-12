"""buyer-agent FastAPI app (doc 07 §4).

Run: uvicorn buyer_agent.app:app --port 8200
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from buyer_agent import shopper
from buyer_agent.config import settings
from buyer_agent.db import BuyerDB
from buyer_agent.mandate import period_start
from buyer_agent.prp_client import MerchantKey, PRPClient
from buyer_agent.recovery import Deps, buy
from shared.money import fmt
from shared.prp import keys, signing
from shared.prp.ids import new_id
from shared.prp.models import Mandate
from shared.prp.signing import MemoryNonceStore, PRPAuthError

logger = logging.getLogger(__name__)
PRINCIPAL_ID = "prn_maya"


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: str
    sku: str
    category: str
    amount_minor: StrictInt = Field(ge=1)
    currency_code: str = "USD"
    quantity: StrictInt = Field(default=1, ge=1, le=10)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    merchant_id: str = "mer_kettle_crumb"


class ConnectRequest(BaseModel):
    base_url: str | None = None
    callback: bool = True


def create_app(
    *,
    db: BuyerDB | None = None,
    http: httpx.AsyncClient | None = None,
    signing_key_b64: str | None = None,
    key_id: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FastAPI:
    app = FastAPI(title="Pact buyer agent", version="0.1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.web_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    store = db or BuyerDB(settings.buyer_db_path)
    b64 = signing_key_b64 if signing_key_b64 is not None else settings.buyer_signing_key
    priv = keys.private_from_b64(b64) if b64 else keys.generate()
    agent_key_id = key_id or settings.buyer_key_id or keys.key_id(f"agt_{keys.fingerprint(priv.public_key())[:12]}")
    agent_id = agent_key_id.split("#", 1)[0]
    callback_nonces = MemoryNonceStore()
    if not b64:
        logger.warning("BUYER_SIGNING_KEY not set: using an ephemeral key (%s)", agent_key_id)

    def client_for(merchant_id: str) -> tuple[PRPClient, dict[str, Any]]:
        link = store.merchant_link(merchant_id)
        if not link or not link.get("merchant_public_key"):
            raise HTTPException(409, f"not connected to {merchant_id}")
        mk = MerchantKey(link["merchant_key_id"], keys.public_from_b64(link["merchant_public_key"]))
        return PRPClient(link["base_url"], priv, agent_key_id, mk, http=http,
                         clock=lambda: clock().timestamp()), link

    def active_mandate() -> Mandate:
        row = store.active_mandate()
        if not row:
            raise HTTPException(409, "no active mandate")
        return Mandate.model_validate(row["body"])

    async def run_purchase(req: PurchaseRequest) -> dict[str, Any]:
        mandate = active_mandate()
        client, link = client_for(req.merchant_id)
        host = urlparse(link["base_url"]).hostname or ""
        deps = Deps(db=store, client=client, mandate=mandate, principal_id=PRINCIPAL_ID,
                    merchant_id=req.merchant_id, merchant_name=link.get("merchant_name") or req.merchant_id,
                    merchant_domains=(host,) if host else (), clock=clock)
        r = await buy(deps, sku=req.sku, category=req.category, amount_minor=req.amount_minor,
                      currency_code=req.currency_code, quantity=req.quantity)
        return {"purchase_id": r.purchase_id, "status": r.status, "outcome": r.outcome,
                "intent_id": r.intent_id, "detail": r.detail,
                "guard": [{"decision": g.decision, "rule_fired": g.rule_fired, "reason": g.reason} for g in r.guard_results]}

    def purchase_view(row: dict[str, Any]) -> dict[str, Any]:
        pid = row["purchase_id"]
        decisions = store.guard_decisions_for(pid)
        link = store.merchant_link(row["merchant_id"]) or {}
        name = link.get("merchant_name") or row["merchant_id"]
        marks = {"pass": "✓", "fail": "✗", "skip": "–"}
        tails = {"ACCEPT": "Accepted automatically", "ESCALATE": "Asked you to decide", "REJECT": "Rejected"}
        for gd in decisions:
            lines = [f"Recovery offer from {name} · {fmt(row['amount_minor'], row['currency_code'])}"]
            lines += [f"  {marks[c['status']]} {c['label']}" for c in gd["checks"]]
            lines.append(f"  → {tails[gd['result']]}")
            gd["checklist"] = "\n".join(lines)
        offers = store.offers_for(pid)
        for o in offers:
            o["body"] = o.pop("body_json")
        return {**row, "guard_decisions": decisions, "offers": offers}

    # ------------------------------------------------------------------ #

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"service": "buyer-agent", "agent_key_id": agent_key_id,
                "agent_public_key": keys.public_to_b64(priv.public_key()),
                "llm": "live" if settings.llm_live else "disabled",
                "signing_key": "configured" if b64 else "ephemeral", "paused": store.is_paused()}

    @app.get("/buyer/mandates")
    def list_mandates() -> list[dict[str, Any]]:
        return store.mandates()

    @app.post("/buyer/mandates/draft", status_code=201)
    async def draft_mandate(body: dict[str, Any]) -> dict[str, Any]:
        """Either a full mandate body, or {"text": "...", "display_name"?, "merchant_id"?},
        which the shopper drafts (LLM or template) into one. Always saved as DRAFT."""
        if "text" in body and set(body) <= {"text", "display_name", "merchant_id"}:
            terms = await shopper.draft_terms(str(body["text"]), http)
            if terms is None:
                raise HTTPException(422, "couldn't find a budget in that; try e.g. '$60 a week'")
            body = shopper.build_mandate(
                terms, mandate_id=new_id("mdt"), display_name=str(body.get("display_name", "Maya"))[:60],
                merchant_scope=[str(body.get("merchant_id", "mer_kettle_crumb"))],
                expires_at=(clock() + timedelta(days=90)).isoformat())
        try:
            m = Mandate.model_validate(body)
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False)) from e
        store.upsert_principal(PRINCIPAL_ID, m.principal.display_name)
        store.save_mandate(m.mandate_id, PRINCIPAL_ID, m.model_dump(mode="json", exclude_none=True), "DRAFT")
        return {"mandate_id": m.mandate_id, "status": "DRAFT",
                "mandate": m.model_dump(mode="json", exclude_none=True)}

    @app.post("/buyer/mandates/{mandate_id}/activate")
    def activate_mandate(mandate_id: str) -> dict[str, Any]:
        """Local/judge shortcut. In the full flow this follows merchant onboarding approval."""
        if not any(m["mandate_id"] == mandate_id for m in store.mandates()):
            raise HTTPException(404, "unknown mandate")
        for m in store.mandates():
            if m["status"] == "ACTIVE" and m["mandate_id"] != mandate_id:
                store.set_mandate_status(m["mandate_id"], "REVOKED")
        store.set_mandate_status(mandate_id, "ACTIVE")
        return {"mandate_id": mandate_id, "status": "ACTIVE"}

    @app.post("/buyer/merchants/{merchant_id}/connect")
    async def connect(merchant_id: str, req: ConnectRequest | None = None) -> dict[str, Any]:
        req = req or ConnectRequest()
        mandate = active_mandate() if store.active_mandate() else None
        if mandate is None:
            drafts = store.mandates()
            if not drafts:
                raise HTTPException(409, "draft a mandate first")
            mandate = Mandate.model_validate(drafts[0]["body"])
        base = (req.base_url or settings.merchant_base_url).rstrip("/")
        link = store.merchant_link(merchant_id)
        pinned = (MerchantKey(link["merchant_key_id"], keys.public_from_b64(link["merchant_public_key"]))
                  if link and link.get("merchant_public_key") and link.get("merchant_key_id") else None)
        client = PRPClient(base, priv, agent_key_id, pinned, http=http, clock=lambda: clock().timestamp())
        body: dict[str, Any] = {
            "prp_version": "0.1", "agent_id": agent_id, "agent_key_id": agent_key_id,
            "agent_public_key": keys.public_to_b64(priv.public_key()),
            "mandate": mandate.model_dump(mode="json", exclude_none=True),
        }
        if req.callback:
            body["callback_url"] = settings.buyer_public_url.rstrip("/") + "/prp/callback"
        resp = await client.register(body)
        if not resp.signature_ok:
            if resp.status != 201 and resp.signature_error == "UNVERIFIED_ERROR":
                raise HTTPException(resp.status, f"merchant returned {resp.status} (unsigned or unverifiable error)")
            raise HTTPException(502, f"merchant response failed verification: {resp.signature_error}")
        if resp.status != 201:
            raise HTTPException(resp.status, resp.body)
        b = resp.body
        if b.get("merchant_id") != merchant_id:
            raise HTTPException(502, "merchant id mismatch")
        store.upsert_merchant_link(
            merchant_id, base_url=base, agent_id=agent_id, merchant_public_key=b["merchant_public_key"],
            merchant_key_id=b["merchant_key_id"], merchant_name=b.get("merchant_name"),
            mandate_id=mandate.mandate_id, status=b.get("registration_status", "PENDING_APPROVAL"),
        )
        return {"merchant_id": merchant_id, "approval_url": b.get("approval_url"),
                "registration_status": b.get("registration_status")}

    @app.post("/buyer/purchases")
    async def place_purchase(req: PurchaseRequest) -> dict[str, Any]:
        return await run_purchase(req)

    @app.post("/buyer/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        client, link = client_for(req.merchant_id)
        h = http or httpx.AsyncClient(timeout=20.0)
        try:
            cat = (await h.get(link["base_url"].rstrip("/") + "/store/catalog")).json()
        except (httpx.HTTPError, ValueError) as e:
            raise HTTPException(502, f"catalog unavailable: {e}") from e
        items = cat.get("items", cat) if isinstance(cat, dict) else cat
        if isinstance(items, dict):  # merchant serves {sku: {name, category, price_minor}}
            items = [{"sku": sku, **v} for sku, v in items.items()]
        intent = await shopper.propose(req.message, items, http)
        if intent is None:
            return {"reply": "I couldn't find that in the catalog.", "purchase": None}
        item = next(i for i in items if i["sku"] == intent.sku)
        result = await run_purchase(PurchaseRequest(
            merchant_id=req.merchant_id, sku=item["sku"], category=item["category"],
            amount_minor=item["price_minor"] * intent.quantity,
            currency_code=item.get("currency_code", "USD"), quantity=intent.quantity))
        return {"reply": f"{result['status'].replace('_', ' ').lower()}: {item.get('name', item['sku'])}",
                "purchase": result}

    @app.get("/buyer/purchases")
    def list_purchases() -> list[dict[str, Any]]:
        return store.purchases()

    @app.get("/buyer/purchases/{purchase_id}")
    def get_purchase(purchase_id: str) -> dict[str, Any]:
        row = store.purchase(purchase_id)
        if not row:
            raise HTTPException(404, "unknown purchase")
        return purchase_view(row)

    @app.get("/buyer/by-intent/{intent_id}")
    def by_intent(intent_id: str) -> dict[str, Any]:
        row = store.purchase_by_intent(intent_id)
        if not row:
            raise HTTPException(404, "unknown intent")
        return purchase_view(row)

    @app.get("/buyer/budget")
    def budget() -> dict[str, Any]:
        m = active_mandate()
        spent = store.spent_since(m.mandate_id, period_start(m.budget.period, clock()))
        return {"period": m.budget.period, "limit_minor": m.budget.limit_minor, "spent_minor": spent,
                "remaining_minor": m.budget.limit_minor - spent, "currency_code": m.currency_code}

    @app.get("/buyer/inbox")
    def inbox() -> list[dict[str, Any]]:
        return store.inbox()

    @app.post("/buyer/inbox/{msg_id}/dismiss")
    def dismiss(msg_id: str) -> dict[str, Any]:
        if not store.dismiss(msg_id):
            raise HTTPException(404, "unknown message")
        return {"msg_id": msg_id, "status": "DISMISSED"}

    @app.post("/buyer/reset")
    def reset() -> dict[str, Any]:
        """Judge mode: back to the scenario baseline (mandate and merchant link kept)."""
        store.reset_activity()
        return {"reset": True}

    @app.post("/buyer/pause")
    def pause() -> dict[str, Any]:
        store.set_paused(True)
        return {"paused": True}

    @app.post("/buyer/resume")
    def resume() -> dict[str, Any]:
        store.set_paused(False)
        return {"paused": False}

    @app.post("/prp/callback")
    async def prp_callback(request: Request) -> Response:
        raw = await request.body()

        def resolve(kid: str):
            link = store.merchant_link_by_key_id(kid)
            return keys.public_from_b64(link["merchant_public_key"]) if link else None

        try:
            v = signing.verify(request.headers, "POST", "/prp/callback", raw, resolve, callback_nonces,
                               now=int(clock().timestamp()))
        except PRPAuthError as e:
            err = signing.canonical_json({"prp_version": "0.1", "error": {"code": e.code, "message": e.message}})
            return Response(err, status_code=401, media_type="application/json")
        body = v.body if isinstance(v.body, dict) else {}
        if body.get("event") == "registration.active":
            # Maya approved on the merchant's onboarding page: activate our copy of that mandate.
            link = store.merchant_link_by_key_id(v.key_id)
            mid = body.get("mandate_id")
            if link and mid == link.get("mandate_id") and any(m["mandate_id"] == mid for m in store.mandates()):
                for m in store.mandates():
                    if m["status"] == "ACTIVE" and m["mandate_id"] != mid:
                        store.set_mandate_status(m["mandate_id"], "REVOKED")
                store.set_mandate_status(mid, "ACTIVE")
                store.set_merchant_link_status(link["merchant_id"], "ACTIVE")
        elif body.get("event") == "intent.updated":
            row = store.purchase_by_intent(str(body.get("intent_id")))
            outcome = body.get("outcome")
            if row and outcome in ("RECOVERED", "RECOVERED_BY_HUMAN", "ORGANIC") and row["status"] != "PAID":
                store.update_purchase(row["purchase_id"], status="PAID", outcome=outcome)
                mid = (store.merchant_link(row["merchant_id"]) or {}).get("mandate_id")
                mrow = next((x for x in store.mandates() if x["mandate_id"] == mid), None)
                if mrow:
                    m = Mandate.model_validate(mrow["body"])
                    store.record_spend(mandate_id=m.mandate_id, period_start=period_start(m.budget.period, clock()),
                                       amount_minor=row["amount_minor"], purchase_id=row["purchase_id"])
                store.add_inbox(principal_id=PRINCIPAL_ID, kind="RECEIPT", purchase_id=row["purchase_id"],
                                text=f"Paid {fmt(row['amount_minor'], row['currency_code'])} after your approval.")
            elif row and outcome == "LOST":
                store.update_purchase(row["purchase_id"], status="LOST", outcome="LOST")
        msg = signing.sign(priv, agent_key_id, "POST", "/prp/callback", {"prp_version": "0.1", "ok": True},
                           timestamp=int(clock().timestamp()))
        return Response(msg.body, status_code=200, headers=msg.headers)

    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """`uvicorn buyer_agent.app:app` builds the app on first access, not at import,
    so tests can import create_app without touching data/buyer.db."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
