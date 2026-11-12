"""Merchant database (`merchant.db`) — doc 07 §1.

SQLite in WAL mode. Money is INTEGER minor units plus `currency_code`; timestamps
are UTC ISO-8601; every row that feeds a metric carries `provenance`
(sandbox | fixture | simulated).

Two properties are enforced by the database itself rather than by convention:

- `audit_trail` is append-only: triggers abort any UPDATE or DELETE.
- `outcomes` is unique per intent, and `record_outcome` is INSERT-OR-IGNORE, so a
  webhook and a reconciler poll racing on the same capture write one outcome (I15).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT,
    paypal_payer_id TEXT,
    channel TEXT NOT NULL CHECK (channel IN ('agent','human')),
    opted_out INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- vault_id never leaves the merchant; agents only ever see `alias`.
CREATE TABLE IF NOT EXISTS funding_sources (
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    alias TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('CARD','PAYPAL_WALLET')),
    vault_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REVOKED')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (customer_id, alias)
);

CREATE TABLE IF NOT EXISTS agent_registrations (
    agent_id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(customer_id),
    agent_public_key TEXT NOT NULL,
    key_id TEXT NOT NULL UNIQUE,
    callback_url TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING_APPROVAL','ACTIVE','REVOKED')),
    onboarding_token TEXT NOT NULL UNIQUE,
    draft_mandate_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registered_mandates (
    mandate_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agent_registrations(agent_id),
    caps_json TEXT NOT NULL,
    approved_by_payer_id TEXT,
    approved_at TEXT NOT NULL,
    approval_ref TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_intents (
    intent_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    channel TEXT NOT NULL CHECK (channel IN ('agent','human')),
    agent_id TEXT,
    mandate_id TEXT,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency_code TEXT NOT NULL,
    items_json TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    provenance TEXT NOT NULL CHECK (provenance IN ('sandbox','fixture','simulated')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES payment_intents(intent_id),
    paypal_order_id TEXT,
    paypal_capture_id TEXT,
    funding_alias TEXT,
    request_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    processor_code TEXT,
    issue TEXT,
    raw_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failures (
    failure_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
    failure_class TEXT NOT NULL,
    retry_same_instrument INTEGER NOT NULL,
    diagnosed_by TEXT NOT NULL CHECK (diagnosed_by IN ('rules','llm')),
    confidence REAL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES payment_intents(intent_id),
    stage_trace_json TEXT NOT NULL,
    chosen_action TEXT NOT NULL,
    nev_minor INTEGER,
    alternatives_json TEXT NOT NULL,
    held_out INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL,
    review_status TEXT,
    created_at TEXT NOT NULL
);

-- body_json is the offer exactly as signed (the evidence).
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES payment_intents(intent_id),
    decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
    body_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN','ACCEPTED','DECLINED','EXPIRED','SUPERSEDED')),
    accepted_option_id TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
    kind TEXT NOT NULL,
    paypal_order_id TEXT,
    approve_url TEXT,
    message_text TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    verified INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    body_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    intent_id TEXT PRIMARY KEY REFERENCES payment_intents(intent_id),
    outcome TEXT NOT NULL CHECK (outcome IN
        ('RECOVERED','RECOVERED_BY_HUMAN','ORGANIC','LOST','PAID')),
    source TEXT NOT NULL CHECK (source IN ('webhook','poll','api','simulator')),
    recovered_minor INTEGER NOT NULL,
    paypal_capture_id TEXT,
    attributed_action_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_trail (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT,
    stage TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_trail
BEGIN SELECT RAISE(ABORT, 'audit_trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_trail
BEGIN SELECT RAISE(ABORT, 'audit_trail is append-only'); END;

CREATE TABLE IF NOT EXISTS controls (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- PRP replay guard, shared across workers (signing.NonceStore).
CREATE TABLE IF NOT EXISTS prp_nonces (
    key_id TEXT NOT NULL,
    nonce TEXT NOT NULL,
    seen_at INTEGER NOT NULL,
    PRIMARY KEY (key_id, nonce)
);

-- Agent-API idempotency: same key + same body replays the stored response;
-- same key + different body is a 409.
CREATE TABLE IF NOT EXISTS idempotency (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);

CREATE INDEX IF NOT EXISTS ix_attempts_intent ON attempts(intent_id);
CREATE INDEX IF NOT EXISTS ix_decisions_intent ON decisions(intent_id);
CREATE INDEX IF NOT EXISTS ix_offers_intent ON offers(intent_id);
CREATE INDEX IF NOT EXISTS ix_audit_intent ON audit_trail(intent_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class Database:
    """One SQLite file, one write lock. Connections are per call; WAL lets reads overlap."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        # A shared in-memory DB needs one long-lived connection.
        self._memory = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None) \
            if self.path == ":memory:" else None
        # executescript commits implicitly, so it runs outside tx(). Every statement
        # in SCHEMA is IF NOT EXISTS, so concurrent first boots are harmless.
        with self._write_lock:
            conn = self._open()
            try:
                conn.executescript(SCHEMA)
            finally:
                if self._memory is None:
                    conn.close()

    def _open(self) -> sqlite3.Connection:
        if self._memory is not None:
            self._memory.row_factory = sqlite3.Row
            return self._memory
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction. Serialised in-process so check-then-write is atomic."""
        with self._write_lock:
            conn = self._open()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            finally:
                if self._memory is None:
                    conn.close()

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._write_lock if self._memory is not None else _nullcontext():
            conn = self._open()
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                if self._memory is None:
                    conn.close()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None


@contextmanager
def _nullcontext() -> Iterator[None]:
    yield


# -- Writers used across the service ---------------------------------------

def audit(conn: sqlite3.Connection, intent_id: str | None, stage: str,
          payload: dict[str, Any]) -> None:
    """Append one audit row. There is no update or delete path (triggers enforce it)."""
    conn.execute(
        "INSERT INTO audit_trail (intent_id, stage, payload_json, created_at) VALUES (?,?,?,?)",
        (intent_id, stage, dumps(payload), now_iso()))


def record_outcome(conn: sqlite3.Connection, intent_id: str, outcome: str, source: str,
                   recovered_minor: int, capture_id: str | None,
                   attributed_action_id: str | None) -> bool:
    """Idempotent across sources (I15). Returns True only for the first writer."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO outcomes (intent_id, outcome, source, recovered_minor, "
        "paypal_capture_id, attributed_action_id, created_at) VALUES (?,?,?,?,?,?,?)",
        (intent_id, outcome, source, recovered_minor, capture_id, attributed_action_id, now_iso()))
    if cur.rowcount:
        conn.execute("UPDATE payment_intents SET outcome=?, state='PAID', updated_at=? "
                     "WHERE intent_id=?", (outcome, now_iso(), intent_id))
        audit(conn, intent_id, "MEASURE", {"outcome": outcome, "source": source,
                                           "recovered_minor": recovered_minor,
                                           "capture_id": capture_id})
    return bool(cur.rowcount)


def security_event(conn: sqlite3.Connection, kind: str, detail: dict[str, Any]) -> None:
    conn.execute("INSERT INTO security_events (kind, detail_json, created_at) VALUES (?,?,?)",
                 (kind, dumps(detail), now_iso()))


def get_control(db: Database, key: str, default: str) -> str:
    row = db.one("SELECT value FROM controls WHERE key=?", (key,))
    return row["value"] if row else default


def set_control(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO controls (key, value, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                 (key, value, now_iso()))


class SqliteNonceStore:
    """`shared.prp.signing.NonceStore` backed by merchant.db, so replays are caught
    across workers and restarts."""

    def __init__(self, db: Database, ttl_s: int = 600) -> None:
        self.db, self.ttl = db, ttl_s

    def seen(self, key_id: str, nonce: str, now: int) -> bool:
        return self.db.one("SELECT 1 FROM prp_nonces WHERE key_id=? AND nonce=? AND seen_at>=?",
                           (key_id, nonce, now - self.ttl)) is not None

    def remember(self, key_id: str, nonce: str, now: int) -> bool:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM prp_nonces WHERE seen_at<?", (now - self.ttl,))
            cur = conn.execute("INSERT OR IGNORE INTO prp_nonces VALUES (?,?,?)",
                               (key_id, nonce, now))
            return bool(cur.rowcount)
