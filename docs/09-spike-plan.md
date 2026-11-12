# 09 · Feasibility spike — do this first

**Goal:** prove, on *our* sandbox app, the PayPal behaviours the agent version
depends on. **Timebox: 3½ hours.** Scripts live in `scripts/spike/`, plain Python +
httpx, no framework.

## Steps

| # | Prove | How | Pass when |
|---|---|---|---|
| S1 | Auth + basic order | `01_auth_order.py`: OAuth token → create order (no payment source) → print approve link → approve as Maya in the browser → capture | Capture `COMPLETED`; `processor_response` present for card |
| S2 | Save a PayPal wallet | `02_vault_paypal.py`: setup token (PayPal) → approve as Maya → payment token → print `vault_id` | `vault_id` returned; listed by `GET /v3/vault/payment-tokens?customer_id=` |
| S3 | Save cards with decline triggers | `03_vault_cards.py`: setup tokens for test card `4012 8888 8888 1881` with names `CCREJECT-IF`, `CCREJECT-SF`, `CCREJECT-REFUSED`, plus one clean card | `vault_id` per card |
| S4 | Charge a saved source with no redirect | `04_charge_vaulted.py`: order with `payment_source.paypal.vault_id` (wallet) and with `card.vault_id` (clean card) | Both `COMPLETED` with no payer interaction |
| S4b | Consent & stored-credential encoding | Repeat S4's card charge with encoding A (`CUSTOMER`/`ONE_TIME`/`SUBSEQUENT`) and B (`MERCHANT`/`UNSCHEDULED`/`SUBSEQUENT`) — doc 04 §3.4; for the wallet, create the token with an unscheduled `usage_pattern` and repeat. Screenshot the consent text PayPal shows Maya at approval | Record which encodings PayPal accepts for each source; choose one and write the reason in `RESULTS.md` |
| S5 | Decline on a saved card | Same script against the `CCREJECT-IF` card | Capture `DECLINED` with `response_code` `5120` |
| S5b | Fallback decline | If S5 fails: add `PayPal-Mock-Response` with `INSTRUMENT_DECLINED` on capture (negative testing enabled) | 422 `INSTRUMENT_DECLINED` |
| S6 | Recovery with alternate source | After S5, new order for the same amount with the wallet `vault_id`, request id derived from a fake offer id | `COMPLETED`; repeating the call with the same request id returns the same order |
| S7 | Webhooks | Public tunnel → register webhook → run S4 again → call verify-webhook-signature | `SUCCESS` for `PAYMENT.CAPTURE.COMPLETED` (and `DECLINED` if emitted) |
| S8 | Agent Toolkit | `pip install paypal-agent-toolkit`; call a read-only tool (get order) from Python | Returns the S4 order |

Record every request/response (secrets redacted) in `scripts/spike/RESULTS.md` —
it doubles as the first `verify_live` receipt and as evidence in the write-up.

## Go / no-go

| Result | Decision |
|---|---|
| S1, S2, S4, S4b, S6 pass **and** (S5 or S5b) passes | **GO — agent version** |
| S4b: only encoding B accepted | GO with B; the write-up explains that the merchant charges under consent the customer gave at onboarding, at the request of the customer's agent |
| S4b: neither encoding accepted for saved cards, wallet works | GO with the PayPal wallet as every agent funding source; decline scenarios use negative testing (S5b) |
| S4 fails for PayPal wallet but passes for cards | GO with cards as both primary and alternate sources; wallet only in human escalation |
| S4 fails for all saved sources | **Switch to the fallback** (`fallback/PACT-MERCHANT-FALLBACK.md`) — the agent can't pay without a human |
| S5 and S5b both fail | GO, but declines in the demo come from fixture events labelled FIXTURE; recovery attempts stay real |
| S5b fails (even if S5 passes) | GO; scenario S3 uses its budget-based variant (doc 01, §8 footnote) |
| S7 fails | GO; rely on the reconciler poll; note it in the README |
| S8 fails | GO; Ask Pact uses our own read tools; drop the toolkit claim |

Nothing built in Phase 1 is wasted either way — the merchant core is shared by
both versions (doc 10).
