"""Read models for the merchant console and the judge's linked view (doc 07 §3)."""

from __future__ import annotations

import json
from typing import Any

from merchant.config import DATA_DIR
from merchant.db import Database
from merchant.engine.holdout import lift_report


def _row(r) -> dict[str, Any]:
    d = dict(r)
    for k in list(d):
        if k.endswith("_json") and isinstance(d[k], str):
            try:
                d[k.removesuffix("_json")] = json.loads(d.pop(k))
            except json.JSONDecodeError:
                pass
    return d


def feed(db: Database, since: int = 0, limit: int = 200) -> dict[str, Any]:
    rows = db.query("SELECT * FROM audit_trail WHERE seq>? ORDER BY seq LIMIT ?", (since, limit))
    events = [_row(r) for r in rows]
    return {"events": events, "next": events[-1]["seq"] if events else since}


def decision(db: Database, decision_id: str) -> dict[str, Any] | None:
    d = db.one("SELECT * FROM decisions WHERE decision_id=?", (decision_id,))
    if d is None:
        return None
    out = _row(d)
    out["options"] = out.pop("alternatives", [])
    out["labels"] = {"probabilities": "SIMULATED"}
    intent_id = d["intent_id"]
    out["intent"] = _row(db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,)))
    out["offers"] = [_row(r) for r in db.query(
        "SELECT * FROM offers WHERE decision_id=?", (decision_id,))]
    out["actions"] = [_row(r) for r in db.query(
        "SELECT * FROM actions WHERE decision_id=?", (decision_id,))]
    out["audit"] = [_row(r) for r in db.query(
        "SELECT * FROM audit_trail WHERE intent_id=? ORDER BY seq", (intent_id,))]
    o = db.one("SELECT * FROM outcomes WHERE intent_id=?", (intent_id,))
    out["outcome"] = _row(o) if o else None
    return out


def ledger(db: Database, limit: int = 500) -> list[dict[str, Any]]:
    """Rows for the AG Grid decision ledger."""
    rows = db.query(
        "SELECT d.decision_id, d.intent_id, d.chosen_action, d.nev_minor, d.held_out, d.mode, "
        "json_extract(d.stage_trace_json, '$.holdout_exempt') IS NOT NULL AS judge_scripted, "
        "d.review_status, d.created_at, p.channel, p.amount_minor, p.currency_code, p.provenance, "
        "f.failure_class, f.diagnosed_by, o.outcome "
        "FROM decisions d JOIN payment_intents p ON p.intent_id=d.intent_id "
        "LEFT JOIN failures f ON f.attempt_id=(SELECT attempt_id FROM attempts a "
        "  WHERE a.intent_id=d.intent_id AND a.status='DECLINED' ORDER BY a.created_at DESC LIMIT 1) "
        "LEFT JOIN outcomes o ON o.intent_id=d.intent_id ORDER BY d.created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def metrics(db: Database, provenance: str | None = None) -> dict[str, Any]:
    """Gross / organic / caused / spend / net, split by provenance — never pooled."""
    provs = [provenance] if provenance else ["sandbox", "fixture", "simulated"]
    out: dict[str, Any] = {}
    for prov in provs:
        r = db.one(
            "SELECT "
            " COALESCE(SUM(CASE WHEN o.outcome IN ('RECOVERED','RECOVERED_BY_HUMAN') THEN o.recovered_minor END),0) caused,"
            " COALESCE(SUM(CASE WHEN o.outcome='ORGANIC' THEN o.recovered_minor END),0) organic,"
            " COALESCE(SUM(CASE WHEN o.outcome='LOST' THEN p.amount_minor END),0) lost,"
            " COUNT(DISTINCT p.intent_id) intents "
            "FROM payment_intents p LEFT JOIN outcomes o ON o.intent_id=p.intent_id "
            "WHERE p.provenance=? AND EXISTS (SELECT 1 FROM decisions d WHERE d.intent_id=p.intent_id)",
            (prov,))
        acted = db.one(
            "SELECT COUNT(*) n, SUM(o.outcome IN ('RECOVERED','RECOVERED_BY_HUMAN')) k "
            "FROM decisions d JOIN payment_intents p ON p.intent_id=d.intent_id "
            "LEFT JOIN outcomes o ON o.intent_id=d.intent_id "
            "WHERE p.provenance=? AND d.held_out=0 AND d.chosen_action<>'DROP' "
            "AND json_extract(d.stage_trace_json, '$.holdout_exempt') IS NULL", (prov,))
        held = db.one(
            "SELECT COUNT(*) n, SUM(o.outcome='ORGANIC') k FROM decisions d "
            "JOIN payment_intents p ON p.intent_id=d.intent_id "
            "LEFT JOIN outcomes o ON o.intent_id=d.intent_id WHERE p.provenance=? AND d.held_out=1 "
            "AND json_extract(d.stage_trace_json, '$.holdout_exempt') IS NULL",
            (prov,))
        out[prov] = {
            "intents_with_failures": r["intents"], "caused_minor": r["caused"],
            "organic_minor": r["organic"], "gross_minor": r["caused"] + r["organic"],
            "lost_minor": r["lost"],
            "holdout": lift_report(acted["k"] or 0, acted["n"] or 0,
                                   held["k"] or 0, held["n"] or 0).to_dict(),
        }
    return {"by_provenance": out,
            "note": "Sandbox, fixture and simulated figures are never pooled. Judge-scripted "
                    "demo runs are excluded from both holdout arms."}


def model_metrics() -> dict[str, Any]:
    path = DATA_DIR / "model_metrics.json"
    if not path.exists():
        return {"available": False, "provenance": "simulated"}
    return {"available": True, **json.loads(path.read_text())}


def security_events(db: Database, limit: int = 100) -> list[dict[str, Any]]:
    return [_row(r) for r in db.query("SELECT * FROM security_events ORDER BY id DESC LIMIT ?", (limit,))]


def linked_merchant_side(db: Database, intent_id: str) -> dict[str, Any] | None:
    """Merchant pane of /judge/run/[intentId]: decisions with per-option tables, offers
    as signed, PayPal order ids, outcome, and the merchant half of the timeline."""
    intent = db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
    if intent is None:
        return None
    decisions = [decision(db, r["decision_id"]) for r in db.query(
        "SELECT decision_id FROM decisions WHERE intent_id=? ORDER BY created_at", (intent_id,))]
    for d in decisions:
        d.pop("audit", None)
        d.pop("intent", None)
    attempts = [_row(r) for r in db.query(
        "SELECT attempt_id, paypal_order_id, paypal_capture_id, funding_alias, status, "
        "processor_code, issue, created_at FROM attempts WHERE intent_id=? ORDER BY created_at",
        (intent_id,))]
    timeline = [{"at": r["created_at"], "side": "merchant", "stage": r["stage"],
                 "detail": json.loads(r["payload_json"])}
                for r in db.query("SELECT * FROM audit_trail WHERE intent_id=? ORDER BY seq",
                                  (intent_id,))]
    o = db.one("SELECT * FROM outcomes WHERE intent_id=?", (intent_id,))
    return {"intent": _row(intent), "decisions": decisions, "attempts": attempts,
            "outcome": _row(o) if o else None, "timeline": timeline}
