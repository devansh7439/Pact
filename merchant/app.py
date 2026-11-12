"""merchant-api: FastAPI wiring (doc 07 §3).

    uvicorn merchant.app:app --port 8100

PRP routes verify the signature on the raw bytes *before* the body is used
(doc 03 §3) and sign every response with the request's method and path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from merchant import console
from merchant.config import Settings, settings as default_settings
from merchant.db import Database, SqliteNonceStore, security_event
from merchant.integrations import llm
from merchant.assistant import AskPactAssistant, PactReadTools
from merchant.judge import SCENARIOS, Judge, JudgeError
from merchant.paypal import make_paypal
from merchant.service import MerchantService, err
from shared.prp import keys, signing

log = logging.getLogger(__name__)


def create_app(service: MerchantService | None = None, *, cfg: Settings | None = None,
               buyer: httpx.Client | None = None) -> FastAPI:
    cfg = cfg or default_settings
    if service is None:
        db = Database(cfg.merchant_db_path)
        service = MerchantService(cfg, db, make_paypal(cfg), http=httpx.Client(timeout=10))
    svc = service
    nonces = SqliteNonceStore(svc.db)
    if buyer is None and cfg.judge_mode:
        buyer = httpx.Client(base_url=cfg.buyer_public_url, timeout=30)
    judge = Judge(svc, buyer)
    app_state_judge = judge
    if cfg.judge_mode:
        judge.seed_human()
    app = FastAPI(title="Pact merchant-api", version="0.3.0")
    app.state.service = svc
    app.state.judge = app_state_judge
    app.add_middleware(CORSMiddleware, allow_origins=[cfg.web_public_url],
                       allow_methods=["*"], allow_headers=["*"])

    # -- PRP plumbing -------------------------------------------------------------
    def signed(request: Request, status: int, body: Any) -> Response:
        msg = svc.sign(request.method, request.url.path, body)
        return Response(content=msg.body, status_code=status, headers=msg.headers,
                        media_type="application/json")

    async def verified(request: Request, resolve=None) -> tuple[signing.Verified | None, Response | None]:
        raw = await request.body()
        try:
            v = signing.verify(dict(request.headers), request.method, request.url.path, raw,
                               resolve or svc.agent_key, nonces)
            return v, None
        except signing.PRPAuthError as exc:
            with svc.db.tx() as conn:
                security_event(conn, exc.code, {"path": request.url.path,
                                                "key_id": request.headers.get(signing.H_KEY_ID)})
            status = 409 if exc.code == "REPLAYED_NONCE" else 401
            return None, signed(request, *err(status, exc.code, str(exc)))

    agent = APIRouter(prefix="/agent/v1")

    @agent.post("/register")
    async def register(request: Request) -> Response:
        raw = await request.body()
        try:                                     # trust on first use: the key comes in the body
            claimed = json.loads(raw)
            tofu = keys.public_from_b64(claimed["agent_public_key"])
            tofu_id = claimed["agent_key_id"]
        except (ValueError, KeyError, TypeError):
            return signed(request, *err(422, "INVALID_OPTION", "malformed registration"))
        v, bad = await verified(request, lambda kid: tofu if kid == tofu_id else svc.agent_key(kid))
        if bad:
            return bad
        return signed(request, *svc.register(v.key_id, v.body))

    @agent.post("/checkout")
    async def checkout(request: Request) -> Response:
        v, bad = await verified(request)
        return bad or signed(request, *svc.checkout(v.key_id, v.body or {}))

    @agent.get("/offers/{offer_id}")
    async def get_offer(offer_id: str, request: Request) -> Response:
        v, bad = await verified(request)
        return bad or signed(request, *svc.get_offer(v.key_id, offer_id))

    @agent.post("/offers/{offer_id}/accept")
    async def accept(offer_id: str, request: Request) -> Response:
        v, bad = await verified(request)
        return bad or signed(request, *svc.accept(v.key_id, offer_id, v.body or {}))

    @agent.post("/offers/{offer_id}/decline")
    async def decline(offer_id: str, request: Request) -> Response:
        v, bad = await verified(request)
        return bad or signed(request, *svc.decline(v.key_id, offer_id, v.body or {}))

    @agent.get("/intents/{intent_id}")
    async def intent(intent_id: str, request: Request) -> Response:
        v, bad = await verified(request)
        return bad or signed(request, *svc.get_intent(v.key_id, intent_id))

    app.include_router(agent)

    # -- Storefront & onboarding ----------------------------------------------------
    @app.get("/store/catalog")
    def store_catalog() -> dict:
        from merchant.catalog import CATALOG
        return {"merchant": {"id": cfg.merchant_id, "name": cfg.merchant_name}, "items": CATALOG}

    @app.get("/onboard/{token}")
    def onboard(token: str) -> JSONResponse:
        return JSONResponse(*reversed(svc.onboarding(token)))

    @app.post("/onboard/{token}/vault/paypal")
    async def onboard_vault(token: str, request: Request) -> JSONResponse:
        body = await _json(request)
        return JSONResponse(*reversed(svc.onboarding_vault(token, body.get("alias", "paypal-wallet"))))

    @app.post("/onboard/{token}/confirm")
    async def onboard_confirm(token: str, request: Request) -> JSONResponse:
        body = await _json(request)
        return JSONResponse(*reversed(svc.onboarding_confirm(token, body.get("payer_id"))))

    @app.get("/paypal/return", response_class=HTMLResponse)
    def paypal_return(request: Request) -> HTMLResponse:
        q = request.query_params
        if q.get("onboarding"):                      # vault approval returned
            status, body = svc.onboarding_saved(q["onboarding"], q.get("alias", ""),
                                                q.get("approval_token_id") or q.get("token", ""))
            target = f"{cfg.web_public_url}/onboard/{q['onboarding']}"
        else:                                        # order approval returned
            status, body = (200, {"status": "CANCELLED"}) if q.get("cancel") else \
                svc.capture_approved(q.get("token", ""), "api")
            target = f"{cfg.web_public_url}/buyer"
        return HTMLResponse(f"<p>{body.get('status', status)}</p>"
                            f"<p><a href='{target}'>Back to Pact</a></p>", status_code=status)

    # -- PayPal webhooks -------------------------------------------------------------
    @app.post("/paypal/webhooks")
    async def webhooks(request: Request) -> JSONResponse:
        return JSONResponse(*reversed(svc.webhook(dict(request.headers), await request.body())))

    # -- Console -----------------------------------------------------------------------
    @app.get("/console/feed")
    def feed(since: int = 0) -> dict:
        return console.feed(svc.db, since)

    @app.get("/console/ledger")
    def ledger() -> list[dict]:
        return console.ledger(svc.db)

    @app.get("/console/decisions/{decision_id}")
    def decision(decision_id: str) -> JSONResponse:
        d = console.decision(svc.db, decision_id)
        return JSONResponse(d) if d else JSONResponse({"error": "not found"}, 404)

    @app.get("/console/review-queue")
    def review_queue() -> list[dict]:
        return svc.review_queue()

    @app.post("/console/review-queue/{decision_id}/approve")
    def approve(decision_id: str) -> JSONResponse:
        return JSONResponse(*reversed(svc.review(decision_id, True)))

    @app.post("/console/review-queue/{decision_id}/reject")
    def reject(decision_id: str) -> JSONResponse:
        return JSONResponse(*reversed(svc.review(decision_id, False)))

    @app.get("/console/metrics")
    def metrics(provenance: str | None = None) -> dict:
        return console.metrics(svc.db, provenance)

    @app.get("/console/model")
    def model() -> dict:
        return console.model_metrics()

    @app.get("/console/controls")
    def get_controls() -> dict:
        return svc.controls()

    @app.post("/console/controls")
    async def post_controls(request: Request) -> JSONResponse:
        return JSONResponse(*reversed(svc.set_controls(await _json(request))))

    @app.get("/console/security-events")
    def security() -> list[dict]:
        return console.security_events(svc.db)

    @app.post("/console/reconcile")
    def reconcile() -> dict:
        return svc.reconcile(older_than_s=0)

    # -- Ask Pact assistant (doc 04 §1, doc 10 §P4) ----------------------------------------
    s = svc.s
    creds = (s.paypal_client_id, s.paypal_client_secret) if s.paypal_live else None
    assistant = AskPactAssistant(PactReadTools(
        svc.db, svc.paypal, toolkit_credentials=creds, sandbox=s.paypal_env != "live"))

    @app.post("/assistant/ask")
    async def assistant_ask(request: Request) -> JSONResponse:
        body = await _json(request)
        question = body.get("question", "").strip()
        if not question:
            return JSONResponse({"error": "question is required"}, status_code=400)
        intent_id = body.get("intent_id")
        res = assistant.ask(question, intent_id=intent_id)
        return JSONResponse(res)

    # -- Human customer (Arjun's inbox) -----------------------------------------------------
    @app.get("/store/customers/{customer_id}/inbox")
    def customer_inbox(customer_id: str) -> list[dict]:
        return svc.customer_inbox(customer_id)

    # -- Judge mode ------------------------------------------------------------------------
    def judged(fn, *args) -> JSONResponse:
        try:
            return JSONResponse(fn(*args))
        except JudgeError as exc:
            return JSONResponse({"error": str(exc)}, exc.status)

    @app.get("/judge/scenarios")
    def judge_scenarios() -> dict:
        return {k: {kk: v[kk] for kk in ("title", "channel", "story")} for k, v in SCENARIOS.items()}

    @app.post("/judge/reset")
    def judge_reset() -> JSONResponse:
        return judged(judge.reset)

    @app.post("/judge/scenarios/{scenario}/run")
    def judge_run(scenario: str) -> JSONResponse:
        return judged(judge.run, scenario)

    @app.get("/judge/linked/{intent_id}")
    def judge_linked(intent_id: str) -> JSONResponse:
        return judged(judge.linked, intent_id)

    @app.post("/judge/onboard/{token}")
    def judge_onboard(token: str) -> JSONResponse:
        return judged(judge.onboard, token)

    # -- Health ------------------------------------------------------------------------------
    @app.get("/health")
    def health() -> dict:
        return {"service": "pact-merchant", "paypal": svc.paypal.mode,
                "llm": llm.mode(), "mode": svc.control("mode"),
                "kill_switch": svc.control("kill_switch"),
                "merchant_key_id": svc.key_id, "merchant_public_key": svc.public_key_b64}

    return app


async def _json(request: Request) -> dict:
    raw = await request.body()
    return json.loads(raw) if raw else {}


def __getattr__(name: str):
    """`merchant.app:app` is built lazily, so importing this module creates no database."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
