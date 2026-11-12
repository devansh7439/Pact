"""Wake the hosted demo, seed it if needed, and prove a judge scenario runs.

    MERCHANT_URL=https://pact-merchant-xxxx.onrender.com \
    BUYER_URL=https://pact-buyer-xxxx.onrender.com \
    python -m deploy.warmup

Free-tier services sleep and come back with empty SQLite files, so run this
before anyone looks at the demo. It is safe to run repeatedly: it seeds only
when judge scenario S1 can't run (seeding is idempotent), and it ends with
/judge/reset so judges start from a clean slate.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

from scripts.seed import seed

WAKE_TIMEOUT_S = 240  # a cold free-tier boot is ~1 min; allow for a slow build cache
RESTART_HINT = (
    "Check that MERCHANT_SIGNING_KEY and BUYER_SIGNING_KEY are set (fixed keys keep the "
    "agent's identity across cold starts). Last resort: restart BOTH pact-merchant and "
    "pact-buyer in the Render dashboard, then run this script again."
)


def wake(name: str, url: str) -> dict:
    deadline = time.monotonic() + WAKE_TIMEOUT_S
    last = ""
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url.rstrip("/") + "/health", timeout=30)
            if r.status_code == 200:
                print(f"  {name:<9} up    {url}")
                return r.json()
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        print(f"  {name:<9} waking ({last})")
        time.sleep(5)
    raise SystemExit(f"{name} did not come up within {WAKE_TIMEOUT_S}s ({last}): {url}")


def probe(m: httpx.Client, tries: int = 4) -> httpx.Response:
    """Run S1, retrying if the intent lands in the ~10% holdout arm (no offer is made)."""
    r = m.post("/judge/scenarios/S1/run")
    for _ in range(tries - 1):
        if r.status_code != 200 or r.json().get("result", {}).get("outcome") == "RECOVERED":
            break
        print("  S1 landed in the holdout arm -> retrying")
        r = m.post("/judge/scenarios/S1/run")
    return r


def main() -> int:
    m_url = os.environ.get("MERCHANT_URL", "http://localhost:8100").rstrip("/")
    b_url = os.environ.get("BUYER_URL", "http://localhost:8200").rstrip("/")

    print("1/3 waking services")
    health = wake("merchant", m_url)
    wake("buyer", b_url)
    if health.get("mode") != "autonomous":
        print(f"  warning: merchant mode is {health.get('mode')!r}; is JUDGE_MODE=true set on pact-merchant?")

    with httpx.Client(base_url=m_url, timeout=90) as m, httpx.Client(base_url=b_url, timeout=90) as b:
        print("2/3 checking demo state (judge scenario S1)")
        r = probe(m)
        if r.status_code != 200:
            # Either side may have woken with an empty DB. Seeding is idempotent
            # (same-key re-register returns the existing registration), so just seed.
            print(f"  not ready (HTTP {r.status_code}: {r.text[:120]}) -> seeding")
            try:
                seed(m, b, merchant_base_url=m_url)
            except SystemExit as exc:
                print(f"  {exc}")
                print(f"  {RESTART_HINT}")
                return 1
            r = probe(m)

        outcome = r.json().get("result", {}).get("outcome") if r.status_code == 200 else None
        if outcome != "RECOVERED":
            print(f"  S1 did not recover: HTTP {r.status_code} {r.text[:300]}")
            print(f"  {RESTART_HINT}")
            return 1
        print("  S1 -> RECOVERED")

        print("3/3 resetting to a clean slate")
        reset = m.post("/judge/reset")
        if reset.status_code >= 300:
            print(f"  reset failed: HTTP {reset.status_code} {reset.text[:200]}")
            return 1

    print("ready: demo is warm, seeded and reset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
