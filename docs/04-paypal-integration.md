# 04 · PayPal integration

Every PayPal capability the build relies on, how we use it, and its status.
All calls go to `https://api-m.sandbox.paypal.com`.

## 1. Inventory

| Capability | Endpoints / events | Used for | Status |
|---|---|---|---|
| OAuth 2.0 | `POST /v1/oauth2/token` (client credentials) | Access token, cached until expiry | Standard |
| Orders v2 | `POST /v2/checkout/orders`, `GET /v2/checkout/orders/{id}`, `POST /v2/checkout/orders/{id}/capture` | Every purchase and every recovery attempt | VERIFIED (docs) |
| Processor response | `purchase_units[].payments.captures[].processor_response.response_code` | Decline diagnosis | VERIFIED (docs) |
| Vault v3 — setup tokens | `POST /v3/vault/setup-tokens` → payer approves | Onboarding: save PayPal wallet / card | VERIFIED (docs) |
| Vault v3 — payment tokens | `POST /v3/vault/payment-tokens`, `GET /v3/vault/payment-tokens?customer_id=`, `DELETE /v3/vault/payment-tokens/{id}` | Turn approval into a reusable `vault_id` | VERIFIED (docs) |
| Pay with a saved source | Orders v2 with `payment_source.paypal.vault_id` or `payment_source.card.vault_id` | Agent purchases and alternate-funding recovery, no buyer redirect | Documented · **VERIFY IN SPIKE** on our app |
| Stored-credential indicators | Cards: `payment_source.card.stored_credential` (`payment_initiator`, `payment_type`, `usage`); PayPal wallet: `usage_pattern` at vault creation and on later orders | Declaring correctly who starts each charge on a saved method | Fields VERIFIED (docs) · our encoding **VERIFY IN SPIKE** (S4b) |
| Idempotency | `PayPal-Request-Id` header on every POST | No duplicate orders/captures on retry | Standard |
| Webhooks | `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DECLINED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.REFUNDED`, `CHECKOUT.ORDER.APPROVED`, `CHECKOUT.ORDER.COMPLETED`, `VAULT.PAYMENT-TOKEN.CREATED` | Outcome verification | Event names documented |
| Webhook verification | `POST /v1/notifications/verify-webhook-signature` | Reject forged webhooks | Documented · **VERIFY IN SPIKE** |
| Card decline triggers | Name on card = `CCREJECT-…` in sandbox | Real sandbox declines with real processor codes | VERIFIED (docs) for card checkout · **VERIFY IN SPIKE** for vaulted cards |
| Negative testing | `PayPal-Mock-Response: {"mock_application_codes": "INSTRUMENT_DECLINED"}` | Fallback way to force declines (beta; must be enabled on the sandbox business account) | VERIFY IN SPIKE |
| Subscriptions (P2) | `BILLING.SUBSCRIPTION.PAYMENT.FAILED`, `POST /v1/billing/subscriptions/{id}/capture` with `capture_type: OUTSTANDING_BALANCE` | Human-channel renewal recovery | VERIFIED (docs) |
| Agent Toolkit | `pip install paypal-agent-toolkit` (Python ≥ 3.11) | Ask Pact: read-only order/transaction tools | VERIFIED (docs) |

## 2. Sandbox setup checklist

1. developer.paypal.com → Apps & Credentials → **Sandbox** → create app
   `pact-merchant`. Copy client ID and secret.
2. In the app's features, enable **Save payment methods / Vault** (exact label
   may differ — VERIFY IN SPIKE).
3. Sandbox accounts: one **business** (merchant), two **personal** (Maya, Arjun).
   Record login emails/passwords for the judges' testing instructions.
4. On the business account, enable **negative testing** (Accounts → account →
   settings) for the fallback decline path.
5. Webhooks: add the merchant's public URL `…/paypal/webhooks`, subscribe to the
   events in §1, copy the **Webhook ID** into `PAYPAL_WEBHOOK_ID`.

## 3. Calls in detail

### 3.1 Pay with a saved source (agent purchase / alternate funding)

```http
POST /v2/checkout/orders
Authorization: Bearer <token>
PayPal-Request-Id: att_<intent_id>_<n>
Prefer: return=representation
Content-Type: application/json

{
  "intent": "CAPTURE",
  "purchase_units": [{
    "reference_id": "<intent_id>",
    "custom_id": "<intent_id>",
    "amount": { "currency_code": "USD", "value": "32.00" }
  }],
  "payment_source": { "paypal": { "vault_id": "<vault_id>" } }
}
```

For a saved card use `"payment_source": { "card": { "vault_id": "<vault_id>", "stored_credential": { … } } }`
— the `stored_credential` values are decided in §3.4.
Whether the order completes on create or needs an explicit capture call for
each source type is a spike item; `orders.py` handles both shapes.

`custom_id` carries our intent id so webhooks can be matched without a lookup
table.

### 3.2 Order needing payer approval (escalation / human channel)

Create the order without a `vault_id`, with an `experience_context` whose
`return_url` points at our `/paypal/return` page. Take the `payer-action` /
`approve` link from `links[]` and send it to the human. Capture on
`CHECKOUT.ORDER.APPROVED` (or on return, whichever comes first — capture is
idempotent through `PayPal-Request-Id`).

### 3.3 Onboarding — save PayPal for later

1. `POST /v3/vault/setup-tokens` with `payment_source.paypal` (usage
   `MERCHANT`, customer = our `customer_id`, return/cancel URLs).
2. Redirect the human to the approve link in the response.
3. On return: `POST /v3/vault/payment-tokens` with
   `payment_source.token = { id: <setup_token>, type: "SETUP_TOKEN" }`.
4. Store `vault_id` under the human's `customer_id` with an alias.

For cards, the setup token carries the card data from the card fields (or a
sandbox test card in the spike script).

### 3.4 Consent and stored-credential declaration

**The principle.** A mandate Maya gives her agent is *not* PayPal authorisation to
charge her saved method. PayPal authorisation comes from her approving the
setup token for this merchant (§3.3). The mandate only limits *when the agent may
ask* the merchant to use that authorisation. Both must hold for every charge,
and the write-up says so in plain words.

**How each charge is declared.** PayPal's card stored-credential object has
three fields (VERIFIED from PayPal's SCA payment-indicator docs and the Orders v2
reference):

| Field | Values | Notes from PayPal docs |
|---|---|---|
| `payment_initiator` (required) | `CUSTOMER`, `MERCHANT` | `MERCHANT` means the merchant initiates *and has established consent to charge the buyer* |
| `payment_type` | `ONE_TIME`, `RECURRING`, `UNSCHEDULED` | `ONE_TIME` is the default and only valid with `CUSTOMER` |
| `usage` | `FIRST`, `SUBSEQUENT`, `DERIVED` | `SUBSEQUENT` = a previously saved card is used |

An agent buying on a person's behalf doesn't fit either textbook case cleanly, so
the spike tests both candidate encodings and we pick one with a stated reason:

| Candidate | Encoding | Argument for | Argument against |
|---|---|---|---|
| A · Agent as the customer's delegate | `CUSTOMER` / `ONE_TIME` / `SUBSEQUENT` | The purchase is triggered by the customer's own instruction, through their agent | No human is present to authenticate if the issuer asks |
| B · Merchant charge under consent | `MERCHANT` / `UNSCHEDULED` / `SUBSEQUENT` | Consent was established at onboarding; no customer is in session | The merchant didn't decide to charge — the customer's agent asked |

**Working choice (DESIGN, pending S4b):** A for agent purchases and agent-accepted
recoveries, because the decision to buy originates with the customer's delegate;
B is the fallback if the sandbox rejects A for saved cards. Recoveries always use
the same encoding as the original purchase. Human-channel merchant-initiated
reorders (S6) use B.

**PayPal wallet.** Saved PayPal accounts use a `usage_pattern` set when the token
is created and repeated on later orders; pick the unscheduled pattern that fits
ad-hoc purchases from the Vault/Orders reference during S4b, and record the
consent text PayPal shows Maya on the approval screen (screenshot it — it's
evidence for the write-up).

## 4. Diagnosing declines

Two places a decline can show up, and `taxonomy.py` reads both:

1. **Capture object with `status: DECLINED`** and a `processor_response`
   (`response_code`, `avs_code`, `cvv_code`).
2. **HTTP 422** with an error body whose `details[].issue` names the problem
   (e.g. `INSTRUMENT_DECLINED`, `TRANSACTION_REFUSED`, `PAYER_ACTION_REQUIRED`).

### Sandbox rejection triggers (VERIFIED from PayPal's card-testing page)

Enter the trigger as the card's name / first name. Values are case-sensitive.
PayPal's recommended error-test card: Visa `4012 8888 8888 1881`, any future
expiry, any 3-digit CVV.

| Trigger | Processor code | Name | Our class | Demo scenario |
|---|---|---|---|---|
| `CCREJECT-REFUSED` | `0500` | DO_NOT_HONOR | ISSUER_DECLINED | S3 |
| `CCREJECT-SF` | `9500` | SUSPECTED_FRAUD | RISK_BLOCKED | S2 |
| `CCREJECT-EC` | `5400` | EXPIRED_CARD | INSTRUMENT_INVALID | S4 |
| `CCREJECT-IRC` | `5180` | INVALID_OR_RESTRICTED_CARD | INSTRUMENT_INVALID | — |
| `CCREJECT-IF` | `5120` | INSUFFICIENT_FUNDS | INSUFFICIENT_FUNDS | S1 |
| `CCREJECT-LS` | `9520` | LOST_OR_STOLEN | RISK_BLOCKED | — |
| `CCREJECT-IA` | `1330` | INVALID_ACCOUNT | INSTRUMENT_INVALID | — |
| `CCREJECT-BANK_ERROR` | `5100` | GENERIC_DECLINE | ISSUER_DECLINED | S6 |
| `CCREJECT-CVV_F` | `00N7` | CVV2_FAILURE_POSSIBLE_RETRY_WITH_CVV | AUTH_FAILURE | — |

PayPal's page says that for the suspected-fraud, invalid-or-restricted and
lost-or-stolen triggers you should use another card and not retry the same one.
That guidance is encoded directly as `retry_same_instrument = false` for those
codes and as hard constraint `HARD_RISK_NO_AUTONOMY` for the risk class.

**Demo trick:** vault several sandbox cards for Maya, each named with a different
trigger (`primary-card` = `CCREJECT-IF` for S1, etc.) plus one clean PayPal
wallet. If triggers don't persist through the vault (spike S3), switch to the
negative-testing header for those scenarios.

## 5. Webhooks

```
POST /paypal/webhooks   (raw body preserved)
  1. read headers: paypal-transmission-id, paypal-transmission-time,
     paypal-transmission-sig, paypal-cert-url, paypal-auth-algo
  2. POST /v1/notifications/verify-webhook-signature
     { auth_algo, cert_url, transmission_id, transmission_sig,
       transmission_time, webhook_id: PAYPAL_WEBHOOK_ID, webhook_event: <body> }
  3. verification_status == "SUCCESS" → enqueue; anything else → 400 + audit row
  4. dedupe on event.id
```

Events from the dashboard's webhook simulator may not verify against a real
webhook ID — VERIFY IN SPIKE, and never weaken verification to make them pass;
use real sandbox transactions instead.

**Reconciler fallback:** every open attempt older than 60 s is polled with
`GET /v2/checkout/orders/{id}`. The outcome write is idempotent, so webhook and
poll can both fire.

## 6. PayPal Agent Toolkit — where and why

Used in **Ask Pact**, the merchant's assistant in the console ("why did we lose
revenue on Tuesday?"). The assistant gets:

- Pact read tools (decisions, outcomes, holdout lift), and
- PayPal Agent Toolkit tools configured **read-only** (e.g. get order, list
  transactions).

Not used for money movement in the buyer agent: there, every payment must pass
the mandate guard, so the buyer agent only spends through `prp_client.py`.
Saying this explicitly in the write-up is a feature, not an apology.

## 7. Error handling policy

| PayPal response | Handling |
|---|---|
| 401 | Refresh token once, retry with the same `PayPal-Request-Id` |
| 409 / duplicate request id | Treat as success replay; fetch the order |
| 422 with `details[].issue` | Map through taxonomy → failure event |
| 429 | Back off; executor marks the action `DEFERRED`, never drops it silently |
| 5xx / timeout | Retry up to 3× with the same request id, then `DEFERRED` + reconciler |

## 8. Quotas and provenance

Simulated events (from `simulator/`) carry latent ground-truth fields and are
blocked from reaching PayPal or the LLM by `provenance.py`.
Only seeded demo scenarios and real sandbox transactions call PayPal.
