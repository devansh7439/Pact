# Spike results: PayPal feasibility (doc 09)

**Status:** NOT RUN (no sandbox credentials yet) · **Timebox:** 3½ h · **Run by:** _ · **Date:** _

Sandbox app: `pact-merchant` · Business account: _ · Maya (personal): _ · Arjun (personal): _
Secrets never go in this file. The scripts redact `Authorization`, tokens, CVVs and card numbers (first 4 and last 4 digits kept).

## How to run

```bash
# .env: PAYPAL_ENV=sandbox, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, MERCHANT_PUBLIC_URL
python scripts/spike/01_auth_order.py create        # approve as Maya, then: … capture
python scripts/spike/02_vault_paypal.py create      # approve as Maya, then: … finish
python scripts/spike/03_vault_cards.py
python scripts/spike/04_charge_vaulted.py all       # S4 + S4b (encodings A and B)
python scripts/spike/05_decline.py                  # S5; `mock` for S5b
python scripts/spike/06_recover_alternate.py        # S6
python scripts/spike/07_webhooks.py register https://<tunnel>/paypal/webhooks
python scripts/spike/07_webhooks.py listen          # then rerun 04 … wallet
python scripts/spike/08_toolkit.py                  # needs: pip install paypal-agent-toolkit
```

With no credentials every script prints `SKIPPED: no credentials` and exits 0.
Ids carried between steps are kept in `scripts/spike/state.json`, which stays out of git.

## Step results

| # | Prove | Script | Result | Evidence (log entry / debug id) | Notes |
|---|---|---|---|---|---|
| S1 | Auth + basic order | `01_auth_order.py` | ☐ PASS ☐ FAIL | | |
| S2 | Save a PayPal wallet | `02_vault_paypal.py` | ☐ PASS ☐ FAIL | | |
| S3 | Save cards with decline triggers | `03_vault_cards.py` | ☐ PASS ☐ FAIL | | Do triggers survive vaulting? → S5 |
| S4 | Charge saved source, no redirect (wallet) | `04_charge_vaulted.py wallet` | ☐ PASS ☐ FAIL | | Completed on create or needed capture? |
| S4 | Charge saved source, no redirect (card) | `04_charge_vaulted.py card card-clean` | ☐ PASS ☐ FAIL | | |
| S4b | Encoding A (CUSTOMER/ONE_TIME/SUBSEQUENT) | `04 … --encoding A` | ☐ accepted ☐ rejected | | |
| S4b | Encoding B (MERCHANT/UNSCHEDULED/SUBSEQUENT) | `04 … --encoding B` | ☐ accepted ☐ rejected | | |
| S4b | Wallet usage_pattern (unscheduled) | `02 … create --usage-pattern …` | ☐ accepted ☐ rejected | | Pattern value used: _ |
| S5 | Decline on saved card (5120) | `05_decline.py` | ☐ PASS ☐ FAIL | | response_code seen: _ |
| S5b | Negative-testing decline | `05_decline.py mock` | ☐ PASS ☐ FAIL ☐ not needed | | |
| S6 | Alternate source + idempotent replay | `06_recover_alternate.py` | ☐ PASS ☐ FAIL | | Same order id on replay? |
| S7 | Webhooks verify SUCCESS | `07_webhooks.py` | ☐ PASS ☐ FAIL | | Events received: _ |
| S8 | Agent Toolkit read-only get order | `08_toolkit.py` | ☐ PASS ☐ FAIL | | Entry point that worked: _ |

## S4b decision: stored-credential encoding

**Chosen encoding for saved cards:** ☐ A · ☐ B · ☐ neither (wallet for every agent funding source)

**Wallet `usage_pattern`:** _

**Reason (one paragraph for the write-up):**

> _

**Consent text PayPal showed Maya at approval:** (screenshot path) _

## Go / no-go

| Result | Decision | Applies? |
|---|---|---|
| S1, S2, S4, S4b, S6 pass **and** (S5 or S5b) passes | **GO: agent version** | ☐ |
| S4b: only encoding B accepted | GO with B. The write-up explains the merchant charges under consent from onboarding, at the agent's request | ☐ |
| S4b: neither encoding accepted for saved cards, wallet works | GO with the PayPal wallet as every agent funding source; declines via S5b | ☐ |
| S4 fails for PayPal wallet but passes for cards | GO with cards as primary and alternate; wallet only in human escalation | ☐ |
| S4 fails for all saved sources | **Switch to the fallback** (`fallback/PACT-MERCHANT-FALLBACK.md`) | ☐ |
| S5 and S5b both fail | GO; demo declines come from fixture events labelled FIXTURE, and recovery attempts stay real | ☐ |
| S5b fails (even if S5 passes) | GO; scenario S3 uses its budget-based variant | ☐ |
| S7 fails | GO; rely on the reconciler poll; note it in the README | ☐ |
| S8 fails | GO; Ask Pact uses our own read tools; drop the toolkit claim | ☐ |

**Decision:** ☐ GO (agent version) · ☐ GO with caveats: _ · ☐ FALLBACK

## Request log

Each script appends redacted request/response pairs and PASS/FAIL notes below.

<!-- spike-log: scripts append below this line -->
