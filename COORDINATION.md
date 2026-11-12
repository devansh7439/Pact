# COORDINATION — multi-session board

Shared by the Claude sessions working in this repo. **Read it before you edit anything outside your area.**
Peers are addressed by session name via `SendMessage` (`ListAgents` shows who is live).

## Rules

1. **Own before you edit.** Edit only paths your session owns (table below). To touch another session's path, message the owner first and either ask them to make the change or get the path handed over. Record the handover in the log.
2. **New paths:** add a row to the ownership table *before* you create files there.
3. **Shared config** (`pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`) goes through **pact-6e**.
4. **Commits and pushes.** The user approved pushing ("push everything", given to pact-e4; initial commit 51fa513). Convention: commit **only your own paths** (another session's paths only with that owner's OK, so nobody pushes a half-finished edit), run `git pull --rebase` before every push, never force-push, and never commit secrets, `.env` files or DBs. If unsure whether the user's approval covers a given push, ask the user, not a peer.
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
| Judge endpoints: `POST /judge/reset`, `POST /judge/scenarios/{S1..S6}/run`, `GET /judge/linked/{intent_id}`, `POST /judge/onboard/{token}` | 6e → e4, f3 | **Done.** e4 built `/judge` and `/judge/run/[intentId]` on them; f3's `deploy/warmup.py` uses them. Judge runs are exempt from the holdout |
| CORS on merchant-api | 6e → e4 | **Done.** One origin, `WEB_PUBLIC_URL` (localhost:3000 by default, the Vercel URL when hosted) |
| Seeding: `scripts/seed.py` is idempotent; a same-key re-register returns the existing registration | 6e → f3 | **Done** (77e0451). The deploy relies on it: free-tier wakes come back with empty DBs |
| Deploy env contract: every setting the services read from env, set in `render.yaml` / Vercel | f3 → 6e, e4 | **Live.** **If you add or rename a `Settings` field or a `NEXT_PUBLIC_*` var that the hosted demo needs, message pact-f3** so `render.yaml` and `deploy/README.md` stay in sync |
| PRP wire format: `schemas/*.json`, `shared/prp` signing and models | e4 → 6e | Done (PRP v0.1). Signed bytes are sent exactly as produced |
| Money: int minor units, `shared/money.py` is the only conversion point | 6e → all | Done |

## Blockers

- **PayPal sandbox credentials: needs the user.** This blocks the P0 spike (`scripts/spike` S1–S8, `RESULTS.md`), live client runs and `verify_live`.

## Known red

- None (pact-6e reports 204 passing after the holdout exemption).

## Handoffs / requests (open)

- [x] 6e → e4: merchant console API contract. e4 consumed it straight from `app.py`/`console.py`
- [x] 6e → e4: `/judge/*` endpoints
- [x] 6e → e4: CORS `localhost:3000`
- [x] f3 → 6e: re-register of an ACTIVE agent returned 409, so reseeding after a free-tier wake failed. Fixed in 77e0451 (same-key re-register is idempotent)
- [x] f3 → e4: register errors were reported as BAD_SIGNATURE. Fixed in 46f0910 (real status surfaced; UNVERIFIED_ERROR when no key is pinned)
- [x] f3 → 6e: judge S1 landed in the 10% holdout about 1 click in 10. Fixed (judge-scripted intents exempt; real traffic keeps the holdout)
- [ ] optional, e4: buyer auto-seed on boot in judge mode (draft → activate → connect → `/judge/onboard`). Not required: `deploy/warmup.py` covers it
- [x] e4: fix the `merchant_links` partial upsert (see Known red). Fixed with `BuyerDB.set_merchant_link_status` (plain UPDATE); test green
- [ ] user: PayPal sandbox credentials
- [x] user: pact-f3 takes deploy (P5)
- [ ] user: create the Render Blueprint + Vercel project (steps in `deploy/README.md`); needs the user's accounts

## Log

```
2026-11-12  pact-f3  created COORDINATION.md; folded in the existing e4/6e ownership split; logged test state (tests: ~18 errors agent_api [6e WIP], 1 fail buyer test_app [e4])
2026-11-12  pact-e4  merchant_links partial-upsert fixed; buyer callback handles registration.active (activates the buyer's mandate copy); /buyer/chat accepts the merchant's dict-shaped catalog  (tests: buyer 47 pass / 0 fail)
2026-11-12  pact-e4  web/: scaffold + /buyer + /merchant console (AG Grid ledger, inspector drawer w/ per-option table, metrics+holdout, review queue, controls, security events), typed clients lib/buyer.ts + lib/merchant.ts built from merchant/app.py + console.py  (tsc clean, next build ok)
2026-11-12  pact-f3  verified buyer suite green (47/0); cleared buyer Known-red; marked console contract consumed; still pending from 6e: /judge/*, CORS
2026-11-12  pact-e4  buyer handles merchant 202 PENDING_REVIEW/SCHEDULED (waits for callback, no approve link); POST /buyer/reset; web/: /judge, /judge/run/[intentId] (two-pane linked view + merged timeline), /onboard/[token]  (tests: full suite 187 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  live two-service run (uvicorn :8100 fixture + :8200): register → onboarding → registration.active callback → chat purchase ORGANIC all work. BUG reported to 6e: merchant/paypal/fixture.py:122 appends "?approval_token_id" to a URL that already has "?", so vault return 422s and onboarding can't complete via approve_url
2026-11-12  pact-6e  merchant backend done: db (append-only audit), PayPal live+fixture client, executor (consent + kill switch at call time), pipeline, offer builder R1-R4, service, app (agent API, onboarding, webhooks, console, CORS :3000), judge endpoints + scripts/seed.py, tests/e2e against the real buyer app; invariants I1 I4 I8 I9 I10 I13 I16 green; fixed e4's fixture approve_url bug; the agent_api sqlite red is resolved (tests: ~198 pass / 0 fail)
2026-11-12  pact-e4  USER APPROVED PUSH ("push everything"). Initial commit 51fa513 pushed to origin/main (130 files; secrets scan clean; .env/DBs/node_modules/spike state ignored). Later work goes in follow-up commits; the user asked for pushes  (tests: 197 pass / 0 fail; tsc clean; next build ok)
2026-11-12  pact-f3  deploy (P5): render.yaml (merchant+buyer on Render free, BLAS pinned to 1 thread: commit 1.2GB→220MB), deploy/warmup.py (wake, seed if needed, prove S1, reset), deploy/README.md runbook incl. Vercel. Verified locally: warmup OK on fresh boot / rerun / buyer-only wipe / merchant-only wipe  (tests: 204 pass on py3.12.13, the Render runtime)
2026-11-12  pact-f3  deploy files pushed by pact-e4 as ef1d334 (user's "push everything"); verified identical to local. Rule 4: committing another owner's paths now needs that owner's OK
2026-11-12  pact-6e  re-register idempotent for same key (f3 cold-start blocker); PRP outcome PAID->ORGANIC on wire; judge runs exempt from holdout and excluded from holdout metrics (+ judge_scripted ledger field); I15 test, so all 18 doc 08 invariants are covered; docs 01-03 + CONTEXT updated (tests: 205 pass / 0 fail)
2026-11-12  pact-e4  web/: redesign UI with dark palette, left sidebar, real live overview (metrics, failure class breakdown, controls & kill switch, review queue actions, decisions table w/ inspector)  (tests: 205 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  web/: fix review items — clear kill-switch label, reactive provenance filter, safe Blob CSV export, race-free decision inspector, graceful null intentId handling in /judge/run/[intentId], deduplicated KPI cards and sidebar navigation  (tests: 205 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  web/: redesign /judge into Agent Mission Control operator workspace (3-column layout, real S1-S6 runs via merchant API, live center timeline, action console with governance controls, reset & role switching)  (tests: 205 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  web/: redesign /buyer (Maya Agent) into BankRails financial autonomy dashboard (BankRails sidebar, 4 KPI cards, Recent Transactions with squircle icons & PRP checklist inspection, Active Agents, Spend Rules, conversational prompt bar, modals for Approvals, Funds, Rules, Keys)  (tests: 205 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  web/: make Maya visual references a linear step-by-step chronological recovery timeline (Decline -> Diagnosis -> PRP Offer -> Guard Verification -> Settlement), removing mock multi-agent sidecars in favor of linear PRP execution audit  (tests: 205 pass / 0 fail; tsc clean, next build ok)
2026-11-12  pact-e4  web/: eliminate 1,400+ lines of clutter (mock metrics strip, fake enterprise personas, redundant pipeline stage banners, verbose text descriptions, disjointed buyer sidebar); streamlined /judge to clean S1-S6 cards, /buyer to focused 5-stage timeline, and unified dark navigation  (tests: full suite 220 pass / 0 fail; tsc clean, next build ok)
```



