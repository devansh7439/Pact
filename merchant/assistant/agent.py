"""Ask Pact: merchant assistant for recovery intelligence and ledger auditing (doc 04 §1, doc 10 §P4).

Invariants:
- Strictly read-only: inspects ledger, decision audit, taxonomy, and PayPal order status.
- Zero monetary capability: cannot initiate charges, alter authorizations, or mutate DB state.
- Offline-first: provides deterministic template answers when no LLM is configured,
  and LLM-synthesized answers when LLM credentials are present.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from merchant.assistant.tools import PactReadTools
from merchant.config import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20.0
MAX_TOKENS = 600

SYSTEM_PROMPT = """You are Ask Pact, an intelligent recovery auditor for the Pact payment recovery engine on PayPal.
You help merchants understand payment declines, policy decisions, causal holdouts, and recovery metrics.

Invariants:
- You are strictly an analytical and audit assistant.
- You have read-only access. You cannot execute charges, alter records, or move money.
- Use plain, factual, professional language.
- Explain technical decline causes (e.g. processor codes, issuer rules) in clear terms.
- Highlight the Net Expected Value (NEV) and causal holdout status whenever discussing decisions.
"""

INTENT_ID_REGEX = re.compile(r"\b(pi_[a-zA-Z0-9_-]+)\b")
ORDER_ID_REGEX = re.compile(r"\b(ord_[a-zA-Z0-9_-]+|[0-9A-Z]{17})\b")


class AskPactAssistant:
    """Conversational assistant over PactReadTools."""

    def __init__(self, tools: PactReadTools) -> None:
        self.tools = tools

    def ask(self, question: str, intent_id: str | None = None) -> dict[str, Any]:
        """Process a user question, invoke the appropriate read-only tools, and return an answer."""
        q = question.strip()
        lowered = q.lower()

        # 1. Resolve target intent_id if not explicitly provided
        target_intent = intent_id
        if not target_intent:
            match = INTENT_ID_REGEX.search(q)
            if match:
                target_intent = match.group(1)

        # 2. Resolve target order_id
        match_order = ORDER_ID_REGEX.search(q)
        target_order = match_order.group(1) if match_order else None

        tool_used = None
        data: dict[str, Any] = {}

        # 3. Dispatch to appropriate tool
        if target_intent and any(k in lowered for k in ("why", "explain", "decision", "fail", "reason", "decline")):
            tool_used = "explain_decision"
            data = self.tools.explain_decision(target_intent)
        elif target_intent:
            tool_used = "get_intent_details"
            data = self.tools.get_intent_details(target_intent)
        elif target_order and "order" in lowered:
            tool_used = "get_paypal_order"
            data = self.tools.get_paypal_order(target_order)
        elif any(k in lowered for k in ("metric", "rate", "stats", "performance", "how many", "total", "recovered", "lift")):
            tool_used = "get_recovery_metrics"
            data = self.tools.get_recovery_metrics()
        elif any(k in lowered for k in ("recent", "latest", "list", "failed intents", "show intents")):
            state = "FAILED" if "fail" in lowered else ("PAID" if "paid" in lowered else None)
            tool_used = "query_recent_intents"
            data = {"recent_intents": self.tools.query_recent_intents(state=state, limit=10)}
        elif any(k in lowered for k in ("holdout", "control group")):
            tool_used = "explain_holdout"
            data = {
                "explanation": (
                    "Pact reserves a randomized 10% holdout group (seeded by intent hash) "
                    "where recovery actions are withheld. This provides a rigorous control group "
                    "to measure true causal lift and incremental revenue against organic retries."
                )
            }
        else:
            # Fallback to high-level metrics
            tool_used = "get_recovery_metrics"
            data = self.tools.get_recovery_metrics()

        # 4. Synthesize response (LLM or deterministic template)
        answer = self._synthesize(question, tool_used, data)

        return {
            "question": question,
            "answer": answer,
            "tool_used": tool_used,
            "data": data,
            "mode": f"llm:{settings.llm_model}" if settings.llm_live else "template",
        }

    def _synthesize(self, question: str, tool_used: str | None, data: dict[str, Any]) -> str:
        """Synthesize final response via LLM if live, otherwise deterministic template."""
        if settings.llm_live:
            prompt = (
                f"User asked: {question}\n\n"
                f"Retrieved Tool ({tool_used}) Data:\n{json.dumps(data, indent=2)}\n\n"
                f"Please synthesize a clear, helpful response explaining these findings."
            )
            llm_text = self._call_llm(prompt)
            if llm_text:
                return llm_text

        # Deterministic templates
        if tool_used == "explain_decision":
            if "error" in data:
                return f"Could not explain decision: {data['error']}."
            return (
                f"Decision Analysis for {data.get('intent_id')}:\n"
                f"• Failure Class: {data.get('failure_class')}\n"
                f"• Selected Action: {data.get('chosen_action')}\n"
                f"• Expected Net Value: {data.get('nev_minor', 0)} cents\n"
                f"• Holdout Status: {'Assigned to holdout control group (execution withheld)' if data.get('held_out') else 'Eligible for active execution'}\n\n"
                f"{data.get('explanation')}"
            )
        elif tool_used == "get_intent_details":
            if "error" in data:
                return f"Error retrieving intent: {data['error']}."
            return (
                f"Intent {data.get('intent_id')} is currently in state '{data.get('state')}'. "
                f"Amount: {data.get('amount_minor', 0)} {data.get('currency_code', 'USD')}. "
                f"Total attempts recorded: {data.get('attempts_count', 0)}. "
                f"Outcome: {data.get('outcome', {}).get('outcome') if data.get('outcome') else 'In progress / None'}."
            )
        elif tool_used == "get_recovery_metrics":
            rate_pct = round(data.get("recovery_rate", 0.0) * 100, 2)
            gross_usd = data.get("gross_recovered_minor", 0) / 100.0
            return (
                f"Pact Recovery Performance Overview:\n"
                f"• Total Intents: {data.get('total_intents', 0)}\n"
                f"• Successfully Recovered: {data.get('recovered_count', 0)} ({rate_pct}%)\n"
                f"• Lost: {data.get('lost_count', 0)}\n"
                f"• Organic Recoveries: {data.get('organic_count', 0)}\n"
                f"• Gross Recovered Amount: ${gross_usd:.2f}\n"
                f"• Holdout Cases Tracked: {data.get('held_out_count', 0)}"
            )
        elif tool_used == "query_recent_intents":
            intents = data.get("recent_intents", [])
            if not intents:
                return "No payment intents matching the criteria were found."
            lines = [f"Found {len(intents)} recent intents:"]
            for it in intents[:5]:
                amt = it.get("amount_minor", 0) / 100.0
                lines.append(f"• {it.get('intent_id')} - ${amt:.2f} {it.get('currency_code')} [{it.get('state')}]")
            return "\n".join(lines)
        elif tool_used == "get_paypal_order":
            return (
                f"PayPal Order {data.get('order_id')} (Source: {data.get('source')}): "
                f"{data.get('message', 'Retrieved successfully.')}"
            )
        elif tool_used == "explain_holdout":
            return data.get("explanation", "")

        return "I've inspected the Pact audit ledger. Let me know if you would like details on a specific intent or recovery metric."

    def _call_llm(self, prompt: str) -> str | None:
        """Call configured LLM endpoint."""
        body: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": MAX_TOKENS,
        }
        if settings.llm_reasoning_effort:
            body["reasoning_effort"] = settings.llm_reasoning_effort
        try:
            resp = httpx.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            return choice["message"].get("content", "").strip() or None
        except Exception as exc:
            logger.warning("AskPact LLM call failed, falling back to template: %s", exc)
            return None
