# 07 · Data model & API

IDs are prefixed ULIDs (`pi_`, `att_`, `dec_`, `off_`, `mdt_`, `gd_` …). Money is
`INTEGER` minor units plus a `currency_code`. Timestamps are UTC ISO-8601.
`provenance` ∈ `sandbox` · `fixture` · `simulated` on every row that feeds a metric.

## 1. Merchant database (`merchant.db`)

| Table | Key columns | Notes |
|---|---|---|
| `customers` | `customer_id`, `display_name`, `paypal_payer_id`, `channel` (`agent`/`human`), `opted_out` | |
| `funding_sources` | `customer_id`, `alias`, `kind`, `vault_id`, `status` | `vault_id` never leaves the merchant |
| `agent_registrations` | `agent_id`, `customer_id`, `agent_public_key`, `key_id`, `callback_url`, `status` | Public key only; the agent keeps its private key |
| `registered_mandates` | `mandate_id`, `agent_id`, `caps_json`, `approved_by_payer_id`, `approved_at`, `approval_ref` | The merchant's copy of what the human approved |
| `payment_intents` | `intent_id`, `customer_id`, `channel`, `amount_minor`, `currency_code`, `items_json`, `state`, `outcome`, `provenance` | One per purchase |
| `attempts` | `attempt_id`, `intent_id`, `paypal_order_id`, `paypal_capture_id`, `funding_alias`, `request_id`, `status`, `processor_code`, `issue`, `raw_json` | One per PayPal order |
| `failures` | `failure_id`, `attempt_id`, `failure_class`, `retry_same_instrument`, `diagnosed_by` (`rules`/`llm`), `confidence` | |
| `decisions` | `decision_id`, `intent_id`, `stage_trace_json`, `chosen_action`, `nev_minor`, `alternatives_json`, `held_out`, `mode` | Stage trace = all three stages |
| `offers` | `offer_id`, `intent_id`, `decision_id`, `body_json`, `expires_at`, `status`, `accepted_option_id` | Body exactly as signed |
| `actions` | `action_id`, `decision_id`, `kind`, `paypal_order_id`, `approve_url`, `message_text`, `status` | |
| `webhook_events` | `event_id` (PayPal's), `event_type`, `verified`, `received_at`, `body_json` | Dedupe on `event_id` |
| `outcomes` | `intent_id`, `outcome`, `source` (`webhook`/`poll`/`simulator`), `recovered_minor`, `attributed_action_id` | Unique on `intent_id` |
| `audit_trail` | `seq`, `intent_id`, `stage`, `payload_json`, `created_at` | Append-only; no UPDATE/DELETE path in code |
| `controls` | `key`, `value`, `updated_at` | Mode, floor, ceiling, kill switch, holdout rate |
| `security_events` | `id`, `kind`, `detail_json`, `created_at` | Bad signatures, replays, scanner hits |

## 2. Buyer database (`buyer.db`)

| Table | Key columns | Notes |
|---|---|---|
| `principals` | `principal_id`, `display_name` | |
| `mandates` | `mandate_id`, `principal_id`, `body_json`, `status` | Buyer's copy |
| `merchant_links` | `merchant_id`, `base_url`, `agent_id`, `merchant_public_key`, `merchant_key_id`, `mandate_id` | The agent's own private key lives in its environment (`BUYER_SIGNING_KEY`), never in the DB |
| `purchases` | `purchase_id`, `merchant_id`, `intent_id`, `amount_minor`, `funding_alias`, `status` | The guard compares offers against this |
| `offers_received` | `offer_id`, `purchase_id`, `body_json`, `signature_ok`, `scanner_flags_json` | |
| `guard_decisions` | `gd_id`, `offer_id`, `result`, `rule_fired`, `option_id`, `alias`, `reason` | |
| `budget_ledger` | `entry_id`, `mandate_id`, `period_start`, `amount_minor`, `purchase_id` | Spend counted on capture only |
| `inbox` | `msg_id`, `principal_id`, `kind`, `text`, `approve_url`, `status` | |

## 3. Merchant HTTP API

### Agent API (PRP v0.1 — see doc 03)

`POST /agent/v1/register` · `POST /agent/v1/checkout` ·
`GET /agent/v1/offers/{id}` · `POST /agent/v1/offers/{id}/accept` ·
`POST /agent/v1/offers/{id}/decline` · `GET /agent/v1/intents/{id}`

### Storefront & onboarding

| Method & path | Purpose |
|---|---|
| `GET /store/catalog` | Products |
| `GET /onboard/{token}` (data for the web page) | Caps to approve, funding sources to save |
| `POST /onboard/{token}/vault/paypal` | Create setup token → approve link |
| `GET /paypal/return` | Return from PayPal approval (vault or order) |
| `POST /onboard/{token}/confirm` | Mandate approved → registration active |

### PayPal

| Method & path | Purpose |
|---|---|
| `POST /paypal/webhooks` | Verified webhook intake |

### Console

| Method & path | Purpose |
|---|---|
| `GET /console/feed?since=` | Live event feed (intents, failures, decisions, outcomes) |
| `GET /console/decisions/{id}` | Decision inspector: stage trace, **per-option table** (p(a), p0, lift, cost, NEV, verdict, rule that removed it), audit rows |
| `GET /console/review-queue` · `POST /console/review-queue/{id}/approve` · `…/reject` | Review-first approvals |
| `GET /console/metrics?provenance=sandbox|simulated` | Gross / organic / caused / spend / net; holdout lift with intervals |
| `GET /console/model` | Model metrics vs ceiling (SIMULATED) |
| `GET/POST /console/controls` | Mode, floor, ceiling, holdout, kill switch |
| `POST /console/ask` | Ask Pact (LLM + read-only tools) |
| `GET /console/security-events` | |

### Judge mode

| Method & path | Purpose |
|---|---|
| `POST /judge/reset` | Reseed both services to the scenario baseline |
| `POST /judge/scenarios/{S1..S6}/run` | Run one scenario end-to-end against the PayPal sandbox; returns `intent_id` and a timeline |
| `GET /judge/linked/{intent_id}` | One payload for the linked view: merchant decision + per-option table, offer(s) as signed, buyer guard checklist(s), PayPal order ids, outcome, merged timeline |
| `GET /health` | Mode of each integration: `live` / `fixture` / `disabled` |

## 4. Buyer-agent HTTP API

| Method & path | Purpose |
|---|---|
| `POST /buyer/chat` | Talk to the agent (draft mandate, place an order) |
| `GET /buyer/mandates` · `POST /buyer/mandates/draft` | Mandate drafts and status |
| `POST /buyer/merchants/{id}/connect` | Start registration with a merchant |
| `GET /buyer/purchases` · `GET /buyer/purchases/{id}` | Purchases with guard decisions and the rendered checklist |
| `GET /buyer/by-intent/{intent_id}` | Buyer-side view of a merchant intent (powers the linked view) |
| `GET /buyer/inbox` · `POST /buyer/inbox/{id}/dismiss` | Human inbox |
| `POST /buyer/pause` · `POST /buyer/resume` | Buyer-side kill switch |
| `POST /prp/callback` | Optional merchant push (`intent.updated`), signed |

## 5. Web routes

| Route | Persona | Key components |
|---|---|---|
| `/judge` | Judge | Scenario cards (S1–S4 core, S5 flash, S6 optional), "Run", reset |
| `/judge/run/[intentId]` | Judge | **Linked view**: merchant pane (decision, per-option table) · buyer pane (offer, guard checklist) · shared timeline with PayPal order ids |
| `/merchant` | Merchant | Live feed, AG Grid decision ledger, decision inspector drawer, metrics, holdout panel, review queue, controls, Ask Pact |
| `/buyer` | Maya | Chat, mandate card, budget meter, purchases with the guard checklist, inbox |
| `/onboard/[token]` | Maya | Caps table, "Save PayPal" button, approve |
| `/customer/[id]` | Arjun | Inbox with recovery message and PayPal link |
