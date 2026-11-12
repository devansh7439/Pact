"""buyer.db: the buyer agent's own records (doc 07 §2). SQLite, WAL.

The agent's private key is never stored here (it lives in BUYER_SIGNING_KEY).
Offers are stored as the exact signed bytes received, so the buyer can later
prove what the merchant sent.
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

from shared.prp.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS principals (
    principal_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mandates (
    mandate_id   TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    body_json    TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('DRAFT','ACTIVE','REVOKED','EXPIRED')),
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merchant_links (
    merchant_id         TEXT PRIMARY KEY,
    base_url            TEXT NOT NULL,
    agent_id            TEXT,
    merchant_public_key TEXT,
    merchant_key_id     TEXT,
    merchant_name       TEXT,
    mandate_id          TEXT,
    status              TEXT NOT NULL DEFAULT 'PENDING'
);
CREATE TABLE IF NOT EXISTS purchases (
    purchase_id           TEXT PRIMARY KEY,
    merchant_id           TEXT NOT NULL,
    intent_id             TEXT UNIQUE,
    sku                   TEXT,
    category              TEXT,
    amount_minor          INTEGER NOT NULL,
    currency_code         TEXT NOT NULL,
    funding_alias         TEXT NOT NULL,
    autonomous_recoveries INTEGER NOT NULL DEFAULT 0,
    failed_aliases_json   TEXT NOT NULL DEFAULT '[]',
    status                TEXT NOT NULL,
    outcome               TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offers_received (
    offer_id           TEXT NOT NULL,
    purchase_id        TEXT,
    body_json          TEXT NOT NULL,
    signature_ok       INTEGER NOT NULL,
    signature_error    TEXT,
    scanner_flags_json TEXT NOT NULL DEFAULT '[]',
    received_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guard_decisions (
    gd_id        TEXT PRIMARY KEY,
    offer_id     TEXT,
    purchase_id  TEXT,
    result       TEXT NOT NULL,
    rule_fired   TEXT NOT NULL,
    option_id    TEXT,
    alias        TEXT,
    reason       TEXT NOT NULL,
    checks_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_ledger (
    entry_id     TEXT PRIMARY KEY,
    mandate_id   TEXT NOT NULL,
    period_start TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    purchase_id  TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
    msg_id       TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('ESCALATION','RECEIPT','SECURITY','INFO')),
    text         TEXT NOT NULL,
    approve_url  TEXT,
    purchase_id  TEXT,
    status       TEXT NOT NULL DEFAULT 'UNREAD',
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS controls (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat()


class BuyerDB:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _all(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        rows = self._all(sql, *args)
        return rows[0] if rows else None

    # -- controls ---------------------------------------------------------- #
    def is_paused(self) -> bool:
        row = self._one("SELECT value FROM controls WHERE key='paused'")
        return bool(row and row["value"] == "1")

    def set_paused(self, paused: bool) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO controls(key,value) VALUES('paused',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if paused else "0",))

    # -- principals & mandates -------------------------------------------- #
    def upsert_principal(self, principal_id: str, display_name: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO principals VALUES(?,?) ON CONFLICT(principal_id) "
                      "DO UPDATE SET display_name=excluded.display_name", (principal_id, display_name))

    def save_mandate(self, mandate_id: str, principal_id: str, body: dict[str, Any], status: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO mandates VALUES(?,?,?,?,?) ON CONFLICT(mandate_id) "
                "DO UPDATE SET body_json=excluded.body_json, status=excluded.status",
                (mandate_id, principal_id, json.dumps(body, sort_keys=True), status, _iso()),
            )

    def set_mandate_status(self, mandate_id: str, status: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE mandates SET status=? WHERE mandate_id=?", (status, mandate_id))

    def mandates(self) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM mandates ORDER BY created_at DESC")
        for r in rows:
            r["body"] = json.loads(r.pop("body_json"))
        return rows

    def active_mandate(self) -> dict[str, Any] | None:
        return next((m for m in self.mandates() if m["status"] == "ACTIVE"), None)

    # -- merchant links ---------------------------------------------------- #
    def upsert_merchant_link(self, merchant_id: str, **fields: Any) -> None:
        cols = ["merchant_id", *fields]
        vals = [merchant_id, *fields.values()]
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields) or "merchant_id=merchant_id"
        with self.tx() as c:
            c.execute(
                f"INSERT INTO merchant_links({', '.join(cols)}) VALUES({', '.join('?' * len(cols))}) "
                f"ON CONFLICT(merchant_id) DO UPDATE SET {updates}",
                vals,
            )

    def set_merchant_link_status(self, merchant_id: str, status: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE merchant_links SET status=? WHERE merchant_id=?", (status, merchant_id))

    def merchant_link(self, merchant_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM merchant_links WHERE merchant_id=?", merchant_id)

    def merchant_link_by_key_id(self, key_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM merchant_links WHERE merchant_key_id=?", key_id)

    # -- purchases --------------------------------------------------------- #
    def create_purchase(self, *, merchant_id: str, sku: str, category: str, amount_minor: int,
                        currency_code: str, funding_alias: str) -> str:
        pid = new_id("pur")
        now = _iso()
        with self.tx() as c:
            c.execute(
                "INSERT INTO purchases(purchase_id, merchant_id, sku, category, amount_minor, currency_code, "
                "funding_alias, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid, merchant_id, sku, category, amount_minor, currency_code, funding_alias, "CREATED", now, now),
            )
        return pid

    def update_purchase(self, purchase_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE purchases SET {sets}, updated_at=? WHERE purchase_id=?",
                      (*fields.values(), _iso(), purchase_id))

    def bump_recoveries(self, purchase_id: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE purchases SET autonomous_recoveries=autonomous_recoveries+1, updated_at=? "
                      "WHERE purchase_id=?", (_iso(), purchase_id))

    def add_failed_alias(self, purchase_id: str, alias: str) -> None:
        with self.tx() as c:
            row = c.execute("SELECT failed_aliases_json FROM purchases WHERE purchase_id=?", (purchase_id,)).fetchone()
            if row is None:
                return
            failed = set(json.loads(row[0])) | {alias}
            c.execute("UPDATE purchases SET failed_aliases_json=?, updated_at=? WHERE purchase_id=?",
                      (json.dumps(sorted(failed)), _iso(), purchase_id))

    @staticmethod
    def _purchase_row(r: dict[str, Any] | None) -> dict[str, Any] | None:
        if r is not None:
            r["failed_aliases"] = json.loads(r.pop("failed_aliases_json"))
        return r

    def purchase(self, purchase_id: str) -> dict[str, Any] | None:
        return self._purchase_row(self._one("SELECT * FROM purchases WHERE purchase_id=?", purchase_id))

    def purchase_by_intent(self, intent_id: str) -> dict[str, Any] | None:
        return self._purchase_row(self._one("SELECT * FROM purchases WHERE intent_id=?", intent_id))

    def purchases(self) -> list[dict[str, Any]]:
        return [self._purchase_row(r) for r in self._all("SELECT * FROM purchases ORDER BY created_at DESC")]

    # -- offers & guard decisions ----------------------------------------- #
    def store_offer(self, *, offer_id: str, purchase_id: str | None, raw: bytes, signature_ok: bool,
                    signature_error: str | None, scanner_flags: list[str]) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO offers_received VALUES(?,?,?,?,?,?,?)",
                (offer_id, purchase_id, raw.decode("utf-8", "replace"), int(signature_ok),
                 signature_error, json.dumps(scanner_flags), _iso()),
            )

    def offers_for(self, purchase_id: str) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM offers_received WHERE purchase_id=? ORDER BY received_at", purchase_id)
        for r in rows:
            r["scanner_flags"] = json.loads(r.pop("scanner_flags_json"))
            r["signature_ok"] = bool(r["signature_ok"])
        return rows

    def store_guard_decision(self, *, offer_id: str | None, purchase_id: str | None, result: str,
                             rule_fired: str, option_id: str | None, alias: str | None, reason: str,
                             checks: list[dict[str, str]]) -> str:
        gd = new_id("gd")
        with self.tx() as c:
            c.execute(
                "INSERT INTO guard_decisions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (gd, offer_id, purchase_id, result, rule_fired, option_id, alias, reason,
                 json.dumps(checks), _iso()),
            )
        return gd

    def guard_decisions_for(self, purchase_id: str) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM guard_decisions WHERE purchase_id=? ORDER BY created_at", purchase_id)
        for r in rows:
            r["checks"] = json.loads(r.pop("checks_json"))
        return rows

    # -- budget ledger (captures only) ------------------------------------ #
    def record_spend(self, *, mandate_id: str, period_start: datetime, amount_minor: int, purchase_id: str) -> None:
        """Idempotent per purchase: a second capture notice for the same purchase is a no-op."""
        with self.tx() as c:
            c.execute(
                "INSERT INTO budget_ledger VALUES(?,?,?,?,?,?) ON CONFLICT(purchase_id) DO NOTHING",
                (new_id("led"), mandate_id, period_start.isoformat(), amount_minor, purchase_id, _iso()),
            )

    def spent_since(self, mandate_id: str, period_start: datetime) -> int:
        row = self._one(
            "SELECT COALESCE(SUM(amount_minor),0) AS s FROM budget_ledger WHERE mandate_id=? AND period_start>=?",
            mandate_id, period_start.isoformat(),
        )
        return int(row["s"]) if row else 0

    def reset_activity(self) -> None:
        """Judge-mode reset: clear purchases and everything hanging off them.
        Keeps principals, mandates, merchant links and controls."""
        with self.tx() as c:
            for table in ("purchases", "offers_received", "guard_decisions", "budget_ledger", "inbox"):
                c.execute(f"DELETE FROM {table}")
            c.execute("DELETE FROM controls WHERE key='paused'")

    # -- inbox ------------------------------------------------------------- #
    def add_inbox(self, *, principal_id: str, kind: str, text: str, approve_url: str | None = None,
                  purchase_id: str | None = None) -> str:
        mid = new_id("msg")
        with self.tx() as c:
            c.execute("INSERT INTO inbox VALUES(?,?,?,?,?,?,?,?)",
                      (mid, principal_id, kind, text, approve_url, purchase_id, "UNREAD", _iso()))
        return mid

    def inbox(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM inbox WHERE status!='DISMISSED' ORDER BY created_at DESC")

    def dismiss(self, msg_id: str) -> bool:
        with self.tx() as c:
            cur = c.execute("UPDATE inbox SET status='DISMISSED' WHERE msg_id=?", (msg_id,))
            return cur.rowcount > 0
