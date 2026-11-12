# 05 · Decision engine (merchant side)

Pipeline, one audit row per stage:

```
INGEST → DIAGNOSE → SCORE → DECIDE → (HOLDOUT) → ACT → VERIFY → LEARN → MEASURE
```

## 1. Diagnose — PayPal decline taxonomy

`taxonomy.py` maps every PayPal signal we can observe to a **failure class** —
the level at which recovery economics actually differ. Each entry records the
code, PayPal's name, our class, whether the same instrument may be retried, and
PayPal's own guidance where published (with the source URL in code comments).

### Classes

| Class | Meaning | Same instrument retry | Customer-actionable |
|---|---|---|---|
| `INSUFFICIENT_FUNDS` | Funds short right now | Not immediately | Yes — other source or later |
| `INSTRUMENT_INVALID` | Expired, invalid account, restricted card | Never | Yes — other source |
| `ISSUER_DECLINED` | Do-not-honor / generic decline, cause unknown | Not autonomously | Yes — other source |
| `AUTH_FAILURE` | CVV / authentication problem | Only with payer action | Yes — payer must act |
| `RISK_BLOCKED` | Suspected fraud, lost or stolen | **Never** | Only via payer re-authentication |
| `MERCHANT_CONFIG` | Our own setup is wrong | n/a | No — ops queue |
| `ALREADY_PAID` | A later attempt already succeeded | n/a | No — stop |
| `UNKNOWN` | Nothing reliable to go on | Never | Exception queue |

### Starting map (processor codes VERIFIED from the sandbox trigger table)

| PayPal signal | Class |
|---|---|
| processor `5120` INSUFFICIENT_FUNDS | INSUFFICIENT_FUNDS |
| processor `5400` EXPIRED_CARD | INSTRUMENT_INVALID |
| processor `5180` INVALID_OR_RESTRICTED_CARD | INSTRUMENT_INVALID |
| processor `1330` INVALID_ACCOUNT | INSTRUMENT_INVALID |
| processor `0500` DO_NOT_HONOR | ISSUER_DECLINED |
| processor `5100` GENERIC_DECLINE | ISSUER_DECLINED |
| processor `00N7` CVV2_FAILURE_POSSIBLE_RETRY_WITH_CVV | AUTH_FAILURE |
| processor `9500` SUSPECTED_FRAUD | RISK_BLOCKED |
| processor `9520` LOST_OR_STOLEN | RISK_BLOCKED |
| Orders issue `INSTRUMENT_DECLINED` | ISSUER_DECLINED |
| Orders issue `TRANSACTION_REFUSED` | ISSUER_DECLINED |
| Orders issue `PAYER_ACTION_REQUIRED` | AUTH_FAILURE |

**Build task:** transcribe the full processor response code list from the Orders
v2 `processor_response` definition and the Orders v2 error-messages page into
`taxonomy.py`, with a test asserting every code in the table has exactly one
class. Unmapped codes fall to the LLM fallback below, never to a guess.

### LLM fallback

Only for signals the rules can't map (an unknown issue string, an unfamiliar
description). The LLM may propose one of a fixed set of classes with a confidence;
below 0.70 the event stays `UNKNOWN`. LLM-proposed classes cannot unlock
`RETRY_SAME_INSTRUMENT` and run at a reduced autonomy ceiling.

## 2. Score

Calibrated propensity model (`merchant/ml/`):

- `p0` = probability the payment is recovered with **no** action (organic).
- `p(a)` = probability with action `a`, from `p0` and the per-class effectiveness
  matrix (`economics.py`), learned further by `bandit.py` where
  exploration permits.

New features for this build: `channel` (agent / human), number of alternate
funding aliases registered, decline class, amount band, prior failures on this
customer, hour of day.

Reported honestly: ROC AUC against the simulator's measured Bayes
ceiling, calibration bins, and the label **SIMULATED** wherever these numbers
appear.

## 3. Decide — three ordered stages

### Stage 1 · Hard constraints (the score is not read yet)

| Rule | Effect |
|---|---|
| `HARD_KILL_SWITCH` | Record only; execute nothing |
| `HARD_ALREADY_PAID` | Stop: a capture for this intent already completed |
| `HARD_UNDIAGNOSED` | `UNKNOWN` → exception queue |
| `HARD_RISK_NO_AUTONOMY` | `RISK_BLOCKED` → only `PAYER_ACTION_OFFER` (agent) or `ESCALATE` (human channel) |
| `HARD_NO_SAME_INSTRUMENT` | Strip the failed funding source from every option when retry is disallowed |
| `HARD_ATTEMPT_CAP` | ≥ N recovery attempts on this intent → stop |
| `HARD_OPT_OUT` | Customer opted out of contact → no human-channel messages |
| `HARD_HIGH_VALUE_ESCALATION` | Amount above the merchant's autonomy ceiling → review queue |
| `HARD_AGENT_NOT_REGISTERED` | Agent channel without a valid registration → no offer |
| `HARD_CONSENT_INVALID` | No saved method that is active, owned by this customer and covered by an unexpired registered mandate → that method is removed from every option; if none remain, only `PAYER_ACTION_OFFER` / `CHECKOUT_LINK` / `ESCALATE`. **Re-run immediately before every PayPal call**, not just at decision time |

### Stage 2 · Eligibility (what is coherent for this class and channel)

| Class ↓ / Action → | `ALTERNATE_FUNDING_OFFER` | `RETRY_AFTER_OFFER` | `PAYER_ACTION_OFFER` | `CHECKOUT_LINK` | `ESCALATE` | `DROP` |
|---|---|---|---|---|---|---|
| INSUFFICIENT_FUNDS | agent | agent | agent | human | ✓ | ✓ |
| INSTRUMENT_INVALID | agent | — | agent | human | ✓ | ✓ |
| ISSUER_DECLINED | agent | — | agent | human | ✓ | ✓ |
| AUTH_FAILURE | — | — | agent | human | ✓ | ✓ |
| RISK_BLOCKED | — | — | agent | — | ✓ | ✓ |
| MERCHANT_CONFIG | — | — | — | — | ✓ | — |

For the agent channel, Pact chooses **which options go into the offer**: every
eligible option whose NEV clears the floor, plus `CANCEL` always. For the human
channel it chooses one action.

### Stage 3 · Economics

For each eligible action `a`:

```
NEV(a) = (p(a) − p0) · V  −  fee(a)  −  C(a)

V      = amount × contribution_margin          (merchant setting; default 1.0)
fee(a) = (p(a) − p0) × PayPal fee on the amount (3.49% + $0.49 by default; only the
                                                 incremental capture is ours to pay for)
C(a)   = direct_cost(a)                          (messaging, order creation, ops minutes)
       + goodwill_cost(a)                        (modelled irritation; documented, not real)
```

Implemented in `merchant/engine/economics.py` (`value_action`).

Act iff `max NEV ≥ floor` (merchant setting). Otherwise `DROP`, with the
arithmetic stored in the audit row and shown in the console. Because the engine
optimises the *incremental* term `(p(a) − p0)`, it does not spend money nudging
someone who would have come back anyway — the same definition it reports.

### The per-option table (the model's contribution, made visible)

Every decision renders this table in the decision inspector and in the linked
judge view. It is the single clearest picture of what the model does, so it is a
first-class UI element, not a debug panel.

| Option | Chance with action `p(a)` | Chance without `p0` | Lift `p(a) − p0` | Fee + cost | Expected value `NEV(a)` | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Alternate funding (offer) | 76 % | 19 % | +57 pts | $0.92 + $0.20 | **+$17.12** | ✓ chosen |
| Payer action (offer) | 59 % | 19 % | +40 pts | $0.64 + $0.45 | +$11.68 | offered as fallback option |
| Retry later (offer) | 43 % | 19 % | +24 pts | $0.38 + $0.10 | +$7.12 | offered as fallback option |
| Retry same card | — | — | — | — | — | removed: `HARD_NO_SAME_INSTRUMENT` |
| Escalate | 28 % | 19 % | +10 pts | $0.15 + $2.50 | +$0.39 | below the $0.50 floor |
| Drop | — | 19 % | — | $0 | $0.00 | baseline |

*S1 ($32, processor 5120, agent channel) computed by `policy.decide` with an
illustrative base propensity of 0.95 — real decisions use the model's output.
The S1 test in `tests/merchant/test_policy.py` pins this scenario.*

Rules for the table:

- Show `p0` and the lift, not just `p(a)`. A 78 % recovery chance means little if
  70 % would have come back anyway; the lift is what Pact is paid for.
- Every probability is labelled **SIMULATED** (trained on the simulator) until
  there is enough sandbox history to say otherwise; hover shows the model's
  calibration bucket and the AUC-vs-ceiling figures.
- Options removed by stage 1 or 2 appear greyed out with the rule that removed
  them (e.g. "retry same card — `HARD_NO_SAME_INSTRUMENT`"), so the table also
  shows what the system refused to consider.
- For agent-channel offers, the table explains *which options went into the
  offer*; the buyer pane then shows which one the guard picked and why.

## 4. Live holdout

Simulation-based incrementality is useful but easy to dismiss. The live holdout
measures it on real traffic.

- **Assignment:** `sha256(intent_id + HOLDOUT_SALT) mod 10000 < HOLDOUT_RATE × 10000`,
  deterministic and auditable.
- **Who is eligible:** only intents where the engine *would have acted*, not
  `RISK_BLOCKED`, below the high-value ceiling.
- **What happens:** the decision is recorded as `HELD_OUT` with the action it would
  have taken; nothing is sent.
- **What is reported:** recovery rate (acted) − recovery rate (held out), with a
  Wilson 95 % interval for each and the sample size. With small samples the
  console says "not enough data yet" rather than showing a confident number.
- **Provenance:** sandbox-backed and simulated holdouts are reported separately,
  never pooled.

## 5. Act

| Action | Executor does |
|---|---|
| `ALTERNATE_FUNDING_OFFER`, `RETRY_AFTER_OFFER`, `PAYER_ACTION_OFFER` | Build and sign an PRP offer (doc 03); return it in the `402` |
| `CHECKOUT_LINK` | Create an Orders v2 order needing payer approval; LLM writes the message; dark-pattern scanner checks it; deliver to the demo inbox |
| `ESCALATE` | Add to the console review queue with the evidence |
| `DROP` | Nothing; audit row with the reason |

The LLM writes customer-facing text and console explanations only. It never sees
an amount it can change, never picks an action, and has no tool that calls PayPal.

## 6. Verify, learn, measure

- **Verify:** webhooks (verified) + reconciler poll → outcome per intent; a paid
  intent is never actioned again.
- **Learn:** effectiveness constants audited against observed outcomes; Beta
  posteriors move only under bounded exploration; reported, not auto-applied.
- **Measure:** console shows gross recovered, organic, caused (incremental),
  spend, net value, exceptions — split by channel and by provenance.

## 7. Merchant controls

| Setting | Default |
|---|---|
| Mode | `review_first` on first boot; `autonomous` in judge mode |
| EV floor | $0.50 |
| Autonomy ceiling (amount) | $250 |
| Max recovery attempts per intent | 2 |
| Offer TTL | 15 minutes |
| Holdout rate | 10 % |
| Contribution margin | 1.0 |
| Kill switch | Off |
