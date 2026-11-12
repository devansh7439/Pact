"""Live decision pipeline for one failed attempt (doc 05):

    INGEST → DIAGNOSE → SCORE → DECIDE → HOLDOUT        (here; one audit row each)
    ACT                                                  (service: offer / link / queue)
    VERIFY → MEASURE                                     (verification.py)

The engine's `RecoveryContext` is built from recorded state, never from what the
caller claims: failed aliases come from `attempts`, consent from
`executor.consent_problem`, contact history from `actions`, the kill switch from
`controls`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from merchant.db import Database, audit, dumps, now_iso
from merchant.engine import diagnosis, holdout
from merchant.engine.economics import MerchantPolicy
from merchant.engine.executor import consent_problem
from merchant.engine.policy import Channel, FundingSource, PolicyDecision, RecoveryContext, decide
from merchant.engine.taxonomy import Classification, classify
from shared.prp.ids import new_id

log = logging.getLogger(__name__)

#: Used when no trained model is on disk (fresh clone). Labelled in the audit row.
FALLBACK_PROPENSITY = 0.6


@dataclass(frozen=True, slots=True)
class FailureDecision:
    decision_id: str
    decision: PolicyDecision
    classification: Classification
    held_out: bool
    propensity: float
    propensity_source: str


class Pipeline:
    def __init__(self, db: Database, policy_fn, *, holdout_salt: str, holdout_rate_fn,
                 kill_switch_fn, mode_fn, predict=None) -> None:
        self.db = db
        self._policy: callable = policy_fn          # () -> MerchantPolicy (controls are live)
        self.salt = holdout_salt
        self._rate = holdout_rate_fn
        self._kill = kill_switch_fn
        self._mode = mode_fn
        self._predict = predict

    # -- context --------------------------------------------------------------
    def context(self, intent_id: str) -> RecoveryContext:
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        customer = self.db.one("SELECT * FROM customers WHERE customer_id=?", (intent["customer_id"],))
        failed = tuple(dict.fromkeys(
            r["funding_alias"] for r in self.db.query(
                "SELECT funding_alias FROM attempts WHERE intent_id=? AND status='DECLINED' "
                "AND funding_alias IS NOT NULL ORDER BY created_at", (intent_id,))))
        sources = tuple(
            FundingSource(s["alias"], s["kind"],
                          consent_valid=consent_problem(self.db, intent_id, s["alias"]) is None)
            for s in self.db.query("SELECT * FROM funding_sources WHERE customer_id=? ORDER BY created_at",
                                   (intent["customer_id"],)))
        acted = self.db.one(
            "SELECT COUNT(*) n FROM decisions WHERE intent_id=? AND chosen_action NOT IN ('DROP') "
            "AND held_out=0", (intent_id,))["n"]
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        contacts = self.db.query(
            "SELECT a.created_at FROM actions a JOIN decisions d ON d.decision_id=a.decision_id "
            "JOIN payment_intents p ON p.intent_id=d.intent_id "
            "WHERE p.customer_id=? AND a.kind='CHECKOUT_LINK' AND a.created_at>=? "
            "ORDER BY a.created_at DESC", (intent["customer_id"], since))
        last = (datetime.now(timezone.utc) - datetime.fromisoformat(contacts[0]["created_at"])
                ).total_seconds() / 3600 if contacts else None
        registered = True
        if intent["channel"] == "agent":
            reg = self.db.one("SELECT status FROM agent_registrations WHERE agent_id=?",
                              (intent["agent_id"],))
            registered = bool(reg and reg["status"] == "ACTIVE")
        paid = self.db.one("SELECT 1 FROM outcomes WHERE intent_id=?", (intent_id,)) is not None
        return RecoveryContext(
            channel=Channel(intent["channel"]), failed_funding_aliases=failed,
            funding_sources=sources, agent_registered=registered, attempts_so_far=acted,
            contacts_today=len(contacts), hours_since_last_contact=last,
            customer_opted_out=bool(customer["opted_out"]), already_recovered=paid,
            kill_switch_active=self._kill(), currency_code=intent["currency_code"])

    def _features(self, intent, ctx: RecoveryContext, attempt) -> SimpleNamespace:
        history = self.db.one(
            "SELECT SUM(outcome IS NOT NULL) paid, COUNT(*) total FROM payment_intents "
            "WHERE customer_id=? AND intent_id<>?", (intent["customer_id"], intent["intent_id"]))
        total, paid = history["total"] or 0, history["paid"] or 0
        created = datetime.fromisoformat(intent["created_at"])
        src = next((s for s in ctx.funding_sources if s.alias == attempt["funding_alias"]), None)
        return SimpleNamespace(
            amount=intent["amount_minor"], channel=intent["channel"],
            funding_kind=src.kind if src else "PAYPAL_WALLET",
            processor_response_code=attempt["processor_code"], issue=attempt["issue"],
            alternate_funding_count=sum(1 for s in ctx.funding_sources
                                        if s.consent_valid and s.alias not in ctx.failed_funding_aliases),
            customer_success_rate=(paid / total) if total else 0.5,
            customer_tenure_days=30, prior_payment_count=paid,
            prior_failure_count=total - paid, hours_since_last_success=72.0,
            attempt_number=ctx.attempts_so_far + 1,
            hour_of_day=created.hour, day_of_week=created.weekday())

    def _score(self, features) -> tuple[float, str]:
        try:
            predict = self._predict
            if predict is None:
                from merchant.ml.predict import predict_propensity_batch as predict
            return predict([features])[0], "model (SIMULATED training data)"
        except Exception as exc:  # noqa: BLE001 — a missing model must not stop recovery
            log.warning("propensity model unavailable (%s); using fallback", exc)
            return FALLBACK_PROPENSITY, "fallback constant (no trained model)"

    # -- the run --------------------------------------------------------------
    def on_failure(self, intent_id: str, attempt_id: str) -> FailureDecision:
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        attempt = self.db.one("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,))
        policy: MerchantPolicy = self._policy()
        ctx = self.context(intent_id)

        classification = classify(attempt["processor_code"], attempt["issue"])
        ai = None
        if not classification.confident:
            raw = json.loads(attempt["raw_json"] or "{}")
            ai = diagnosis.diagnose(attempt["processor_code"], attempt["issue"],
                                    raw.get("description"), allow_live=intent["provenance"] != "simulated")
            classification = diagnosis.apply(classification, ai)

        features = self._features(intent, ctx, attempt)
        propensity, source = self._score(features)
        decision = decide(classification, intent["amount_minor"], propensity, ctx, policy)
        decision, held = holdout.apply(decision, classification, intent_id, intent["amount_minor"],
                                       salt=self.salt, rate=self._rate(),
                                       autonomy_ceiling_minor=policy.max_autonomous_amount_minor)
        decision_id = new_id("dec")

        with self.db.tx() as conn:
            audit(conn, intent_id, "INGEST", {"attempt_id": attempt_id,
                                              "processor_code": attempt["processor_code"],
                                              "issue": attempt["issue"],
                                              "funding_alias": attempt["funding_alias"]})
            audit(conn, intent_id, "DIAGNOSE", {
                "failure_class": classification.failure_class.value,
                "diagnosed_by": classification.diagnosed_by, "confident": classification.confident,
                "note": classification.note,
                "llm": None if ai is None else {"accepted": ai.accepted, "confidence": ai.confidence,
                                                "rejected_because": ai.rejected_because}})
            audit(conn, intent_id, "SCORE", {"base_propensity": round(propensity, 4),
                                             "source": source, "features": vars(features)})
            audit(conn, intent_id, "DECIDE", {"decision_id": decision_id,
                                              "action": decision.action.value,
                                              "rule_id": decision.rule_id,
                                              "rationale": decision.rationale,
                                              "options": [r.to_dict() for r in decision.options],
                                              "constraints": list(decision.constraints_applied)})
            audit(conn, intent_id, "HOLDOUT", {"held_out": held, "rate": self._rate()})
            conn.execute(
                "INSERT INTO failures (failure_id, attempt_id, failure_class, retry_same_instrument, "
                "diagnosed_by, confidence) VALUES (?,?,?,?,?,?)",
                (new_id("flr"), attempt_id, classification.failure_class.value,
                 int(classification.retry_same_instrument), classification.diagnosed_by,
                 ai.confidence if ai else 1.0))
            conn.execute(
                "INSERT INTO decisions (decision_id, intent_id, stage_trace_json, chosen_action, "
                "nev_minor, alternatives_json, held_out, mode, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (decision_id, intent_id,
                 dumps({"rule_id": decision.rule_id, "rationale": decision.rationale,
                        "constraints": list(decision.constraints_applied),
                        "failure_class": classification.failure_class.value,
                        "diagnosed_by": classification.diagnosed_by,
                        "base_propensity": round(propensity, 4), "propensity_source": source,
                        "offer_actions": [a.value for a in decision.offer_actions],
                        "eligible_funding_aliases": list(decision.eligible_funding_aliases),
                        "execution_blocked_by": decision.execution_blocked_by}),
                 decision.action.value,
                 decision.valuation.net_ev_minor if decision.valuation else None,
                 dumps([r.to_dict() for r in decision.options]), int(held), self._mode(), now_iso()))
            conn.execute("UPDATE payment_intents SET state='DECIDING', updated_at=? WHERE intent_id=?",
                         (now_iso(), intent_id))
        return FailureDecision(decision_id, decision, classification, held, propensity, source)
