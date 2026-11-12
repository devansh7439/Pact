"""Tests for Ask Pact assistant and read-only tools (doc 04 §1, doc 10 §P4)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from merchant.app import create_app
from merchant.assistant import AskPactAssistant, PactReadTools
from merchant.config import Settings
from merchant.db import Database


@pytest.fixture
def test_db(tmp_path) -> Database:
    db = Database(tmp_path / "test_merchant.db")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO customers(customer_id, display_name, email, channel, created_at) "
            "VALUES('cust_1', 'Maya', 'maya@example.com', 'agent', '2026-11-12T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO customers(customer_id, display_name, email, channel, created_at) "
            "VALUES('cust_2', 'Arjun', 'arjun@example.com', 'human', '2026-11-12T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO payment_intents(intent_id, customer_id, channel, amount_minor, currency_code, items_json, state, provenance, created_at, updated_at) "
            "VALUES('pi_test1', 'cust_1', 'agent', 3200, 'USD', '[]', 'PAID', 'fixture', '2026-11-12T10:00:00Z', '2026-11-12T10:05:00Z')"
        )
        conn.execute(
            "INSERT INTO payment_intents(intent_id, customer_id, channel, amount_minor, currency_code, items_json, state, provenance, created_at, updated_at) "
            "VALUES('pi_test2', 'cust_2', 'agent', 4500, 'USD', '[]', 'FAILED', 'fixture', '2026-11-12T11:00:00Z', '2026-11-12T11:05:00Z')"
        )
        conn.execute(
            "INSERT INTO attempts(attempt_id, intent_id, request_id, status, processor_code, issue, funding_alias, created_at) "
            "VALUES('att_1', 'pi_test2', 'req_1', 'DECLINED', '5100', NULL, 'primary-card', '2026-11-12T11:01:00Z')"
        )
        conn.execute(
            "INSERT INTO failures(failure_id, attempt_id, failure_class, retry_same_instrument, diagnosed_by, confidence) "
            "VALUES('fail_1', 'att_1', 'INSUFFICIENT_FUNDS', 0, 'rules', 1.0)"
        )
        conn.execute(
            "INSERT INTO decisions(decision_id, intent_id, stage_trace_json, chosen_action, nev_minor, alternatives_json, held_out, mode, review_status, created_at) "
            "VALUES('dec_1', 'pi_test2', '[]', 'ALTERNATE_FUNDING', 3800, '[]', 0, 'autonomous', 'APPROVED', '2026-11-12T11:01:10Z')"
        )
        conn.execute(
            "INSERT INTO outcomes(intent_id, outcome, source, recovered_minor, created_at) "
            "VALUES('pi_test1', 'RECOVERED', 'api', 3200, '2026-11-12T10:05:00Z')"
        )
    return db


def test_pact_read_tools_metrics(test_db):
    tools = PactReadTools(test_db)
    metrics = tools.get_recovery_metrics()
    assert metrics["total_intents"] == 2
    assert metrics["recovered_count"] == 1
    assert metrics["gross_recovered_minor"] == 3200
    assert metrics["recovery_rate"] == 0.5


def test_pact_read_tools_query_recent(test_db):
    tools = PactReadTools(test_db)
    all_intents = tools.query_recent_intents()
    assert len(all_intents) == 2

    failed = tools.query_recent_intents(state="FAILED")
    assert len(failed) == 1
    assert failed[0]["intent_id"] == "pi_test2"


def test_pact_read_tools_explain_decision(test_db):
    tools = PactReadTools(test_db)
    exp = tools.explain_decision("pi_test2")
    assert exp["intent_id"] == "pi_test2"
    assert exp["failure_class"] == "ISSUER_DECLINED"
    assert exp["chosen_action"] == "ALTERNATE_FUNDING"
    assert exp["nev_minor"] == 3800
    assert not exp["held_out"]
    assert "classified as ISSUER_DECLINED" in exp["explanation"]


def test_assistant_ask_decision(test_db):
    tools = PactReadTools(test_db)
    assistant = AskPactAssistant(tools)
    res = assistant.ask("Why did pi_test2 decline?")
    assert res["tool_used"] == "explain_decision"
    assert "Decision Analysis for pi_test2" in res["answer"]
    assert "ISSUER_DECLINED" in res["answer"]
    assert "ALTERNATE_FUNDING" in res["answer"]


def test_assistant_ask_metrics(test_db):
    tools = PactReadTools(test_db)
    assistant = AskPactAssistant(tools)
    res = assistant.ask("What is our current recovery rate and total performance?")
    assert res["tool_used"] == "get_recovery_metrics"
    assert "Recovery Performance Overview" in res["answer"]
    assert "50.0%" in res["answer"]
    assert "$32.00" in res["answer"]


def test_assistant_ask_holdout(test_db):
    tools = PactReadTools(test_db)
    assistant = AskPactAssistant(tools)
    res = assistant.ask("Explain the holdout group")
    assert res["tool_used"] == "explain_holdout"
    assert "10% holdout group" in res["answer"]


def test_assistant_api_endpoint(tmp_path):
    cfg = Settings(merchant_db_path=tmp_path / "app_merchant.db", judge_mode=False)
    app = create_app(cfg=cfg)
    client = TestClient(app)

    # Empty question -> 400
    r = client.post("/assistant/ask", json={"question": ""})
    assert r.status_code == 400

    # Valid question -> 200
    r = client.post("/assistant/ask", json={"question": "What is our recovery rate?"})
    assert r.status_code == 200
    data = r.json()
    assert data["tool_used"] == "get_recovery_metrics"
    assert "Recovery Performance" in data["answer"]
