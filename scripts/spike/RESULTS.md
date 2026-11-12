# Spike results: PayPal feasibility (doc 09)

**Status:** PARTIAL · **Timebox:** 3½ h · **Dates:** 2026-11-12 (UTC, both runs)

- **S1 passed:** order created, approved by a sandbox buyer, captured `COMPLETED`.
- **S8 passed** (second run, 21:2xZ): the Agent Toolkit's framework-neutral core (`paypal_agent_toolkit.shared.api.PayPalAPI`, method `get_order_details`) returned the S1 order.
- **S2 unblocked, not finished:** the first run's wallet setup tokens got `403 NOT_AUTHORIZED`. After the sandbox app's Vault feature was enabled, the OAuth token gained `vault/payment-tokens/readwrite` and the second run's setup token returned **201**. It still needs a sandbox buyer to approve it, then `02_vault_paypal.py finish`.
- **S3 still blocked:** card setup tokens return `403` with issue `NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE` ("not allowed to vault the given source"). The sandbox app or business account isn't enabled to save cards.
- **S4–S7 not run:** each needs a saved payment method (S7 also needs a public webhook URL).

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
| S1 | Auth + basic order | `01_auth_order.py` | ☑ PASS ☐ FAIL | order `6VX14008JC947302G`, capture `4UG61505X30485236` | Created, approved by a sandbox buyer, captured `COMPLETED` |
| S2 | Save a PayPal wallet | `02_vault_paypal.py` | ☐ PASS ☐ FAIL (in progress) | run 1: 403 (`f7083825e4d26`, `ca597b3a19c77`, `ca597b4794872`); run 2: 201 (`f264306fc02e1`) | Setup token created after Vault was enabled; awaiting buyer approval + `finish` |
| S3 | Save cards with decline triggers | `03_vault_cards.py` | ☐ PASS ☑ FAIL | debug ids `f443778a3c836`, `f6914663309bf`, `f691466da1b41`, `f679861afc9ae`, `f704261e9e032` | 403 on all five cards, both runs. Run 2 issue: `NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE` (debug `f391945527e31`) |
| S4 | Charge saved source, no redirect (wallet) | `04_charge_vaulted.py wallet` | ☐ PASS ☐ FAIL | | Completed on create or needed capture? |
| S4 | Charge saved source, no redirect (card) | `04_charge_vaulted.py card card-clean` | ☐ PASS ☐ FAIL | | |
| S4b | Encoding A (CUSTOMER/ONE_TIME/SUBSEQUENT) | `04 … --encoding A` | ☐ accepted ☐ rejected | | |
| S4b | Encoding B (MERCHANT/UNSCHEDULED/SUBSEQUENT) | `04 … --encoding B` | ☐ accepted ☐ rejected | | |
| S4b | Wallet usage_pattern (unscheduled) | `02 … create --usage-pattern …` | ☐ accepted ☐ rejected | | Pattern value used: _ |
| S5 | Decline on saved card (5120) | `05_decline.py` | ☐ PASS ☐ FAIL | | response_code seen: _ |
| S5b | Negative-testing decline | `05_decline.py mock` | ☐ PASS ☐ FAIL ☐ not needed | | |
| S6 | Alternate source + idempotent replay | `06_recover_alternate.py` | ☐ PASS ☐ FAIL | | Same order id on replay? |
| S7 | Webhooks verify SUCCESS | `07_webhooks.py` | ☐ PASS ☐ FAIL | | Events received: _ |
| S8 | Agent Toolkit read-only get order | `08_toolkit.py` | ☑ PASS ☐ FAIL | S1 order `6VX14008JC947302G` returned `COMPLETED` | Entry point that worked: `shared.api.PayPalAPI.run("get_order_details")` (framework adapters need `agents`/`langchain`) |

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

### S1 · OAuth token · 2026-11-12 18:36:48Z

`POST /v1/oauth2/token` → **200** · debug id `f75614476b70b`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 32391,
  "nonce": "2026-11-12T18:36:39ZbZEzSWtQRNkunhFJPb3CVWacZKCtinKO0_ypmjWhfbE"
}
```

</details>

### S1 · create order (payer approval) · 2026-11-12 18:36:49Z

`POST /v2/checkout/orders` → **200** · debug id `f6193946213cc`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s1_create_1794508606"
  },
  "body": {
    "intent": "CAPTURE",
    "purchase_units": [
      {
        "reference_id": "pi_spike_s1",
        "custom_id": "pi_spike_s1",
        "amount": {
          "currency_code": "USD",
          "value": "32.00"
        }
      }
    ],
    "payment_source": {
      "paypal": {
        "experience_context": {
          "brand_name": "Kettle & Crumb (sandbox)",
          "shipping_preference": "NO_SHIPPING",
          "user_action": "PAY_NOW",
          "return_url": "http://localhost:8100/paypal/return",
          "cancel_url": "http://localhost:8100/paypal/return?cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "id": "6VX14008JC947302G",
  "intent": "CAPTURE",
  "status": "PAYER_ACTION_REQUIRED",
  "payment_source": {
    "paypal": {}
  },
  "purchase_units": [
    {
      "reference_id": "pi_spike_s1",
      "amount": {
        "currency_code": "USD",
        "value": "32.00"
      },
      "payee": {
        "email_address": "sb-uctej53876657@business.example.com",
        "merchant_id": "6RBCNPTNEGQXS",
        "display_data": {
          "brand_name": "Kettle & Crumb (sandbox)"
        }
      },
      "custom_id": "pi_spike_s1"
    }
  ],
  "links": [
    {
      "href": "https://api.sandbox.paypal.com/v2/checkout/orders/6VX14008JC947302G",
      "rel": "self",
      "method": "GET"
    },
    {
      "href": "https://www.sandbox.paypal.com/checkoutnow?token=6VX14008JC947302G",
      "rel": "payer-action",
      "method": "GET"
    }
  ]
}
```

</details>

### S3 · OAuth token · 2026-11-12 18:36:55Z

`POST /v1/oauth2/token` → **200** · debug id `f247597cd0cbd`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 32384,
  "nonce": "2026-11-12T18:36:39ZbZEzSWtQRNkunhFJPb3CVWacZKCtinKO0_ypmjWhfbE"
}
```

</details>

### S3 · setup token (card card-if) · 2026-11-12 18:36:56Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f443778a3c836`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-if_1794508614"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-IF",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "f443778a3c836",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-if: HTTP 403

### S3 · setup token (card card-sf) · 2026-11-12 18:36:57Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f6914663309bf`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-sf_1794508616"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-SF",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "f6914663309bf",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-sf: HTTP 403

### S3 · setup token (card card-refused) · 2026-11-12 18:36:58Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f691466da1b41`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-refused_1794508617"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-REFUSED",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "f691466da1b41",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-refused: HTTP 403

### S3 · setup token (card card-ec) · 2026-11-12 18:36:59Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f679861afc9ae`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-ec_1794508618"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-EC",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "f679861afc9ae",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-ec: HTTP 403

### S3 · setup token (card card-clean) · 2026-11-12 18:37:00Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f704261e9e032`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-clean_1794508619"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "Maya Sandbox",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "f704261e9e032",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-clean: HTTP 403

### S2 · OAuth token · 2026-11-12 18:37:19Z

`POST /v1/oauth2/token` → **200** · debug id `f5141232d629c`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 32360,
  "nonce": "2026-11-12T18:36:39ZbZEzSWtQRNkunhFJPb3CVWacZKCtinKO0_ypmjWhfbE"
}
```

</details>

### S2 · setup token (paypal, IMMEDIATE) · 2026-11-12 18:37:20Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f7083825e4d26`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s2_setup_IMMEDIATE_1794508638"
  },
  "body": {
    "payment_source": {
      "paypal": {
        "description": "Kettle & Crumb \u2014 let your agent pay with PayPal (sandbox)",
        "usage_type": "MERCHANT",
        "usage_pattern": "IMMEDIATE",
        "customer_type": "CONSUMER",
        "permit_multiple_payment_tokens": true,
        "experience_context": {
          "brand_name": "Kettle & Crumb (sandbox)",
          "shipping_preference": "NO_SHIPPING",
          "return_url": "http://localhost:8100/paypal/return?vault=1",
          "cancel_url": "http://localhost:8100/paypal/return?vault=1&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "f7083825e4d26",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S2** — FAIL setup token with usage_pattern=IMMEDIATE: HTTP 403

### S1 · OAuth token · 2026-11-12 18:46:40Z

`POST /v1/oauth2/token` → **200** · debug id `f1322239944ea`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 31800,
  "nonce": "2026-11-12T18:36:39ZbZEzSWtQRNkunhFJPb3CVWacZKCtinKO0_ypmjWhfbE"
}
```

</details>

### S1 · capture order · 2026-11-12 18:46:41Z

`POST /v2/checkout/orders/6VX14008JC947302G/capture` → **201** · debug id `f132223645325`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s1_capture_6VX14008JC947302G"
  },
  "body": {}
}
```

```json
{
  "id": "6VX14008JC947302G",
  "intent": "CAPTURE",
  "status": "COMPLETED",
  "payment_source": {
    "paypal": {
      "email_address": "sb-7e4qb53889901@personal.example.com",
      "account_id": "DRQ9HLEXXLHBU",
      "account_status": "VERIFIED",
      "name": {
        "given_name": "John",
        "surname": "Doe"
      },
      "address": {
        "country_code": "US"
      }
    }
  },
  "purchase_units": [
    {
      "reference_id": "pi_spike_s1",
      "amount": {
        "currency_code": "USD",
        "value": "32.00"
      },
      "payee": {
        "email_address": "sb-uctej53876657@business.example.com",
        "merchant_id": "6RBCNPTNEGQXS",
        "display_data": {
          "brand_name": "Kettle & Crumb (sandbox)"
        }
      },
      "custom_id": "pi_spike_s1",
      "payments": {
        "captures": [
          {
            "id": "4UG61505X30485236",
            "status": "COMPLETED",
            "amount": {
              "currency_code": "USD",
              "value": "32.00"
            },
            "final_capture": true,
            "seller_protection": {
              "status": "ELIGIBLE",
              "dispute_categories": [
                "ITEM_NOT_RECEIVED",
                "UNAUTHORIZED_TRANSACTION"
              ]
            },
            "seller_receivable_breakdown": {
              "gross_amount": {
                "currency_code": "USD",
                "value": "32.00"
              },
              "paypal_fee": {
                "currency_code": "USD",
                "value": "1.83"
              },
              "net_amount": {
                "currency_code": "USD",
                "value": "30.17"
              }
            },
            "custom_id": "pi_spike_s1",
            "links": [
              {
                "href": "https://api.sandbox.paypal.com/v2/payments/captures/4UG61505X30485236",
                "rel": "self",
                "method": "GET"
              },
              {
                "href": "https://api.sandbox.paypal.com/v2/payments/captures/4UG61505X30485236/refund",
                "rel": "refund",
                "method": "POST"
              },
              {
                "href": "https://api.sandbox.paypal.com/v2/checkout/orders/6VX14008JC947302G",
                "rel": "up",
                "method": "GET"
              }
            ],
            "create_time": "2026-11-12T18:46:40Z",
            "update_time": "2026-11-12T18:46:40Z"
          }
        ]
      }
    }
  ],
  "payer": {
    "name": {
      "given_name": "John",
      "surname": "Doe"
    },
    "email_address": "sb-7e4qb53889901@personal.example.com",
    "payer_id": "DRQ9HLEXXLHBU",
    "address": {
      "country_code": "US"
    }
  },
  "create_time": "2026-11-12T18:36:49Z",
  "update_time": "2026-11-12T18:46:40Z",
  "links": [
    {
      "href": "https://api.sandbox.paypal.com/v2/checkout/orders/6VX14008JC947302G",
      "rel": "self",
      "method": "GET"
    }
  ]
}
```

</details>

> **S1** — PASS capture: {'order_id': '6VX14008JC947302G', 'order_status': 'COMPLETED', 'capture_id': '4UG61505X30485236', 'capture_status': 'COMPLETED', 'processor_response': None, 'issue': None}

### S2 · OAuth token · 2026-11-12 18:46:49Z

`POST /v1/oauth2/token` → **200** · debug id `ca597b39f3aa8`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 31790,
  "nonce": "2026-11-12T18:36:39ZbZEzSWtQRNkunhFJPb3CVWacZKCtinKO0_ypmjWhfbE"
}
```

</details>

### S2 · setup token (paypal, IMMEDIATE) · 2026-11-12 18:46:50Z

`POST /v3/vault/setup-tokens` → **403** · debug id `ca597b3a19c77`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s2_setup_IMMEDIATE_1794509206"
  },
  "body": {
    "payment_source": {
      "paypal": {
        "description": "Kettle & Crumb \u2014 let your agent pay with PayPal (sandbox)",
        "usage_type": "MERCHANT",
        "usage_pattern": "IMMEDIATE",
        "customer_type": "CONSUMER",
        "permit_multiple_payment_tokens": true,
        "experience_context": {
          "brand_name": "Kettle & Crumb (sandbox)",
          "shipping_preference": "NO_SHIPPING",
          "return_url": "http://localhost:8100/paypal/return?vault=1",
          "cancel_url": "http://localhost:8100/paypal/return?vault=1&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "ca597b3a19c77",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S2** — FAIL setup token with usage_pattern=IMMEDIATE: HTTP 403

### S2 · OAuth token · 2026-11-12 18:47:24Z

`POST /v1/oauth2/token` → **200** · debug id `ca597b472bde5`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 31755,
  "nonce": "2026-11-12T18:36:39ZbZEzSWtQRNkunhFJPb3CVWacZKCtinKO0_ypmjWhfbE"
}
```

</details>

### S2 · setup token (paypal, IMMEDIATE) · 2026-11-12 18:47:24Z

`POST /v3/vault/setup-tokens` → **403** · debug id `ca597b4794872`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s2_setup_IMMEDIATE_1794509243"
  },
  "body": {
    "payment_source": {
      "paypal": {
        "description": "Kettle & Crumb \u2014 let your agent pay with PayPal (sandbox)",
        "usage_type": "MERCHANT",
        "usage_pattern": "IMMEDIATE",
        "customer_type": "CONSUMER",
        "permit_multiple_payment_tokens": true,
        "experience_context": {
          "brand_name": "Kettle & Crumb (sandbox)",
          "shipping_preference": "NO_SHIPPING",
          "return_url": "http://localhost:8100/paypal/return?vault=1",
          "cancel_url": "http://localhost:8100/paypal/return?vault=1&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "debug_id": "ca597b4794872",
  "message": "Authorization failed due to insufficient permissions.",
  "details": [
    {
      "issue": "NOT_AUTHORIZED",
      "description": "Authorization failed due to insufficient permissions."
    }
  ]
}
```

</details>

> **S2** — FAIL setup token with usage_pattern=IMMEDIATE: HTTP 403

### S3 · OAuth token · 2026-11-12 21:20:26Z

`POST /v1/oauth2/token` → **200** · debug id `f82739194aca7`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/invoicing https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/vault/payment-tokens/read https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/vault/payment-tokens/readwrite https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid Braintree:Vault https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 32400,
  "nonce": "2026-11-12T21:20:26Zu75_jLeKdrPo4z84S1ysh-8xL3BvVy2FHjocbdqAkvU"
}
```

</details>

### S3 · setup token (card card-if) · 2026-11-12 21:20:27Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f432517422d94`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-if_1794518425"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-IF",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "message": "Authorization failed due to insufficient permissions.",
  "debug_id": "f432517422d94",
  "details": [
    {
      "issue": "NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE",
      "description": "The API caller or the merchant on whose behalf the API call is initiated is not allowed to vault the given source. Please contact PayPal customer support for assistance."
    }
  ],
  "links": [
    {
      "href": "https://developer.paypal.com/docs/limited-release/payment-tokens/v3/api/#error-FORBIDDEN",
      "method": "GET"
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-if: HTTP 403

### S3 · setup token (card card-sf) · 2026-11-12 21:20:27Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f43251710707c`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-sf_1794518427"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-SF",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "message": "Authorization failed due to insufficient permissions.",
  "debug_id": "f43251710707c",
  "details": [
    {
      "issue": "NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE",
      "description": "The API caller or the merchant on whose behalf the API call is initiated is not allowed to vault the given source. Please contact PayPal customer support for assistance."
    }
  ],
  "links": [
    {
      "href": "https://developer.paypal.com/docs/limited-release/payment-tokens/v3/api/#error-FORBIDDEN",
      "method": "GET"
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-sf: HTTP 403

### S3 · setup token (card card-refused) · 2026-11-12 21:20:28Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f893008d8821f`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-refused_1794518427"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-REFUSED",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "message": "Authorization failed due to insufficient permissions.",
  "debug_id": "f893008d8821f",
  "details": [
    {
      "issue": "NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE",
      "description": "The API caller or the merchant on whose behalf the API call is initiated is not allowed to vault the given source. Please contact PayPal customer support for assistance."
    }
  ],
  "links": [
    {
      "href": "https://developer.paypal.com/docs/limited-release/payment-tokens/v3/api/#error-FORBIDDEN",
      "method": "GET"
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-refused: HTTP 403

### S3 · setup token (card card-ec) · 2026-11-12 21:20:29Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f8930088618be`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-ec_1794518428"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "CCREJECT-EC",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "message": "Authorization failed due to insufficient permissions.",
  "debug_id": "f8930088618be",
  "details": [
    {
      "issue": "NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE",
      "description": "The API caller or the merchant on whose behalf the API call is initiated is not allowed to vault the given source. Please contact PayPal customer support for assistance."
    }
  ],
  "links": [
    {
      "href": "https://developer.paypal.com/docs/limited-release/payment-tokens/v3/api/#error-FORBIDDEN",
      "method": "GET"
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-ec: HTTP 403

### S3 · setup token (card card-clean) · 2026-11-12 21:20:29Z

`POST /v3/vault/setup-tokens` → **403** · debug id `f391945527e31`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s3_setup_card-clean_1794518429"
  },
  "body": {
    "payment_source": {
      "card": {
        "number": "4012********1881",
        "expiry": "2030-12",
        "security_code": "[REDACTED]",
        "name": "Maya Sandbox",
        "experience_context": {
          "return_url": "http://localhost:8100/paypal/return?vault=card",
          "cancel_url": "http://localhost:8100/paypal/return?vault=card&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "name": "NOT_AUTHORIZED",
  "message": "Authorization failed due to insufficient permissions.",
  "debug_id": "f391945527e31",
  "details": [
    {
      "issue": "NOT_ENABLED_TO_VAULT_PAYMENT_SOURCE",
      "description": "The API caller or the merchant on whose behalf the API call is initiated is not allowed to vault the given source. Please contact PayPal customer support for assistance."
    }
  ],
  "links": [
    {
      "href": "https://developer.paypal.com/docs/limited-release/payment-tokens/v3/api/#error-FORBIDDEN",
      "method": "GET"
    }
  ]
}
```

</details>

> **S3** — FAIL setup token card-clean: HTTP 403

### S2 · OAuth token · 2026-11-12 21:20:48Z

`POST /v1/oauth2/token` → **200** · debug id `f9435351f8650`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]"
  },
  "body": {
    "grant_type": "client_credentials"
  }
}
```

```json
{
  "scope": "https://uri.paypal.com/services/invoicing https://uri.paypal.com/services/checkout/one-click-with-merchant-issued-token https://uri.paypal.com/services/payments/futurepayments https://uri.paypal.com/services/vault/payment-tokens/read https://uri.paypal.com/services/disputes/read-buyer https://uri.paypal.com/services/payments/realtimepayment https://uri.paypal.com/services/subscriptions/confirm-payment https://uri.paypal.com/services/payments/client-payments-eligibility https://api.paypal.com/v1/vault/credit-card https://api.paypal.com/v1/payments/.* https://uri.paypal.com/services/vault/payment-tokens/readwrite https://uri.paypal.com/services/applications/webhooks https://uri.paypal.com/services/pricing/exchange-currency/read https://uri.paypal.com/services/credit/client-offer-presentment/read https://uri.paypal.com/services/disputes/update-seller https://uri.paypal.com/services/payments/payment/authcapture openid Braintree:Vault https://uri.paypal.com/services/disputes/read-seller https://uri.paypal.com/services/payments/orders/client_sdk_orders_api https://uri.paypal.com/services/payments/refund https://uri.paypal.com/services/disputes/create https://uri.paypal.com/services/pricing/quote-exchange-rates/read https://uri.paypal.com/services/documents/disputes/download https://uri.paypal.com/services/billing-agreements https://uri.paypal.com/services/checkout/payment-resources https://uri.paypal.com/payments/payouts https://api.paypal.com/v1/vault/credit-card/.* https://uri.paypal.com/services/shipping/trackers/readwrite https://uri.paypal.com/services/subscriptions",
  "access_token": "[REDACTED]",
  "token_type": "Bearer",
  "app_id": "APP-0XS15166W95391723",
  "expires_in": 32378,
  "nonce": "2026-11-12T21:20:26Zu75_jLeKdrPo4z84S1ysh-8xL3BvVy2FHjocbdqAkvU"
}
```

</details>

### S2 · setup token (paypal, IMMEDIATE) · 2026-11-12 21:20:49Z

`POST /v3/vault/setup-tokens` → **201** · debug id `f264306fc02e1`

<details><summary>request / response (redacted)</summary>

```json
{
  "headers": {
    "Authorization": "[REDACTED]",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
    "PayPal-Request-Id": "spike_s2_setup_IMMEDIATE_1794518447"
  },
  "body": {
    "payment_source": {
      "paypal": {
        "description": "Kettle & Crumb \u2014 let your agent pay with PayPal (sandbox)",
        "usage_type": "MERCHANT",
        "usage_pattern": "IMMEDIATE",
        "customer_type": "CONSUMER",
        "permit_multiple_payment_tokens": true,
        "experience_context": {
          "brand_name": "Kettle & Crumb (sandbox)",
          "shipping_preference": "NO_SHIPPING",
          "return_url": "http://localhost:8100/paypal/return?vault=1",
          "cancel_url": "http://localhost:8100/paypal/return?vault=1&cancel=1"
        }
      }
    }
  }
}
```

```json
{
  "id": "37J54500LJ684320Y",
  "customer": {
    "id": "SkVHOvlCcq"
  },
  "status": "PAYER_ACTION_REQUIRED",
  "payment_source": {
    "paypal": {
      "description": "Kettle & Crumb \u2014 let your agent pay with PayPal (sandbox)",
      "usage_pattern": "IMMEDIATE",
      "permit_multiple_payment_tokens": true,
      "usage_type": "MERCHANT",
      "customer_type": "CONSUMER"
    }
  },
  "links": [
    {
      "href": "https://api.sandbox.paypal.com/v3/vault/setup-tokens/37J54500LJ684320Y",
      "rel": "self",
      "method": "GET",
      "encType": "application/json"
    },
    {
      "href": "https://www.sandbox.paypal.com/agreements/approve?approval_session_id=37J54500LJ684320Y",
      "rel": "approve",
      "method": "GET",
      "encType": "application/json"
    }
  ]
}
```

</details>

> **S8** — FAIL toolkit: RuntimeError('paypal_agent_toolkit.openai.toolkit: ModuleNotFoundError("No module named \'agents\'"); paypal_agent_toolkit.langchain.toolkit: ModuleNotFoundError("No module named \'langchain\'"); paypal_agent_toolkit.crewai.toolkit: ModuleNotFoundError("No module named \'paypal_agent_toolkit.crewai\'")')

> **S8** — toolkit built via paypal_agent_toolkit.shared.api.PayPalAPI; tools exposed (read-only config): []

> **S8** — PASS get order 6VX14008JC947302G via toolkit: {"message": "The PayPal order 6VX14008JC947302G has been successfully captured.", "status": "COMPLETED", "amount": "USD 32.00", "raw": {"id": "6VX14008JC947302G", "intent": "CAPTURE", "status": "COMPLETED", "payment_source": {"paypal": {"email_address": "sb-7e4qb53889901@personal.example.com", "acco
