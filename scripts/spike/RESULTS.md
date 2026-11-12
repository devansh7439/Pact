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
