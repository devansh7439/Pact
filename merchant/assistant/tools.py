"""Read-only tools for the Ask Pact merchant assistant (doc 04 §1, doc 10 §P4).

Invariants:
- All tools are strictly read-only. No tool output can move money or mutate state.
- Exposes merchant ledger, decision audit, taxonomy diagnostics, and PayPal Agent Toolkit order queries.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from merchant.db import Database
from merchant.engine.taxonomy import classify

logger = logging.getLogger(__name__)


class PactReadTools:
    """Read-only inspection tools for the merchant recovery engine."""

    def __init__(
        self,
        db: Database,
        paypal_client: Any = None,
        toolkit_credentials: tuple[str, str] | None = None,
        sandbox: bool = True,
    ) -> None:
        self.db = db
        self.paypal = paypal_client
        self._toolkit = None
        self._toolkit_error = None
        if toolkit_credentials:
            self._init_paypal_toolkit(*toolkit_credentials, sandbox=sandbox)

    def _init_paypal_toolkit(self, client_id: str, secret: str, sandbox: bool) -> None:
        """Build the toolkit's framework-neutral core. Only `get_order_details` is ever called."""
        try:
            from paypal_agent_toolkit.shared.api import PayPalAPI  # type: ignore
            from paypal_agent_toolkit.shared.configuration import Context  # type: ignore

            self._toolkit = PayPalAPI(client_id=client_id, secret=secret, context=Context(sandbox=sandbox))
            logger.info("PayPal Agent Toolkit loaded (read-only get_order_details)")
        except Exception as e:
            self._toolkit_error = str(e)
            logger.debug("PayPal Agent Toolkit not initialized: %s", e)

    def get_intent_details(self, intent_id: str) -> dict[str, Any]:
        """Fetch complete audit lifecycle for a payment intent."""
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        if not intent:
            return {"error": f"Intent '{intent_id}' not found"}

        attempts = self.db.query("SELECT * FROM attempts WHERE intent_id=? ORDER BY created_at ASC", (intent_id,))
        decision = self.db.one("SELECT * FROM decisions WHERE intent_id=?", (intent_id,))
        outcome = self.db.one("SELECT * FROM outcomes WHERE intent_id=?", (intent_id,))
        offers = self.db.query("SELECT * FROM offers WHERE intent_id=?", (intent_id,))

        return {
            "intent_id": intent["intent_id"],
            "state": intent["state"],
            "amount_minor": intent["amount_minor"],
            "currency_code": intent["currency_code"],
            "channel": intent["channel"],
            "attempts_count": len(attempts),
            "attempts": [
                {
                    "attempt_id": a["attempt_id"],
                    "status": a["status"],
                    "processor_code": a["processor_code"],
                    "issue": a["issue"],
                    "funding_alias": a["funding_alias"],
                }
                for a in attempts
            ],
            "decision": (
                {
                    "decision_id": decision["decision_id"],
                    "chosen_action": decision["chosen_action"],
                    "nev_minor": decision["nev_minor"],
                    "held_out": bool(decision["held_out"]),
                    "review_status": decision["review_status"],
                }
                if decision
                else None
            ),
            "outcome": (
                {
                    "outcome": outcome["outcome"],
                    "source": outcome["source"],
                    "recovered_minor": outcome["recovered_minor"],
                }
                if outcome
                else None
            ),
            "offers_count": len(offers),
        }

    def query_recent_intents(self, state: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """List recent payment intents with optional state filtering."""
        limit = min(max(1, limit), 50)
        if state:
            rows = self.db.query(
                "SELECT intent_id, amount_minor, currency_code, state, channel, created_at "
                "FROM payment_intents WHERE state=? ORDER BY created_at DESC LIMIT ?",
                (state.upper(), limit),
            )
        else:
            rows = self.db.query(
                "SELECT intent_id, amount_minor, currency_code, state, channel, created_at "
                "FROM payment_intents ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    def get_recovery_metrics(self) -> dict[str, Any]:
        """Compute top-level recovery statistics across all recorded intents."""
        total = self.db.one("SELECT COUNT(*) as c FROM payment_intents")["c"]
        recovered = self.db.one("SELECT COUNT(*) as c FROM outcomes WHERE outcome IN ('RECOVERED','RECOVERED_BY_HUMAN')")["c"]
        lost = self.db.one("SELECT COUNT(*) as c FROM outcomes WHERE outcome='LOST'")["c"]
        organic = self.db.one("SELECT COUNT(*) as c FROM outcomes WHERE outcome='ORGANIC'")["c"]
        gross_recovered_minor = self.db.one(
            "SELECT COALESCE(SUM(recovered_minor), 0) as s FROM outcomes WHERE outcome IN ('RECOVERED','RECOVERED_BY_HUMAN')"
        )["s"]
        held_out_count = self.db.one("SELECT COUNT(*) as c FROM decisions WHERE held_out=1")["c"]

        rate = (recovered / total) if total > 0 else 0.0
        return {
            "total_intents": total,
            "recovered_count": recovered,
            "lost_count": lost,
            "organic_count": organic,
            "gross_recovered_minor": gross_recovered_minor,
            "held_out_count": held_out_count,
            "recovery_rate": round(rate, 4),
        }

    def explain_decision(self, intent_id: str) -> dict[str, Any]:
        """Explain the algorithmic rationale for a decision."""
        details = self.get_intent_details(intent_id)
        if "error" in details:
            return details

        decision = details.get("decision")
        if not decision:
            return {"intent_id": intent_id, "explanation": "No decision has been recorded yet for this intent."}

        attempts = details.get("attempts", [])
        last_attempt = attempts[-1] if attempts else None
        proc_code = last_attempt.get("processor_code") if last_attempt else None
        issue = last_attempt.get("issue") if last_attempt else None
        diag = classify(proc_code, issue)

        chosen = decision["chosen_action"]
        nev = decision["nev_minor"]
        held_out = decision["held_out"]

        explanation = (
            f"Intent {intent_id} failed with {diag.entry.name if diag.entry else 'unmapped signal'} "
            f"(classified as {diag.failure_class.value}). "
            f"The engine selected action '{chosen}' with expected net value {nev} cents. "
        )
        if held_out:
            explanation += "Note: This intent was assigned to the 10% holdout group, so autonomous execution was withheld to measure true causal lift."

        return {
            "intent_id": intent_id,
            "failure_class": diag.failure_class.value,
            "chosen_action": chosen,
            "nev_minor": nev,
            "held_out": held_out,
            "explanation": explanation,
        }

    def get_paypal_order(self, order_id: str) -> dict[str, Any]:
        """Fetch PayPal Order state via official PayPal Agent Toolkit or fallback client."""
        # 1. Try PayPal Agent Toolkit if available
        if self._toolkit is not None:
            try:
                res = json.loads(self._toolkit.run("get_order_details", {"order_id": order_id}))
                # The toolkit's own "message" always says "captured"; report PayPal's raw order instead.
                return {"order_id": order_id, "source": "paypal_agent_toolkit", "order": res.get("raw", res)}
            except Exception as e:
                logger.info("toolkit get_order_details failed for %s: %s", order_id, e)

        # 2. Try PayPal client direct lookup from attempt records
        att = self.db.one("SELECT * FROM attempts WHERE paypal_order_id=?", (order_id,))
        if att and att["raw_json"]:
            try:
                return {"order_id": order_id, "source": "pact_audit_ledger", "order": json.loads(att["raw_json"])}
            except Exception:
                pass

        return {
            "order_id": order_id,
            "source": "not_found",
            "message": f"Order {order_id} not available via toolkit or cache.",
        }
