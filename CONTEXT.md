# CONTEXT — Pact

Snapshot as of 2026-11-12. Read this first; the full detail lives in `docs/`.

## 1. What this is

**Pact: payment recovery for AI agents, on PayPal.** It's an entry for the **PayPal AI Hackathon 2026**.
The protocol is the **Pact Recovery Protocol (PRP v0.1)**.

When an agent's payment is declined, no human is on the checkout page. The **merchant side**
diagnoses the decline, prices each recovery option and issues a **signed recovery offer** (an HTTP `402`).
The **buyer agent** checks the offer against a **mandate** its human approved, then either pays through
PayPal on its own or escalates to the human. The rule throughout: **models predict, policies decide,
LLMs explain. No LLM output can move money.**

## 2. Layout

```
Pact/
├── README.md · LICENSE (MIT) · .env.example · pyproject.toml · requirements.txt · CONTEXT.md
├── docs/00…11-*.md          blueprint (product, protocol, PayPal, engine, buyer, data, safety, plans)
├── fallback/PACT-MERCHANT-FALLBACK.md   merchant-only scope if the spike fails
├── schemas/                 JSON Schemas: recovery_offer, recovery_response, mandate (PRP v0.1)
├── shared/money.py          int minor units ⇄ PayPal "12.34" strings (only place they meet)
├── shared/prp/              PRP signing (Ed25519), keys, ids, Pydantic models   [parallel session]
├── merchant/
│   ├── config.py            env settings; fixture mode without PayPal creds, templates without LLM
│   ├── engine/              taxonomy · economics · policy · holdout · controls · provenance ·
│   │                        diagnosis (LLM fallback) · evaluate
│   ├── integrations/llm.py  customer messages + dark-pattern / unapproved-link checks
│   ├── ml/                  features · train · predict (calibrated RF, SIMULATED data)
│   └── simulator/           PayPal-shaped synthetic declines + counterfactual oracle
├── buyer_agent/             guard (G1–G12), scanner, fixtures …   [parallel session, in progress]
├── tests/{merchant,buyer,shared}/
├── data/model_metrics.json  committed; recovery_model.joblib is gitignored (rebuild with train)
└── _archive/                local only, gitignored: v0.2 zip and a stale doc copy
```

## 3. Running

```bash
.venv/Scripts/python -m pytest                    # 140 passing as of this snapshot, offline
.venv/Scripts/python -m merchant.ml.train
.venv/Scripts/python -m merchant.engine.evaluate
```

The local venv uses Python 3.14 and the docs target ≥ 3.11. The code avoids 3.12+ only features.

## 4. Engine essentials (merchant/engine)

- **Classes:** INSUFFICIENT_FUNDS, INSTRUMENT_INVALID, ISSUER_DECLINED, AUTH_FAILURE, RISK_BLOCKED,
  MERCHANT_CONFIG, ALREADY_PAID, UNKNOWN. `classify(processor_response_code, issue)`: the processor code
  wins over the issue, and anything unmapped is UNKNOWN (exception queue, or the LLM fallback).
- **Actions:** ALTERNATE_FUNDING_OFFER, RETRY_AFTER_OFFER, PAYER_ACTION_OFFER (agent channel);
  CHECKOUT_LINK (human channel); ESCALATE; DROP. RETRY_SAME_INSTRUMENT exists only so the table can
  show it refused, and to serve as the blind-retry baseline. No PayPal class permits it.
- **NEV(a) = lift·amount·margin − lift·PayPal fee − cost(a)**, where lift = p(a) − p0. The engine acts only if the best NEV ≥ the $0.50 floor.
- **`policy.decide`** runs in three stages:
  1. Terminal hard constraints: ALREADY_PAID, UNDIAGNOSED, ATTEMPT_CAP, AGENT_NOT_REGISTERED, HIGH_VALUE.
     LLM-derived diagnoses get ¼ of the autonomy ceiling.
  2. Narrowing constraints: RISK_NO_AUTONOMY, NO_SAME_INSTRUMENT (covers every alias that failed on the intent),
     CONSENT_INVALID, and on the human channel OPT_OUT, CONTACT_DAILY_CAP and CONTACT_COOLDOWN.
     These contact rules also block ESCALATE unless the class is config or risk.
  3. Eligibility by class×channel, then economics.

  The decision carries `options` (the per-option table with verdict or removing rule), `offer_actions`,
  `eligible_funding_aliases` and `execution_blocked_by` (the kill switch records but doesn't execute).
- **Holdout:** `sha256(intent_id+salt) mod 10000 < rate·10000`. Only intents the engine would have acted on are eligible (not risk, not over the ceiling).
  Lift is reported with Wilson intervals, or "not enough data yet" when any arm has fewer than 30 intents.
- **Evaluation (SIMULATED, seed 77771111, 1,000 intents):** Pact nets +$7,747 and blind retry loses −$247.
  Model AUC is 0.56 against a Bayes ceiling of 0.59. The problem is deliberately noisy.

## 5. Rules that must hold (doc 08)

- Money is int minor units, and the only conversion point is `shared/money.py`.
- Consent is re-checked **immediately before every PayPal call** (the executor; not built yet).
- Only `merchant/paypal/` talks to PayPal, only `executor.py` calls its write functions, and the buyer spends only via `guard → prp_client`.
- PRP signatures are verified before parsing, and they bind method, path, timestamp and nonce. Send the signed bytes exactly as produced.
- `display.text` is untrusted and never feeds a decision. The agent sees aliases, never a `vault_id`.
- Simulated data never reaches PayPal or the LLM (`provenance.is_simulated`). Label every metric sandbox, fixture or simulated.

## 6. Status and next steps (2026-11-12)

Three Claude sessions coordinate through `COORDINATION.md`, which holds ownership, contracts and the log:
- **pact-6e** owns the merchant backend and docs.
- **pact-e4** owns the buyer agent, PRP, spike scripts and web.
- **pact-f3** owns coordination and deploy.

Initial commit `51fa513` is on origin/main (pushed by pact-e4 at the user's instruction).

| Phase (doc 10) | State |
|---|---|
| P0 spike | Scripts S1–S8 and the `RESULTS.md` template are written (`scripts/spike/`). **Not run: needs PayPal sandbox credentials.** |
| P1 merchant core | Done, offline: db, PayPal client (live + fixture), executor, pipeline, holdout, outcomes, webhooks and the reconciler. Still to do: bandit/learning, `verify_live`, live verification after the spike |
| P2 console + linked view | API done (`merchant/console.py`). `web/` has /merchant, /buyer, /judge and the linked view, /onboard (pact-e4) |
| P3 agent layer | Done end to end: PRP signing, buyer guard and service, merchant agent API, offer builder. `tests/e2e` runs both real services |
| P4 AI layer | LLM explanations and messages exist. **Ask Pact is not built** (unassigned) |
| P5 deploy + judge | Judge endpoints + `scripts/seed.py` are done. Render deploy is with pact-f3. The services need fixed MERCHANT/BUYER signing keys |
| P6 video + Devpost | Not started |

Invariants (doc 08): 18 of 18 have tests.
Run order for a demo: start merchant (:8100, JUDGE_MODE=true) and buyer (:8200), then run `python -m scripts.seed`, then open web /judge.

## 7. Known gaps

- `taxonomy.py` holds the 9 sandbox processor codes plus 9 Orders issues, and 6 of those issues are DESIGN mappings.
  The full PayPal processor-code list still needs transcribing (doc 05 build task).
- Effectiveness, organic and cost constants are documented modelling assumptions, not measured values.
- The outcome enums disagree between doc 01 §3 and doc 03 §6. Doc 03 is authoritative.
- AG Grid master-detail and row grouping may be Enterprise-only, so check before building the console.
