# 08 · Safety & invariants

## 1. Threat model

| # | Threat | Where | Defence |
|---|---|---|---|
| T1 | Forged recovery offer (fake merchant) | Buyer | Ed25519 signature against the merchant's registered key, verified before parsing; merchant scope check (G4) |
| T1b | One party fabricating the other's message (e.g. merchant inventing an "accept") | Both | Separate Ed25519 keys — no shared secret; both sides store signed bytes as received |
| T2 | Replayed accept → second charge | Merchant | Nonce store + 300 s window; accept idempotent on `(offer_id, option_id)`; `PayPal-Request-Id` derived from it |
| T3 | Merchant raises the price during recovery | Buyer | Offer rule R1; guard G5 compares to the buyer's own purchase record |
| T4 | Injection via offer text | Buyer | Guard never reads prose; quarantine; scanner flag; LLM has no money tools |
| T5 | Retrying a hard decline on the same instrument | Merchant | `HARD_NO_SAME_INSTRUMENT`, `HARD_RISK_NO_AUTONOMY`; offer rule R2/R3 |
| T6 | Agent overspends | Buyer + merchant | Guard G6 on the buyer's ledger; merchant re-checks registered caps on every checkout/accept |
| T7 | Double capture from webhook + poll race | Merchant | Unique outcome per intent; `HARD_ALREADY_PAID` before any new attempt |
| T8 | Forged PayPal webhook | Merchant | `verify-webhook-signature`; unverified events stored but never acted on |
| T9 | Simulated data reaching PayPal or the LLM | Merchant | `provenance.py` gate |
| T10 | LLM invents an action or an amount | Both | LLM outputs are text or schema-validated drafts; no tool path to money |
| T11 | Dark patterns in customer messages | Merchant | Scanner rejects false urgency, invented discounts, pressure; template fallback |
| T12 | Secrets leaking to the browser | Both | Only the services hold PayPal secrets and PRP private keys; web talks to the services' public APIs |
| T14 | Charging a saved method without valid PayPal consent (revoked token, expired mandate, deregistered agent) | Merchant | `HARD_CONSENT_INVALID` re-checked immediately before every PayPal call |
| T13 | `vault_id` exposure to the agent | Merchant | Agent sees aliases only |

## 2. Invariants the test suite must prove

Property tests (hypothesis) generate random offers, mandates, ledgers, event
orders and failures; each invariant is a test name.

| ID | Invariant | Test |
|---|---|---|
| I1 | No intent ever has more than one completed capture | `test_single_capture_per_intent` (random webhook/poll interleavings) |
| I2 | For `retry_same_instrument = false`, no attempt after the failure uses the failed alias | `test_no_same_instrument_after_hard_decline` |
| I3 | `RISK_BLOCKED` never yields an autonomous attempt | `test_risk_never_autonomous` |
| I4 | Every offer's amount equals its intent's amount | `test_offer_amount_immutable` |
| I5 | The guard never ACCEPTs when the amount exceeds remaining budget or per-purchase cap | `test_guard_respects_budget` |
| I6 | The guard's result is independent of `display.text` | `test_guard_ignores_prose` (same offer, random text → same result) |
| I7 | Any signature/nonce/timestamp fault → REJECT before the guard runs | `test_bad_signature_rejected` |
| I8 | Accept is idempotent: N identical accepts → one PayPal order | `test_accept_idempotent` |
| I9 | Expired offers create nothing | `test_expired_offer_inert` |
| I10 | Kill switch on → zero PayPal write calls | `test_kill_switch_blocks_writes` |
| I11 | Simulated events → zero PayPal or LLM calls | `test_provenance_gate` |
| I12 | Hard constraints are evaluated before the score is read | `test_constraints_before_score` (score function raises if called early) |
| I13 | Every engine stage writes exactly one audit row | `test_audit_completeness` |
| I14 | Held-out intents receive no action | `test_holdout_inert` |
| I15 | Outcome write is idempotent across sources | `test_outcome_idempotent` |
| I16 | No PayPal attempt on a saved method without a passing consent check at call time (revocation between accept and call → no call) | `test_consent_checked_at_call_time` |
| I17 | A signature made by one party's key never verifies as the other party's | `test_keys_not_interchangeable` |
| I18 | Signatures bind method and path: a valid `decline` signature fails on `accept` | `test_signature_binds_route` |

## 3. Red-team checklist (run before recording the demo)

- [ ] Send an offer signed with a different Ed25519 key → rejected, security event visible in both consoles.
- [ ] Revoke the saved PayPal method between accept and execution → no PayPal call, `CONSENT_INVALID`.
- [ ] Replay a captured accept request → `409`/`REPLAYED_NONCE`, no new order in PayPal.
- [ ] Offer with amount +$1 → guard REJECT `amount_changed`.
- [ ] Offer listing the failed alias after a 5120 → merchant refuses to build it (unit) and guard rejects it (unit).
- [ ] Injection text S5 → no change in decision; flag shown.
- [ ] Kill switch on mid-scenario → nothing executes; console says so.
- [ ] Post a forged webhook → `400`, not acted on.
- [ ] Turn off the LLM key → everything still works with templates.
