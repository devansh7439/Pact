# 03 · Pact Recovery Protocol (PRP) v0.1

**Status: DESIGN.** A small, signed HTTP+JSON protocol for what happens *after*
an agent-initiated payment is declined. It does not cover discovery, cart or
checkout semantics; it starts at "the payment failed" and ends at a terminal
outcome.

JSON Schemas: [`schemas/recovery_offer.schema.json`](../schemas/recovery_offer.schema.json),
[`schemas/recovery_response.schema.json`](../schemas/recovery_response.schema.json),
[`schemas/mandate.schema.json`](../schemas/mandate.schema.json).

## 1. Design goals

1. **Machine-decidable.** Every field the buyer agent acts on is structured and
   enumerated. No decision depends on reading prose.
2. **Untrusted prose is quarantined.** Human-readable text is carried in one
   clearly marked field and is never an instruction.
3. **The merchant cannot change the deal during recovery.** The amount and
   currency are fixed to the original intent.
4. **Safe to retry at the HTTP layer.** Every state-changing call is idempotent.
5. **Either side can say no.** Merchant policy shapes the options; the buyer's
   mandate picks among them or escalates.

## 2. Endpoints (served by the merchant)

| Method & path | Purpose | Success | Notable errors |
|---|---|---|---|
| `POST /agent/v1/register` | Start onboarding: agent sends its public key; merchant returns its public key and a merchant-hosted approval URL | `201` | `409` agent already registered |
| `POST /agent/v1/checkout` | Purchase under a registered mandate | `200` receipt, or **`402`** with a recovery offer | `403` outside registered caps, `409` duplicate idempotency key |
| `GET  /agent/v1/offers/{offer_id}` | Fetch an offer | `200` | `404`, `410` expired |
| `POST /agent/v1/offers/{offer_id}/accept` | Accept one option | `200` receipt, `202` pending payer action (returns `approve_url`), or `402` new offer if declined again | `409` already accepted, `410` expired, `422` invalid option/alias |
| `POST /agent/v1/offers/{offer_id}/decline` | Decline all options | `200` | `410` |
| `GET  /agent/v1/intents/{intent_id}` | Current state and outcome | `200` | `404` |

Optional push: if the agent registered a `callback_url`, the merchant POSTs
`intent.updated` events there (signed the same way). Agents must also work by
polling; callbacks are a convenience.

## 3. Message signing (Ed25519)

Each party has its **own** Ed25519 keypair. Private keys never leave their owner;
public keys are exchanged once, at registration. Because no secret is shared, the
merchant cannot fabricate an "agent accepted" message and the agent cannot
fabricate an offer — each side's record of what the other said is provable.

Every request and response body is signed:

```
PRP-Key-Id:    agt_7f3c...#k1      # signer id + key version
PRP-Timestamp: 1763030400          # unix seconds
PRP-Nonce:     0b9e0c2a-...        # UUIDv4, single use
PRP-Signature: v1=base64url(Ed25519_sign(private_key,
                   "PRP/0.1\n" + method + "\n" + path + "\n" + timestamp + "\n" + nonce + "\n" + canonical_json(body)))
```

- Method and path are inside the signed string, so a signature for
  `POST /offers/X/decline` can't be replayed against `/offers/X/accept`.
- `canonical_json`: UTF-8, keys sorted, no insignificant whitespace, integers
  only for money (no floats anywhere in PRP).
- Receivers reject: unknown key id, timestamp skew > 300 s, a nonce seen in the
  last 10 minutes, or a bad signature — **before** parsing the body into models.
- Key rotation: registration accepts a new public key signed by the old one;
  key ids are versioned (`#k1`, `#k2`).
- Implementation: `cryptography.hazmat.primitives.asymmetric.ed25519`, ~60 lines
  in `shared/prp/signing.py`.

### What the signature binds

The offer body — and therefore its signature — fixes the intent, merchant,
amount, currency, expiry, failure class and the failed funding source together.
Changing any one of them invalidates the signature. The acceptance body binds the
offer id, the chosen option, the funding alias and the mandate id. Both sides
store the signed bytes exactly as received (`offers.body_json`,
`offers_received.body_json`), so either can later prove what the other sent.

## 4. The recovery offer

Returned in the body of a `402` from `/checkout` or `/accept`, and retrievable via
`GET /agent/v1/offers/{offer_id}`.

```json
{
  "prp_version": "0.1",
  "offer_id": "off_01JD4K...",
  "intent_id": "pi_01JD4J...",
  "merchant": { "id": "mer_kettle_crumb", "name": "Kettle & Crumb" },
  "created_at": "2026-11-20T10:15:02Z",
  "expires_at": "2026-11-20T10:30:02Z",
  "amount": { "currency_code": "USD", "value_minor": 3200 },
  "failure": {
    "class": "INSUFFICIENT_FUNDS",
    "retry_same_instrument": false,
    "failed_funding_alias": "primary-card",
    "paypal": {
      "processor_response_code": "5120",
      "processor_response_name": "INSUFFICIENT_FUNDS"
    }
  },
  "options": [
    {
      "option_id": "opt_alt",
      "kind": "ALTERNATE_FUNDING",
      "eligible_funding_aliases": ["paypal-wallet"]
    },
    {
      "option_id": "opt_payer",
      "kind": "PAYER_ACTION"
    },
    {
      "option_id": "opt_cancel",
      "kind": "CANCEL"
    }
  ],
  "decision_ref": "dec_01JD4K...",
  "display": {
    "untrusted": true,
    "locale": "en-US",
    "text": "Your card was declined for insufficient funds. You can pay with your saved PayPal balance instead."
  }
}
```

### Option kinds

| Kind | Meaning | What happens on accept |
|---|---|---|
| `ALTERNATE_FUNDING` | Pay with a different saved funding source | Merchant creates a new PayPal order with that source's `vault_id`; immediate result |
| `RETRY_AFTER` | Same or other source, not before `not_before` | Accept is held until `not_before`, then attempted |
| `PAYER_ACTION` | The human must approve on PayPal | Merchant creates an order needing payer approval; returns `approve_url` (`202`) |
| `CANCEL` | Abandon the purchase | Intent closes as `LOST` with reason `buyer_cancelled` |

### Offer rules (enforced by both sides)

| Rule | Merchant enforces when building | Buyer guard enforces when evaluating |
|---|---|---|
| R1 · `amount` equals the original intent amount and currency | ✓ | ✓ (compares to its own purchase record) |
| R2 · If `retry_same_instrument` is false, `failed_funding_alias` never appears in any option | ✓ | ✓ |
| R3 · `RISK_BLOCKED` failures offer only `PAYER_ACTION` and `CANCEL` | ✓ | ✓ (escalates regardless) |
| R4 · `expires_at` − `created_at` ≤ 30 minutes | ✓ | ✓ |
| R5 · At most one accepted option per offer | ✓ (`409` after the first) | ✓ |
| R6 · `display.text` is never used as input to a decision | n/a | ✓ (quarantined; see doc 06) |
| R7 · Unknown fields or option kinds → treat the offer as invalid and escalate | n/a | ✓ |

## 5. Accepting an offer

```json
{
  "prp_version": "0.1",
  "offer_id": "off_01JD4K...",
  "option_id": "opt_alt",
  "funding_alias": "paypal-wallet",
  "mandate_id": "mdt_01JD3...",
  "agent_decision_ref": "gd_01JD4K...",
  "idempotency_key": "acc_off_01JD4K_opt_alt"
}
```

The merchant derives the PayPal `PayPal-Request-Id` from `(offer_id, option_id)`.
Re-sending the same accept is safe and returns the same result.

### Merchant checks on every accept, in order

1. Signature, key id, timestamp, nonce (§3).
2. Offer exists, not expired, not already accepted; option belongs to this offer.
3. `funding_alias` is in the option's `eligible_funding_aliases` and is not the
   failed alias.
4. **Consent check** (`HARD_CONSENT_INVALID`, doc 05): the alias maps to a saved
   PayPal method that is active and owned by this customer; the registered
   mandate is unexpired and its caps still allow the amount; the agent
   registration is active.
5. Kill switch off.

Only then is a PayPal order created. Checks 4–5 run again immediately before the
PayPal call, so a revocation between accept and execution still stops it.

## 6. Outcomes

`intent.outcome` ∈ `RECOVERED` · `RECOVERED_BY_HUMAN` · `ORGANIC` · `LOST` ·
`PENDING`. `RECOVERED` means paid through an option the agent accepted
autonomously; `RECOVERED_BY_HUMAN` means paid after a `PAYER_ACTION` escalation.

## 7. Error body

```json
{ "prp_version": "0.1", "error": { "code": "OFFER_EXPIRED", "message": "..." } }
```

Codes: `BAD_SIGNATURE`, `UNKNOWN_KEY`, `REPLAYED_NONCE`, `CLOCK_SKEW`,
`OUTSIDE_MANDATE`, `CONSENT_INVALID`, `OFFER_EXPIRED`, `OFFER_ALREADY_ACCEPTED`,
`INVALID_OPTION`, `ALIAS_NOT_ALLOWED`, `KILL_SWITCH_ACTIVE`, `PAYPAL_ERROR`.

## 8. Relationship to other agentic-commerce protocols

PRP covers a gap — post-decline recovery — rather than checkout itself. In
principle it could ride as an extension next to an agentic checkout protocol.
We make **no compatibility claim** with any named protocol in the submission.
