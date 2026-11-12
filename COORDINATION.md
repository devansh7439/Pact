# COORDINATION — multi-session board

Shared by the Claude sessions working in this repo. **Read it before you edit anything outside your area.**
Peers are addressed by session name via `SendMessage` (`ListAgents` shows who is live).

## Rules

1. **Own before you edit.** Edit only paths your session owns (table below). To touch another session's path, message the owner first and either ask them to make the change or get the path handed over. Record the handover in the log.
2. **New paths:** add a row to the ownership table *before* you create files there.
3. **Shared config** (`pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`) goes through **pact-6e**.
4. **No commits or pushes** until the user approves. This applies to everyone.
5. **Contracts are pinned here.** If a change alters an API, schema or fixture another session consumes, update the *Contracts* section and message the consumer in the same step.
6. **Log every finished chunk** as one line at the bottom of the log, newest last: `HH:MM  session  what  (tests: N pass / M fail)`.
7. **Leave tests green, or say they're red.** If you leave a test red on purpose, list it under *Known red*. If you see red in someone else's area, report it to the owner and don't fix it.
8. This file is append-mostly. Edit only your own rows; append to the log and to handoffs.

## Ownership

| Session | Area | Owned paths |
|---|---|---|
| **pact-6e** | Merchant backend (P1, P3 merchant side) | `merchant/**`, `shared/money.py`, `tests/merchant/**`, `tests/shared/test_money.py`, `tests/properties/test_merchant_properties.py`, `docs/**`, `README.md`, `CONTEXT.md`, `pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`. Planned: `tests/e2e/**`, `scripts/seed.py`, `merchant/judge.py` |
| **pact-e4** | Buyer agent, PRP, web UI (P2, P3 buyer side) | `buyer_agent/**`, `shared/prp/**`, `tests/buyer/**`, `tests/shared/**` (except `test_money.py`), `tests/properties/test_buyer_properties.py`, `scripts/spike/**`, `web/**` |
| **pact-f3** | Coordination + deploy (P5) | `COORDINATION.md`, `render.yaml`, `deploy/**`. Free tiers: Render for merchant-api and buyer-agent, Vercel for `web/` (configured in the dashboard, so no files in `web/`) |

Unowned and unclaimed: P4 Ask Pact (`merchant/assistant/**`, needs a handover from 6e), P6 Devpost/video material (`docs/submission/**`, needs a handover from 6e).

## Contracts (producer → consumer)

| Contract | Producer → consumer | Status |
|---|---|---|
| Merchant HTTP API used by `web/` (console read models, review queue, controls, security events) | 6e → e4 | **Consumed.** e4 built `web/lib/merchant.ts` from `merchant/app.py` and `console.py` as they stand. **6e: message e4 if any of those route shapes change** |
| Judge endpoints: `POST /judge/reset`, `POST /judge/scenarios/{S1..S6}/run`, `GET /judge/linked/{intent_id}` | 6e → e4 | **Pending** (6e next task b) |
| CORS for `http://localhost:3000` on merchant-api | 6e → e4 | **Requested** |
| PRP wire format: `schemas/*.json`, `shared/prp` signing and models | e4 → 6e | Done (PRP v0.1). Signed bytes are sent exactly as produced |
| Money: int minor units, `shared/money.py` is the only conversion point | 6e → all | Done |

## Blockers

- **PayPal sandbox credentials: needs the user.** This blocks the P0 spike (`scripts/spike` S1–S8, `RESULTS.md`), live client runs and `verify_live`.

## Known red (snapshot 2026-11-12, by pact-f3)

- `tests/merchant/test_agent_api.py`: about 18 setup errors (`sqlite3.OperationalError`). **pact-6e is working on this** (sqlite transaction bug).

## Handoffs / requests (open)

- [x] 6e → e4: merchant console API contract. e4 consumed it straight from `app.py`/`console.py`
- [ ] 6e → e4: `/judge/*` endpoints
- [ ] 6e → e4: CORS `localhost:3000`
- [x] e4: fix the `merchant_links` partial upsert (see Known red). Fixed with `BuyerDB.set_merchant_link_status` (plain UPDATE); test green
- [ ] user: PayPal sandbox credentials
- [ ] user: decide what pact-f3 takes on (deploy / submission docs / Ask Pact)

## Log

```
2026-11-12  pact-f3  created COORDINATION.md; folded in the existing e4/6e ownership split; logged test state (tests: ~18 errors agent_api [6e WIP], 1 fail buyer test_app [e4])
2026-11-12  pact-e4  merchant_links partial-upsert fixed; buyer callback handles registration.active (activates the buyer's mandate copy); /buyer/chat accepts the merchant's dict-shaped catalog  (tests: buyer 47 pass / 0 fail)
2026-11-12  pact-e4  web/: scaffold + /buyer + /merchant console (AG Grid ledger, inspector drawer w/ per-option table, metrics+holdout, review queue, controls, security events), typed clients lib/buyer.ts + lib/merchant.ts built from merchant/app.py + console.py  (tsc clean, next build ok)
2026-11-12  pact-f3  verified buyer suite green (47/0); cleared buyer Known-red; marked console contract consumed; still pending from 6e: /judge/*, CORS
2026-11-12  pact-e4  buyer handles merchant 202 PENDING_REVIEW/SCHEDULED (waits for callback, no approve link); POST /buyer/reset; web/: /judge, /judge/run/[intentId] (two-pane linked view + merged timeline), /onboard/[token]  (tests: full suite 187 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  live two-service run (uvicorn :8100 fixture + :8200): register → onboarding → registration.active callback → chat purchase ORGANIC all work. BUG reported to 6e: merchant/paypal/fixture.py:122 appends "?approval_token_id" to a URL that already has "?", so vault return 422s and onboarding can't complete via approve_url
2026-11-12  pact-6e  merchant backend done: db (append-only audit), PayPal live+fixture client, executor (consent + kill switch at call time), pipeline, offer builder R1-R4, service, app (agent API, onboarding, webhooks, console, CORS :3000), judge endpoints + scripts/seed.py, tests/e2e against the real buyer app; invariants I1 I4 I8 I9 I10 I13 I16 green; fixed e4's fixture approve_url bug; the agent_api sqlite red is resolved (tests: ~198 pass / 0 fail)
```
