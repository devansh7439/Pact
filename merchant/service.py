"""Merchant service: everything the HTTP layer exposes, as plain methods.

Each method returns `(status_code, body)`. Signature checks happen in the route
layer (doc 03 §3) before anything here runs; this module trusts only the
verified key id and re-derives everything else from its own database.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from merchant import catalog
from merchant.agent_api.offers import build_offer, offer_json
from merchant.config import Settings
from merchant.db import (
    Database,
    audit,
    dumps,
    get_control,
    now_iso,
    record_outcome,
    security_event,
    set_control,
)
from merchant.engine.economics import MerchantPolicy, RecoveryAction
from merchant.engine.executor import ExecutionBlocked, Executor, consent_problem
from merchant.engine.pipeline import FailureDecision, Pipeline
from merchant.integrations import llm
from merchant.paypal.types import PayPal
from shared.prp import keys, signing
from shared.prp.ids import new_id
from shared.prp.models import Acceptance, Mandate

log = logging.getLogger(__name__)
A = RecoveryAction
Result = tuple[int, dict[str, Any]]


def err(status: int, code: str, message: str = "") -> Result:
    return status, {"prp_version": "0.1", "error": {"code": code, "message": message}}


def prp_outcome(outcome: str) -> str:
    """Internal outcome -> PRP wire value (doc 03 §6). A first-try success is recorded
    as PAID internally (not a recovery) and is ORGANIC on the wire: paid with no Pact action."""
    return "ORGANIC" if outcome == "PAID" else outcome


def _req_hash(body: Any) -> str:
    return hashlib.sha256(dumps(body).encode()).hexdigest()


@dataclass
class Clock:
    fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self.fn()


class MerchantService:
    def __init__(self, settings: Settings, db: Database, paypal: PayPal, *,
                 signing_key: Ed25519PrivateKey | None = None, clock: Clock | None = None,
                 http: httpx.Client | None = None, predict=None) -> None:
        self.s, self.db, self.paypal = settings, db, paypal
        self.clock = clock or Clock()
        if signing_key is None and settings.merchant_signing_key:
            signing_key = keys.private_from_b64(settings.merchant_signing_key)
        if signing_key is None:
            log.warning("MERCHANT_SIGNING_KEY not set: using an ephemeral PRP key for this process")
            signing_key = keys.generate()
        self.key = signing_key
        self.key_id = settings.merchant_key_id
        self.public_key_b64 = keys.public_to_b64(signing_key.public_key())
        self.http = http
        self.provenance = "sandbox" if paypal.mode == "live" else "fixture"
        self.executor = Executor(db, paypal, killed=self.killed,
                                 merchant_public_url=settings.merchant_public_url)
        self.pipeline = Pipeline(db, self.policy, holdout_salt=settings.holdout_salt,
                                 holdout_rate_fn=lambda: float(self.control("holdout_rate")),
                                 kill_switch_fn=self.killed, mode_fn=lambda: self.control("mode"),
                                 predict=predict)

    # -- controls -------------------------------------------------------------
    def _defaults(self) -> dict[str, str]:
        return {"mode": "autonomous" if self.s.judge_mode else self.s.pact_mode,
                "kill_switch": "off", "ev_floor_minor": str(self.s.ev_floor_minor),
                "autonomy_ceiling_minor": str(self.s.autonomy_ceiling_minor),
                "max_recovery_attempts": str(self.s.max_recovery_attempts),
                "holdout_rate": str(self.s.holdout_rate)}

    def control(self, key: str) -> str:
        return get_control(self.db, key, self._defaults()[key])

    def controls(self) -> dict[str, Any]:
        c = {k: self.control(k) for k in self._defaults()}
        c["executes"] = c["kill_switch"] == "off" and c["mode"] == "autonomous"
        return c

    def set_controls(self, changes: dict[str, Any], actor: str = "merchant") -> Result:
        allowed = set(self._defaults())
        bad = set(changes) - allowed
        if bad:
            return 422, {"error": f"unknown controls: {sorted(bad)}"}
        if "mode" in changes and changes["mode"] not in ("review_first", "autonomous"):
            return 422, {"error": "mode must be review_first or autonomous"}
        if "kill_switch" in changes and changes["kill_switch"] not in ("on", "off"):
            return 422, {"error": "kill_switch must be on or off"}
        with self.db.tx() as conn:
            for k, v in changes.items():
                set_control(conn, k, str(v))
            audit(conn, None, "CONTROLS", {"changes": changes, "actor": actor})
        return 200, self.controls()

    def killed(self) -> bool:
        return self.control("kill_switch") == "on"

    def review_first(self) -> bool:
        return self.control("mode") == "review_first"

    def policy(self) -> MerchantPolicy:
        return MerchantPolicy(min_net_ev_minor=int(self.control("ev_floor_minor")),
                              max_autonomous_amount_minor=int(self.control("autonomy_ceiling_minor")),
                              max_attempts_per_payment=int(self.control("max_recovery_attempts")),
                              contribution_margin=self.s.contribution_margin)

    # -- PRP key resolution ----------------------------------------------------
    def agent_key(self, key_id: str):
        row = self.db.one("SELECT agent_public_key, status FROM agent_registrations WHERE key_id=?",
                          (key_id,))
        if row is None or row["status"] == "REVOKED":
            return None
        return keys.public_from_b64(row["agent_public_key"])

    def agent_for_key(self, key_id: str):
        return self.db.one("SELECT * FROM agent_registrations WHERE key_id=?", (key_id,))

    def sign(self, method: str, path: str, body: Any) -> signing.SignedMessage:
        return signing.sign(self.key, self.key_id, method, path, body)

    # -- idempotency -------------------------------------------------------------
    def _replay(self, scope: str, key: str, body: Any) -> Result | None:
        row = self.db.one("SELECT * FROM idempotency WHERE scope=? AND key=?", (scope, key))
        if row is None:
            return None
        if row["request_hash"] != _req_hash(body):
            return err(409, "OFFER_ALREADY_ACCEPTED" if scope == "accept" else "INVALID_OPTION",
                       "idempotency key reused with a different body")
        return row["status_code"], json.loads(row["response_json"])

    def _remember(self, scope: str, key: str, body: Any, result: Result) -> Result:
        with self.db.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO idempotency VALUES (?,?,?,?,?,?)",
                         (scope, key, _req_hash(body), result[0], dumps(result[1]), now_iso()))
        return result

    # =========================================================================
    # Registration & onboarding (doc 01 flow A)
    # =========================================================================
    def register(self, key_id: str, body: dict) -> Result:
        try:
            mandate = Mandate.model_validate(body.get("mandate"))
            agent_id, agent_key_id = body["agent_id"], body["agent_key_id"]
            public_b64 = body["agent_public_key"]
            keys.public_from_b64(public_b64)
        except (KeyError, ValidationError, ValueError) as exc:
            return err(422, "INVALID_OPTION", f"bad registration: {exc}")
        if agent_key_id != key_id:
            return err(401, "BAD_SIGNATURE", "agent_key_id must match the signing key id")
        if self.s.merchant_id not in mandate.merchant_scope:
            return err(403, "OUTSIDE_MANDATE", "mandate does not include this merchant")
        existing = self.db.one("SELECT * FROM agent_registrations WHERE agent_id=?", (agent_id,))
        if existing is not None:
            # Same key that just signed this request: the agent is reconnecting (e.g. its
            # store was wiped on a cold start). Return the registration as it stands,
            # whatever its status. A different key for the same agent_id is still a 409.
            if existing["agent_public_key"] == public_b64 and existing["status"] != "REVOKED":
                return 201, self._registration_body(existing)
            return err(409, "INVALID_OPTION", "agent already registered")
        token = new_id("onb")
        customer_id = new_id("cus")
        with self.db.tx() as conn:
            conn.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?)",
                         (customer_id, mandate.principal.display_name, None,
                          mandate.principal.paypal_payer_id, "agent", 0, now_iso()))
            conn.execute("INSERT INTO agent_registrations VALUES (?,?,?,?,?,?,?,?,?)",
                         (agent_id, customer_id, public_b64, agent_key_id, body.get("callback_url"),
                          "PENDING_APPROVAL", token,
                          dumps(mandate.model_dump(mode="json", exclude_none=True)), now_iso()))
            audit(conn, None, "REGISTER", {"agent_id": agent_id, "key_id": agent_key_id,
                                           "mandate_id": mandate.mandate_id})
        return 201, self._registration_body(self.db.one(
            "SELECT * FROM agent_registrations WHERE agent_id=?", (agent_id,)))

    def _registration_body(self, reg) -> dict:
        return {"prp_version": "0.1", "agent_id": reg["agent_id"], "merchant_id": self.s.merchant_id,
                "merchant_name": self.s.merchant_name, "merchant_public_key": self.public_key_b64,
                "merchant_key_id": self.key_id,
                "approval_url": f"{self.s.web_public_url.rstrip('/')}/onboard/{reg['onboarding_token']}",
                "registration_status": reg["status"]}

    def _reg_by_token(self, token: str):
        return self.db.one("SELECT * FROM agent_registrations WHERE onboarding_token=?", (token,))

    def onboarding(self, token: str) -> Result:
        reg = self._reg_by_token(token)
        if reg is None:
            return 404, {"error": "unknown onboarding token"}
        mandate = json.loads(reg["draft_mandate_json"])
        saved = [dict(alias=r["alias"], kind=r["kind"], status=r["status"]) for r in self.db.query(
            "SELECT alias, kind, status FROM funding_sources WHERE customer_id=?", (reg["customer_id"],))]
        return 200, {"merchant": {"id": self.s.merchant_id, "name": self.s.merchant_name},
                     "agent_id": reg["agent_id"], "status": reg["status"], "mandate": mandate,
                     "saved_funding": saved,
                     "missing_funding": [f["alias"] for f in mandate["funding"]
                                         if f["alias"] not in {s["alias"] for s in saved}]}

    def onboarding_vault(self, token: str, alias: str) -> Result:
        reg = self._reg_by_token(token)
        if reg is None:
            return 404, {"error": "unknown onboarding token"}
        mandate = json.loads(reg["draft_mandate_json"])
        f = next((f for f in mandate["funding"] if f["alias"] == alias), None)
        if f is None:
            return 422, {"error": f"{alias} is not in the mandate"}
        st = self.paypal.create_setup_token(
            customer_id=reg["customer_id"], kind=f["kind"], request_id=f"setup_{token}_{alias}",
            return_url=f"{self.s.merchant_public_url}/paypal/return?onboarding={token}&alias={alias}",
            cancel_url=f"{self.s.web_public_url}/onboard/{token}?cancelled=1")
        return 200, {"approve_url": st.approve_url, "setup_token": st.token_id}

    def onboarding_saved(self, token: str, alias: str, setup_token_id: str) -> Result:
        reg = self._reg_by_token(token)
        if reg is None:
            return 404, {"error": "unknown onboarding token"}
        mandate = json.loads(reg["draft_mandate_json"])
        f = next((f for f in mandate["funding"] if f["alias"] == alias), None)
        if f is None:
            return 422, {"error": f"{alias} is not in the mandate"}
        pt = self.paypal.create_payment_token(setup_token_id=setup_token_id,
                                              customer_id=reg["customer_id"],
                                              request_id=f"ptok_{setup_token_id}")
        self.save_funding(reg["customer_id"], alias, f["kind"], pt.vault_id)
        return 200, {"alias": alias, "saved": True}

    def save_funding(self, customer_id: str, alias: str, kind: str, vault_id: str) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT INTO funding_sources VALUES (?,?,?,?,?,?) ON CONFLICT(customer_id, alias) "
                         "DO UPDATE SET vault_id=excluded.vault_id, status='ACTIVE'",
                         (customer_id, alias, kind, vault_id, "ACTIVE", now_iso()))
            audit(conn, None, "VAULT", {"customer_id": customer_id, "alias": alias, "kind": kind})

    def onboarding_confirm(self, token: str, payer_id: str | None = None) -> Result:
        reg = self._reg_by_token(token)
        if reg is None:
            return 404, {"error": "unknown onboarding token"}
        if reg["status"] == "ACTIVE":
            return 200, {"status": "ACTIVE"}
        mandate = json.loads(reg["draft_mandate_json"])
        saved = {r["alias"] for r in self.db.query(
            "SELECT alias FROM funding_sources WHERE customer_id=? AND status='ACTIVE'",
            (reg["customer_id"],))}
        if not saved:
            return 409, {"error": "save at least one funding source with PayPal first"}
        approval_ref = new_id("onb")
        with self.db.tx() as conn:
            conn.execute("INSERT INTO registered_mandates VALUES (?,?,?,?,?,?,?)",
                         (mandate["mandate_id"], reg["agent_id"], dumps(mandate), payer_id,
                          now_iso(), approval_ref, mandate["expires_at"]))
            conn.execute("UPDATE agent_registrations SET status='ACTIVE' WHERE agent_id=?",
                         (reg["agent_id"],))
            audit(conn, None, "MANDATE_APPROVED", {"agent_id": reg["agent_id"],
                                                   "mandate_id": mandate["mandate_id"],
                                                   "approval_ref": approval_ref,
                                                   "payer_id": payer_id})
        self._post_callback(reg["agent_id"], {"prp_version": "0.1", "event": "registration.active",
                                              "mandate_id": mandate["mandate_id"]})
        return 200, {"status": "ACTIVE", "mandate_id": mandate["mandate_id"],
                     "approval_ref": approval_ref, "saved_funding": sorted(saved)}

    # =========================================================================
    # Agent checkout (doc 01 flow B)
    # =========================================================================
    def checkout(self, key_id: str, body: dict) -> Result:
        reg = self.agent_for_key(key_id)
        idem = body.get("idempotency_key")
        if not idem:
            return err(422, "INVALID_OPTION", "idempotency_key is required")
        scope_key = f"{reg['agent_id']}:{idem}"
        if (replay := self._replay("checkout", scope_key, body)) is not None:
            return replay
        if reg["status"] != "ACTIVE":
            return err(403, "OUTSIDE_MANDATE", "registration is not active")
        mdt = self.db.one("SELECT * FROM registered_mandates WHERE mandate_id=? AND agent_id=?",
                          (body.get("mandate_id"), reg["agent_id"]))
        if mdt is None:
            return err(403, "OUTSIDE_MANDATE", "unknown mandate for this agent")
        caps = json.loads(mdt["caps_json"])
        sku, qty = body.get("sku"), body.get("quantity", 1)
        amount = body.get("amount") or {}
        expected = catalog.price(sku, qty) if isinstance(qty, int) else None
        if expected is None:
            return err(422, "INVALID_OPTION", "unknown sku or bad quantity")
        if amount.get("value_minor") != expected or amount.get("currency_code") != caps["currency_code"]:
            return err(422, "INVALID_OPTION", f"amount must be {expected} {caps['currency_code']}")
        # The merchant's own copy of the human-approved caps (two guardrails).
        reason = None
        if datetime.fromisoformat(mdt["expires_at"]) <= self.clock.now():
            reason = "mandate expired"
        elif expected > caps["per_purchase_cap_minor"]:
            reason = "over the per-purchase cap"
        elif catalog.CATALOG[sku]["category"] not in caps["allowed_categories"]:
            reason = "category not allowed"
        elif body.get("funding_alias") not in {f["alias"] for f in caps["funding"]}:
            reason = "funding alias not in mandate"
        elif self._spent(mdt["mandate_id"], caps) + expected > caps["budget"]["limit_minor"]:
            reason = "over the period budget"
        if reason:
            return self._remember("checkout", scope_key, body, err(403, "OUTSIDE_MANDATE", reason))
        if self.killed():
            return err(503, "KILL_SWITCH_ACTIVE", "kill switch is on")

        intent_id = new_id("pi")
        with self.db.tx() as conn:
            conn.execute("INSERT INTO payment_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (intent_id, reg["customer_id"], "agent", reg["agent_id"], mdt["mandate_id"],
                          expected, caps["currency_code"],
                          dumps([{"sku": sku, "quantity": qty}]), "ATTEMPTING", None,
                          self.provenance, now_iso(), now_iso()))
            audit(conn, intent_id, "CHECKOUT", {"agent_id": reg["agent_id"], "sku": sku,
                                                "quantity": qty, "amount_minor": expected,
                                                "funding_alias": body["funding_alias"]})
        result = self._attempt_and_decide(intent_id, body["funding_alias"], f"att_{intent_id}_1",
                                          paid_outcome="PAID", action_id=None)
        return self._remember("checkout", scope_key, body, result)

    # -- Human channel: merchant-initiated reorder on a saved card (flow D) -----
    def merchant_charge(self, customer_id: str, sku: str, alias: str, quantity: int = 1,
                        request_id: str | None = None) -> Result:
        """Charge a human customer's saved method for a reorder they set up (S4, S6)."""
        amount = catalog.price(sku, quantity)
        if amount is None:
            return 422, {"error": "unknown sku"}
        if self.killed():
            return err(503, "KILL_SWITCH_ACTIVE", "kill switch is on")
        intent_id = new_id("pi")
        with self.db.tx() as conn:
            conn.execute("INSERT INTO payment_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (intent_id, customer_id, "human", None, None, amount, "USD",
                          dumps([{"sku": sku, "quantity": quantity}]), "ATTEMPTING", None,
                          self.provenance, now_iso(), now_iso()))
            audit(conn, intent_id, "CHECKOUT", {"customer_id": customer_id, "sku": sku,
                                                "amount_minor": amount, "funding_alias": alias,
                                                "initiated_by": "merchant"})
        status, body = self._attempt_and_decide(intent_id, alias, request_id or f"att_{intent_id}_1",
                                                paid_outcome="PAID", action_id=None)
        return status, {"intent_id": intent_id, **body}

    def customer_inbox(self, customer_id: str) -> list[dict]:
        """What a human customer (Arjun) received: recovery messages with PayPal links."""
        rows = self.db.query(
            "SELECT a.action_id, a.message_text, a.approve_url, a.status, a.created_at, "
            "p.intent_id, p.amount_minor, p.currency_code, o.outcome FROM actions a "
            "JOIN decisions d ON d.decision_id=a.decision_id "
            "JOIN payment_intents p ON p.intent_id=d.intent_id "
            "LEFT JOIN outcomes o ON o.intent_id=p.intent_id "
            "WHERE p.customer_id=? AND a.kind='CHECKOUT_LINK' ORDER BY a.created_at DESC",
            (customer_id,))
        return [dict(r) for r in rows]

    def _spent(self, mandate_id: str, caps: dict) -> int:
        days = {"DAY": 1, "WEEK": 7, "MONTH": 30}[caps["budget"]["period"]]
        since = (self.clock.now() - timedelta(days=days)).isoformat(timespec="seconds")
        row = self.db.one(
            "SELECT COALESCE(SUM(o.recovered_minor),0) s FROM outcomes o "
            "JOIN payment_intents p ON p.intent_id=o.intent_id "
            "WHERE p.mandate_id=? AND o.created_at>=?", (mandate_id, since))
        return row["s"]

    def _attempt_and_decide(self, intent_id: str, alias: str, request_id: str, *,
                            paid_outcome: str, action_id: str | None) -> Result:
        try:
            att = self.executor.charge(intent_id, alias, request_id)
        except ExecutionBlocked as exc:
            return err(503 if exc.code == "KILL_SWITCH_ACTIVE" else 403, exc.code, str(exc))
        if att.result.paid:
            self.finalize(intent_id, att.result.capture_id, "api", paid_outcome, action_id)
            return 200, self._receipt(intent_id, att.result.order_id)
        if att.result.status == "ERROR":
            return err(502, "PAYPAL_ERROR", att.result.description or "PayPal unavailable")
        fd = self.pipeline.on_failure(intent_id, att.attempt_id)
        return self.act(intent_id, fd, att.funding_alias)

    def _receipt(self, intent_id: str, order_id: str | None) -> dict:
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        return {"prp_version": "0.1", "intent_id": intent_id, "status": "COMPLETED",
                "paypal_order_id": order_id,
                "amount": {"currency_code": intent["currency_code"],
                           "value_minor": intent["amount_minor"]}}

    # -- ACT --------------------------------------------------------------------
    def act(self, intent_id: str, fd: FailureDecision, failed_alias: str | None) -> Result:
        intent = dict(self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,)))
        d = fd.decision
        action_id = new_id("act")
        if intent["channel"] == "agent":
            offer = build_offer(
                intent=intent, decision=d, decision_id=fd.decision_id,
                classification=fd.classification, failed_alias=failed_alias or "unknown",
                merchant_id=self.s.merchant_id, merchant_name=self.s.merchant_name,
                now=self.clock.now(), ttl_seconds=self.s.offer_ttl_seconds,
                retry_after_hours=d.retry_after_hours)
            body = offer_json(offer)
            state = {"DROP": "HELD_OUT" if fd.held_out else "DROPPED",
                     "ESCALATE": "ESCALATED"}.get(d.action.value, "OFFERED")
            with self.db.tx() as conn:
                conn.execute("UPDATE offers SET status='SUPERSEDED' WHERE intent_id=? AND status='OPEN'",
                             (intent_id,))
                conn.execute("INSERT INTO offers VALUES (?,?,?,?,?,?,?)",
                             (offer.offer_id, intent_id, fd.decision_id,
                              signing.canonical_json(body).decode(), body["expires_at"], "OPEN", None))
                conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
                             (action_id, fd.decision_id, "OFFER", None, None, None, "SENT", now_iso()))
                if d.action is A.ESCALATE:
                    conn.execute("UPDATE decisions SET review_status='PENDING' WHERE decision_id=?",
                                 (fd.decision_id,))
                conn.execute("UPDATE payment_intents SET state=?, updated_at=? WHERE intent_id=?",
                             (state, now_iso(), intent_id))
                audit(conn, intent_id, "ACT", {"kind": "OFFER", "offer_id": offer.offer_id,
                                               "options": [o["option_id"] for o in body["options"]],
                                               "decision_action": d.action.value})
            return 402, body

        # Human channel: one action.
        status, approve_url, text, order_id = "RECORDED", None, None, None
        if d.action is A.CHECKOUT_LINK:
            if self.review_first():
                status = "PENDING_REVIEW"
            elif d.execution_blocked_by:
                status = "BLOCKED"
            else:
                try:
                    att = self.executor.payer_order(intent_id, f"link_{fd.decision_id}")
                    approve_url, order_id = att.result.approve_url, att.result.order_id
                    customer = self.db.one("SELECT display_name FROM customers WHERE customer_id=?",
                                           (intent["customer_id"],))
                    msg = llm.generate_message(customer["display_name"], intent["amount_minor"],
                                               fd.classification.failure_class.value, d.action,
                                               approve_url, intent["currency_code"],
                                               allow_live=intent["provenance"] != "simulated")
                    text, status = msg.text, "SENT"
                except ExecutionBlocked:
                    status = "BLOCKED"
        elif d.action is A.ESCALATE:
            status = "PENDING_REVIEW"
        state = {"CHECKOUT_LINK": "LINK_SENT", "ESCALATE": "ESCALATED"}.get(
            d.action.value, "HELD_OUT" if fd.held_out else "DROPPED")
        with self.db.tx() as conn:
            conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
                         (action_id, fd.decision_id, d.action.value, order_id, approve_url, text,
                          status, now_iso()))
            if status == "PENDING_REVIEW":
                conn.execute("UPDATE decisions SET review_status='PENDING' WHERE decision_id=?",
                             (fd.decision_id,))
            conn.execute("UPDATE payment_intents SET state=?, updated_at=? WHERE intent_id=?",
                         (state, now_iso(), intent_id))
            audit(conn, intent_id, "ACT", {"kind": d.action.value, "status": status,
                                           "order_id": order_id})
        return 200, {"intent_id": intent_id, "action": d.action.value, "status": status,
                     "approve_url": approve_url, "message": text}

    # =========================================================================
    # Offers (doc 03 §5) — checks in the documented order
    # =========================================================================
    def get_offer(self, key_id: str, offer_id: str) -> Result:
        offer, problem = self._offer_for_agent(key_id, offer_id)
        if problem:
            return problem
        if self._expired(offer):
            return err(410, "OFFER_EXPIRED", "offer expired")
        return 200, json.loads(offer["body_json"])

    def _offer_for_agent(self, key_id: str, offer_id: str):
        reg = self.agent_for_key(key_id)
        offer = self.db.one(
            "SELECT o.* FROM offers o JOIN payment_intents p ON p.intent_id=o.intent_id "
            "WHERE o.offer_id=? AND p.agent_id=?", (offer_id, reg["agent_id"]))
        return offer, (None if offer else err(404, "INVALID_OPTION", "unknown offer"))

    def _expired(self, offer) -> bool:
        return datetime.fromisoformat(offer["expires_at"]) <= self.clock.now()

    def accept(self, key_id: str, offer_id: str, body: dict) -> Result:
        try:
            acc = Acceptance.model_validate(body)
        except ValidationError as exc:
            return err(422, "INVALID_OPTION", str(exc.errors()[0]["msg"]))
        if acc.offer_id != offer_id:
            return err(422, "INVALID_OPTION", "offer_id in body does not match the path")
        reg = self.agent_for_key(key_id)
        if (replay := self._replay("accept", f"{reg['agent_id']}:{acc.idempotency_key}", body)):
            return replay
        # 2. offer exists, unexpired, not already accepted; option belongs to it.
        offer, problem = self._offer_for_agent(key_id, offer_id)
        if problem:
            return problem
        if self._expired(offer):
            with self.db.tx() as conn:
                conn.execute("UPDATE offers SET status='EXPIRED' WHERE offer_id=? AND status='OPEN'",
                             (offer_id,))
            return err(410, "OFFER_EXPIRED", "offer expired; nothing was created")
        prior = self.db.one("SELECT * FROM actions WHERE action_id=?", (f"acc_{offer_id}",))
        if offer["status"] == "ACCEPTED" and offer["accepted_option_id"] == acc.option_id and prior:
            return 200, json.loads(prior["message_text"])           # I8: same accept, same result
        if offer["status"] != "OPEN":
            return err(409, "OFFER_ALREADY_ACCEPTED", f"offer is {offer['status']}")
        offer_body = json.loads(offer["body_json"])
        option = next((o for o in offer_body["options"] if o["option_id"] == acc.option_id), None)
        if option is None:
            return err(422, "INVALID_OPTION", "option not in this offer")
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (offer["intent_id"],))
        if acc.mandate_id != intent["mandate_id"]:
            return err(422, "INVALID_OPTION", "mandate does not match the intent")
        kind = option["kind"]
        # 3. alias allowed for this option, and not the failed one.
        if kind in ("ALTERNATE_FUNDING", "RETRY_AFTER"):
            failed = offer_body["failure"]["failed_funding_alias"]
            if (acc.funding_alias is None or acc.funding_alias not in option["eligible_funding_aliases"]
                    or (acc.funding_alias == failed
                        and not offer_body["failure"]["retry_same_instrument"])):
                return err(422, "ALIAS_NOT_ALLOWED", "funding alias not allowed for this option")
            # 4. consent (re-run again inside the executor, immediately before PayPal).
            if problem := consent_problem(self.db, intent["intent_id"], acc.funding_alias):
                return err(403, "CONSENT_INVALID", problem)
        # 5. kill switch.
        if self.killed():
            return err(503, "KILL_SWITCH_ACTIVE", "kill switch is on")

        with self.db.tx() as conn:
            cur = conn.execute("UPDATE offers SET status='ACCEPTED', accepted_option_id=? "
                               "WHERE offer_id=? AND status='OPEN'", (acc.option_id, offer_id))
            if not cur.rowcount:                                     # lost a race
                return err(409, "OFFER_ALREADY_ACCEPTED", "offer already accepted")
            audit(conn, intent["intent_id"], "ACCEPT", {"offer_id": offer_id,
                                                         "option_id": acc.option_id,
                                                         "alias": acc.funding_alias,
                                                         "agent_decision_ref": acc.agent_decision_ref})
        result = self._execute_option(intent["intent_id"], offer_id, offer["decision_id"], option,
                                      acc.funding_alias)
        with self.db.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO actions VALUES (?,?,?,?,?,?,?,?)",
                         (f"acc_{offer_id}", offer["decision_id"], f"ACCEPT_{kind}", None, None,
                          dumps(result[1]), str(result[0]), now_iso()))
        return self._remember("accept", f"{reg['agent_id']}:{acc.idempotency_key}", body, result)

    def _execute_option(self, intent_id: str, offer_id: str, decision_id: str, option: dict,
                        alias: str | None) -> Result:
        kind, option_id = option["kind"], option["option_id"]
        request_id = f"acc_{offer_id}_{option_id}"                   # derived from (offer, option)
        if kind == "CANCEL":
            self.finalize(intent_id, None, "api", "LOST", None)
            return 200, {"prp_version": "0.1", "intent_id": intent_id, "status": "CANCELLED"}
        if kind == "PAYER_ACTION":
            try:
                att = self.executor.payer_order(intent_id, request_id)
            except ExecutionBlocked as exc:
                return err(503, exc.code, str(exc))
            with self.db.tx() as conn:
                conn.execute("UPDATE payment_intents SET state='ESCALATED_TO_HUMAN', updated_at=? "
                             "WHERE intent_id=?", (now_iso(), intent_id))
            return 202, {"prp_version": "0.1", "intent_id": intent_id, "status": "PAYER_ACTION_REQUIRED",
                         "approve_url": att.result.approve_url, "expires_at":
                         self.db.one("SELECT expires_at FROM offers WHERE offer_id=?",
                                     (offer_id,))["expires_at"]}
        if kind == "RETRY_AFTER" and datetime.fromisoformat(option["not_before"]) > self.clock.now():
            with self.db.tx() as conn:
                conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
                             (f"sched_{offer_id}", decision_id, "RETRY_AFTER", None, None,
                              dumps({"alias": alias, "not_before": option["not_before"],
                                     "request_id": request_id}), "SCHEDULED", now_iso()))
            return 202, {"prp_version": "0.1", "intent_id": intent_id, "status": "SCHEDULED",
                         "not_before": option["not_before"]}
        if self.review_first():
            with self.db.tx() as conn:
                conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
                             (f"rev_{offer_id}", decision_id, "ACCEPTED_CHARGE", None, None,
                              dumps({"alias": alias, "request_id": request_id}), "PENDING_REVIEW",
                              now_iso()))
                conn.execute("UPDATE decisions SET review_status='PENDING' WHERE decision_id=?",
                             (decision_id,))
            return 202, {"prp_version": "0.1", "intent_id": intent_id, "status": "PENDING_REVIEW"}
        return self._attempt_and_decide(intent_id, alias, request_id, paid_outcome="RECOVERED",
                                        action_id=f"acc_{offer_id}")

    def decline(self, key_id: str, offer_id: str, body: dict) -> Result:
        offer, problem = self._offer_for_agent(key_id, offer_id)
        if problem:
            return problem
        if self._expired(offer):
            return err(410, "OFFER_EXPIRED", "offer expired")
        with self.db.tx() as conn:
            conn.execute("UPDATE offers SET status='DECLINED' WHERE offer_id=? AND status='OPEN'",
                         (offer_id,))
        self.finalize(offer["intent_id"], None, "api", "LOST", None)
        return 200, {"prp_version": "0.1", "offer_id": offer_id, "status": "DECLINED"}

    def get_intent(self, key_id: str | None, intent_id: str) -> Result:
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        if intent is None:
            return err(404, "INVALID_OPTION", "unknown intent")
        if key_id is not None:
            reg = self.agent_for_key(key_id)
            if intent["agent_id"] != reg["agent_id"]:
                return err(404, "INVALID_OPTION", "unknown intent")
        out = self.db.one("SELECT * FROM outcomes WHERE intent_id=?", (intent_id,))
        return 200, {"prp_version": "0.1", "intent_id": intent_id, "state": intent["state"],
                     "outcome": prp_outcome(out["outcome"]) if out else "PENDING",
                     "amount": {"currency_code": intent["currency_code"],
                                "value_minor": intent["amount_minor"]}}

    # =========================================================================
    # VERIFY → MEASURE
    # =========================================================================
    def finalize(self, intent_id: str, capture_id: str | None, source: str, outcome: str,
                 action_id: str | None) -> bool:
        """Record the outcome once (I15) and tell the agent, if it registered a callback."""
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        held = self.db.one("SELECT 1 FROM decisions WHERE intent_id=? AND held_out=1", (intent_id,))
        if outcome == "RECOVERED" and held:
            outcome = "ORGANIC"
        with self.db.tx() as conn:
            first = record_outcome(conn, intent_id, outcome, source,
                                   0 if outcome == "LOST" else intent["amount_minor"],
                                   capture_id, action_id)
            if first and outcome == "LOST":
                conn.execute("UPDATE payment_intents SET state='LOST' WHERE intent_id=?", (intent_id,))
            if first:
                audit(conn, intent_id, "VERIFY", {"source": source, "capture_id": capture_id})
        if first:
            self._callback(intent_id, outcome)
        return first

    def outcome_for_order(self, order_id: str) -> tuple[str, str | None]:
        """Attribute a paid order to what caused it (doc 03 §6)."""
        att = self.db.one("SELECT * FROM attempts WHERE paypal_order_id=?", (order_id,))
        if att is None:
            return "PAID", None
        rid = att["request_id"]
        if rid.startswith("acc_") and att["funding_alias"] is None:
            return "RECOVERED_BY_HUMAN", rid
        if rid.startswith("acc_") or rid.startswith("link_"):
            return "RECOVERED", rid
        return "PAID", None

    def on_paid_order(self, order_id: str, capture_id: str | None, source: str) -> bool:
        att = self.db.one("SELECT intent_id FROM attempts WHERE paypal_order_id=?", (order_id,))
        if att is None:
            return False
        outcome, action = self.outcome_for_order(order_id)
        return self.finalize(att["intent_id"], capture_id, source, outcome, action)

    def capture_approved(self, order_id: str, source: str) -> Result:
        att = self.db.one("SELECT intent_id FROM attempts WHERE paypal_order_id=?", (order_id,))
        if att is None:
            return 404, {"error": "unknown order"}
        if self.db.one("SELECT 1 FROM outcomes WHERE intent_id=?", (att["intent_id"],)):
            return 200, {"status": "ALREADY_PAID"}                 # never capture twice (I1)
        try:
            res = self.executor.capture(att["intent_id"], order_id)
        except ExecutionBlocked as exc:
            return err(503, exc.code, str(exc))
        if res.result.paid:
            self.on_paid_order(order_id, res.result.capture_id, source)
        return 200, {"status": res.result.status}

    def webhook(self, headers: dict[str, str], raw: bytes) -> Result:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return 400, {"error": "bad json"}
        verified = self.paypal.verify_webhook(headers, event)
        event_id = event.get("id") or new_id("whk")
        with self.db.tx() as conn:
            cur = conn.execute("INSERT OR IGNORE INTO webhook_events VALUES (?,?,?,?,?)",
                               (event_id, event.get("event_type", "?"), int(verified), now_iso(),
                                raw.decode("utf-8", "replace")))
            duplicate = not cur.rowcount
            if not verified:
                security_event(conn, "WEBHOOK_UNVERIFIED", {"event_id": event_id,
                                                            "event_type": event.get("event_type")})
                audit(conn, None, "WEBHOOK_REJECTED", {"event_id": event_id})
        if not verified:
            return 400, {"error": "webhook signature not verified"}        # stored, never acted on
        if duplicate:
            return 200, {"status": "duplicate"}
        resource = event.get("resource") or {}
        etype = event.get("event_type")
        if etype == "PAYMENT.CAPTURE.COMPLETED":
            order_id = ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
            if order_id:
                self.on_paid_order(order_id, resource.get("id"), "webhook")
        elif etype == "CHECKOUT.ORDER.APPROVED" and resource.get("id"):
            self.capture_approved(resource["id"], "webhook")
        return 200, {"status": "ok"}

    def reconcile(self, older_than_s: int = 60) -> dict[str, int]:
        """Poll open attempts (webhook fallback), run due RETRY_AFTER accepts, expire offers."""
        stats = {"polled": 0, "captured": 0, "retried": 0, "expired": 0}
        cutoff = (self.clock.now() - timedelta(seconds=older_than_s)).isoformat(timespec="seconds")
        for att in self.db.query(
                "SELECT a.* FROM attempts a LEFT JOIN outcomes o ON o.intent_id=a.intent_id "
                "WHERE o.intent_id IS NULL AND a.paypal_order_id IS NOT NULL "
                "AND a.status IN ('PAYER_ACTION_REQUIRED','PENDING','APPROVED') AND a.created_at<=?",
                (cutoff,)):
            stats["polled"] += 1
            res = self.paypal.get_order(att["paypal_order_id"])
            if res.status == "APPROVED":
                if self.capture_approved(att["paypal_order_id"], "poll")[1].get("status") == "COMPLETED":
                    stats["captured"] += 1
            elif res.paid:
                self.on_paid_order(att["paypal_order_id"], res.capture_id, "poll")
                stats["captured"] += 1
        now = self.clock.now().isoformat()
        for act in self.db.query("SELECT * FROM actions WHERE kind='RETRY_AFTER' AND status='SCHEDULED'"):
            info = json.loads(act["message_text"])
            if info["not_before"] <= now:
                d = self.db.one("SELECT intent_id FROM decisions WHERE decision_id=?", (act["decision_id"],))
                with self.db.tx() as conn:
                    conn.execute("UPDATE actions SET status='EXECUTED' WHERE action_id=?",
                                 (act["action_id"],))
                self._attempt_and_decide(d["intent_id"], info["alias"], info["request_id"],
                                         paid_outcome="RECOVERED", action_id=act["action_id"])
                stats["retried"] += 1
        with self.db.tx() as conn:
            stats["expired"] = conn.execute(
                "UPDATE offers SET status='EXPIRED' WHERE status='OPEN' AND expires_at<=?",
                (now,)).rowcount
        return stats

    def _callback(self, intent_id: str, outcome: str) -> None:
        intent = self.db.one("SELECT agent_id FROM payment_intents WHERE intent_id=?", (intent_id,))
        if intent and intent["agent_id"]:
            self._post_callback(intent["agent_id"], {"prp_version": "0.1", "event": "intent.updated",
                                                     "intent_id": intent_id,
                                                     "outcome": prp_outcome(outcome)})

    def _post_callback(self, agent_id: str, body: dict) -> None:
        """Signed push to the agent's callback_url. Best effort: agents must also poll."""
        if self.http is None:
            return
        reg = self.db.one("SELECT callback_url FROM agent_registrations WHERE agent_id=?", (agent_id,))
        if not reg or not reg["callback_url"]:
            return
        url = httpx.URL(reg["callback_url"])
        msg = self.sign("POST", url.path, body)
        try:
            self.http.post(str(url), content=msg.body, headers=msg.headers, timeout=10)
        except httpx.HTTPError as exc:                     # agents must also work by polling
            log.warning("callback to %s failed: %s", url, exc)

    # =========================================================================
    # Review queue (review-first mode)
    # =========================================================================
    def review_queue(self) -> list[dict]:
        rows = self.db.query(
            "SELECT d.decision_id, d.intent_id, d.chosen_action, d.nev_minor, p.amount_minor, "
            "p.channel, d.created_at FROM decisions d JOIN payment_intents p ON p.intent_id=d.intent_id "
            "WHERE d.review_status='PENDING' ORDER BY d.created_at")
        return [dict(r) for r in rows]

    def review(self, decision_id: str, approve: bool, actor: str = "merchant") -> Result:
        d = self.db.one("SELECT * FROM decisions WHERE decision_id=? AND review_status='PENDING'",
                        (decision_id,))
        if d is None:
            return 404, {"error": "no pending review for that decision"}
        with self.db.tx() as conn:
            conn.execute("UPDATE decisions SET review_status=? WHERE decision_id=?",
                         ("APPROVED" if approve else "REJECTED", decision_id))
            audit(conn, d["intent_id"], "REVIEW", {"decision_id": decision_id, "approve": approve,
                                                   "actor": actor})
        if not approve:
            return 200, {"status": "REJECTED"}
        pending = self.db.one("SELECT * FROM actions WHERE decision_id=? AND status='PENDING_REVIEW'",
                              (decision_id,))
        if pending is None:
            return 200, {"status": "APPROVED", "executed": None}
        with self.db.tx() as conn:
            conn.execute("UPDATE actions SET status='APPROVED' WHERE action_id=?", (pending["action_id"],))
        if pending["kind"] == "ACCEPTED_CHARGE":
            info = json.loads(pending["message_text"])
            return self._attempt_and_decide(d["intent_id"], info["alias"], info["request_id"],
                                            paid_outcome="RECOVERED", action_id=pending["action_id"])
        if pending["kind"] == "CHECKOUT_LINK":
            try:
                att = self.executor.payer_order(d["intent_id"], f"link_{decision_id}")
            except ExecutionBlocked as exc:
                return err(503, exc.code, str(exc))
            with self.db.tx() as conn:
                conn.execute("UPDATE actions SET status='SENT', paypal_order_id=?, approve_url=? "
                             "WHERE action_id=?", (att.result.order_id, att.result.approve_url,
                                                    pending["action_id"]))
            return 200, {"status": "APPROVED", "approve_url": att.result.approve_url}
        return 200, {"status": "APPROVED", "executed": None}
