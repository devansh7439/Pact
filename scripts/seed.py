"""Seed judge mode: Maya's mandate, her agent's registration, onboarding, a clean slate.

    python -m scripts.seed                       # against running services
    MERCHANT_URL=... BUYER_URL=... python -m scripts.seed

Runs entirely through the services' public HTTP APIs, so it works the same
against localhost and the hosted demo. Requires JUDGE_MODE=true on merchant-api
(fixture onboarding is a judge-only shortcut; live onboarding is the real
/onboard/{token} page with PayPal approval).
"""

from __future__ import annotations

import os
import sys

import httpx

MAYA_MANDATE = {
    "mandate_id": "mdt_01JD3MAYADEMO0000",
    "principal": {"display_name": "Maya"},
    "merchant_scope": ["mer_kettle_crumb"],
    "currency_code": "USD",
    "budget": {"period": "WEEK", "limit_minor": 10000},
    "per_purchase_cap_minor": 5000,
    "allowed_categories": ["coffee", "tea", "brewing-supplies"],
    "funding": [{"alias": "primary-card", "kind": "CARD", "priority": 1},
                {"alias": "paypal-wallet", "kind": "PAYPAL_WALLET", "priority": 2}],
    "recovery": {"allow_alternate_funding": True, "allow_retry_after": False,
                 "max_autonomous_recoveries_per_purchase": 1,
                 "always_escalate_classes": ["RISK_BLOCKED", "AUTH_FAILURE", "UNKNOWN"]},
    "expires_at": "2027-06-30T00:00:00Z",
}


def _ok(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 300:
        raise SystemExit(f"seed: {what} failed: {r.status_code} {r.text[:300]}")
    return r.json() if r.content else {}


def seed(merchant: httpx.Client, buyer: httpx.Client, *, merchant_base_url: str) -> dict:
    _ok(buyer.post("/buyer/mandates/draft", json=MAYA_MANDATE), "draft mandate")
    _ok(buyer.post(f"/buyer/mandates/{MAYA_MANDATE['mandate_id']}/activate"), "activate mandate")
    conn = _ok(buyer.post("/buyer/merchants/mer_kettle_crumb/connect",
                          json={"base_url": merchant_base_url}), "connect")
    token = conn["approval_url"].rstrip("/").rsplit("/", 1)[1]
    approved = _ok(merchant.post(f"/judge/onboard/{token}"), "onboard")
    _ok(merchant.post("/console/controls", json={"mode": "autonomous"}), "controls")
    _ok(merchant.post("/judge/reset"), "reset")
    return {"approval_url": conn["approval_url"], "mandate": approved}


def main() -> int:
    m_url = os.environ.get("MERCHANT_URL", "http://localhost:8100")
    b_url = os.environ.get("BUYER_URL", "http://localhost:8200")
    with httpx.Client(base_url=m_url, timeout=60) as m, httpx.Client(base_url=b_url, timeout=60) as b:
        result = seed(m, b, merchant_base_url=m_url)
    print(f"seeded: Maya's mandate {result['mandate'].get('mandate_id')} is ACTIVE at {m_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
