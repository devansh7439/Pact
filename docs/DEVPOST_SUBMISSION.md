# Devpost Submission — Pact

**PayPal AI Hackathon 2026**

---

## General Info

- **Project Name:** Pact: Payment Recovery for AI Agents on PayPal
- **Tagline / Elevator Pitch:** When an agent's payment fails, nobody's watching. Pact diagnoses declines, evaluates net expected value, and executes signed recovery offers on PayPal within human mandates.
- **Repository:** https://github.com/devansh7439/Pact

---

## Built With

`paypal-orders-v2`, `paypal-vault-v3`, `python`, `fastapi`, `ed25519`, `scikit-learn`, `ag-grid`, `next.js`, `react`, `typescript`, `tailwind-css`, `pydantic`, `sqlite`, `thompson-sampling`, `bayesian-bandits`, `ai-agents`

---

## Project Story

### Inspiration

Maya tells her shopping agent: *"Reorder my coffee beans. Keep it under $60 a week."* At 2 a.m. the agent checks out, and her card declines for insufficient funds.

If Maya were at the checkout, she'd switch to her PayPal balance and move on. Her agent can't do that. Every recovery tool merchants have (dunning emails, SMS, "update your billing info" banners) assumes a person reads the message. So agents do one of two things: retry the same card until the processor flags them, or give up and let the order quietly die.

We built **Pact** for that moment. It's payment recovery for AI agents on PayPal, split into two halves that don't trust each other. The merchant decides which recoveries are worth offering. The buyer's agent checks every offer against the limits Maya set before a cent moves.

### What it does

The two sides talk over the **Pact Recovery Protocol (PRP v0.1)**, a small signed protocol we wrote. Neither side holds the other's money or keys.

**One decline, end to end**

1. Maya's agent captures a $42 order. PayPal returns processor code `5120` (insufficient funds).
2. The merchant engine classifies the decline, scores each recovery option by net expected value, and replies `HTTP 402 Payment Required` with a signed offer: *retry with a different funding source*.
3. Maya's agent verifies the signature and runs the offer through 12 checks against her mandate. The amount hasn't changed, the merchant is on her list, she has budget left, and her mandate allows switching to her vaulted PayPal wallet.
4. The agent captures with the wallet. The order goes through. Maya gets a receipt, not a problem to solve.

In the demo video this flow runs in fixture mode, and the status panel says so ("PayPal: fixture"). See *What ran against the real sandbox* below.

If the code had been `9500` (suspected fraud), step 3 would stop. Risk declines are never recovered automatically; Maya gets a one-tap approval link instead.

**Merchant side (`pact-merchant`)**

- **Reads the decline.** Maps 34 PayPal processor codes (`00N7`, `5100`–`5210`, `9500`, …) and 20 Orders v2 issues (`INSTRUMENT_DECLINED`, `PAYER_ACTION_REQUIRED`, …) to failure classes.
- **Prices every option.** Each recovery action \\( a \\) is compared against doing nothing (\\( a_0 \\)):

$$\text{NEV}(a) = \big(\hat{P}(a) - \hat{P}(a_0)\big) \times \text{Amount} \times \text{Margin} - \text{Fee}(a) - \text{Cost}(a)$$

  If no option clears the merchant's profit floor (chasing a $4 add-on, say), Pact doesn't try. A recovery that costs more than it earns isn't a recovery.
- **Signs the offer.** Options go out as machine-readable JSON signed with the merchant's Ed25519 key.
- **Measures itself honestly.** A deterministic 10% of declines (salted SHA-256) get no intervention, so the dashboard reports lift over what would have recovered anyway.

**Buyer side (`pact-buyer`)**

- **12 checks before money moves (G1–G12):** valid signature; known offer format; not expired; merchant allowed; amount unchanged from the original order; within the per-order cap and weekly budget; failure class allowed for autonomous recovery; retry attempts left; and a funding source from Maya's approved list that hasn't already failed. Anything else goes to Maya.
- **Never auto-recovers risk declines.** Suspected fraud always goes to the human.
- **Treats offers as data, not instructions.** Every field is parsed through strict schemas, and text that tries to instruct the agent is quarantined and dropped.

### How we built it

- **PayPal Orders v2 and Vault v3.** Captures go through `POST /v2/checkout/orders/{id}/capture` with `PayPal-Request-Id`, so a retry can never double-charge. The onboarding code exchanges Vault v3 setup tokens for permanent `vault_id`s, and the executor builds agent charges with stored-credential fields (`payment_initiator: CUSTOMER`, `payment_type: ONE_TIME`, `usage: SUBSEQUENT`) to mark the agent as the customer's authorized delegate. Order create and capture have run against the sandbox. The Vault and stored-credential paths haven't yet (see below).
- **Webhooks.** Seven events (`PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DECLINED`, `VAULT.PAYMENT-TOKEN.CREATED`, …) are checked with `POST /v1/notifications/verify-webhook-signature` before anything acts on them. When a webhook and a reconciler poll race on the same capture, exactly one outcome is recorded. This is tested offline. No sandbox webhook has been received yet.
- **PRP v0.1.** Ed25519 signatures over canonical JSON bind the HTTP method, path, timestamp (±300 s) and a single-use nonce, so a captured offer can't be replayed or redirected to another endpoint.
- **Models.** An isotonic-calibrated random forest (scikit-learn) estimates \\( \hat{P} \\). A Beta-Bernoulli bandit with Thompson sampling learns which actions work for each failure class, with exploration capped so learning never spends past the profit floor.
- **Stack.** Python 3.12, FastAPI, Pydantic and SQLite on the backend; Next.js 14, React, TypeScript, Tailwind and AG Grid on the frontend. One linked view puts the merchant's diagnosis and the buyer's checklist on a single timeline.

### AI tools used and how

Our rule: **models advise; deterministic policy and the human's mandate decide.**

- **Propensity model:** predicts \\( \hat{P}(a) \\) and \\( \hat{P}(a_0) \\). Every prediction is visible in the per-option inspector next to the arithmetic it feeds.
- **Bandit:** shifts action priors as real outcomes arrive, inside the same profit floor.
- **LLM:** turns Maya's plain-English request into a structured mandate and drafts recovery emails without dark patterns. With no API key, both fall back to templates.
- **Ask Pact:** a read-only assistant merchants can ask "why did we drop this recovery?" or "what state is this order in?" It answers from the decision ledger and audit trail. It includes an adapter for the PayPal Agent Toolkit's read-only order lookup, but the toolkit isn't installed in our builds yet, so order state currently comes from Pact's own stored PayPal responses.
- **The boundary:** no model can call anything that captures funds, changes an amount or touches an authorization.

### Challenges we ran into

1. **A mandate isn't payment consent.** "Spend up to $60 a week" tells the agent what it may do. It doesn't authorize PayPal to charge anything. We split consent in two: Maya authorizes the Vault token herself at onboarding, and the mandate only governs *when* the agent may use it.
2. **Recovery tools take credit for luck.** Plenty of declines clear on their own: a brief issuer outage, a payday. Without a control group you can't tell recovery from luck, so we added the 10% live holdout and report lift with Wilson 95% confidence intervals.
3. **Payment metadata is an attack surface.** Memo fields and error messages are text an attacker can write, and an LLM-driven agent will read them. Every offer field is untrusted: it goes through strict Pydantic schemas and injection scanners before anything acts on it.

### What ran against the real sandbox

- **Ran:** OAuth, then Orders v2 create → approval by a sandbox buyer → capture (`COMPLETED`), on 2026-11-12. The redacted request log is in [`scripts/spike/RESULTS.md`](../scripts/spike/RESULTS.md).
- **Blocked:** saving a payment method. `POST /v3/vault/setup-tokens` returned `403 NOT_AUTHORIZED` for all five test cards and for the PayPal wallet. The likely cause is that save-payment-methods isn't enabled on our sandbox app.
- **Not yet run against the sandbox:** everything that needs a saved method. That covers charging it without a redirect, the `5110`/`5120`/`9500` test-card declines, the stored-credential labels and webhooks. The code and offline tests for all of it are in the repo.
- **The demo video** runs in fixture mode: PayPal's responses are canned, and the status panel shows "PayPal: fixture". Every metric in the console is labelled `sandbox`, `fixture` or `simulated`.

### Accomplishments that we're proud of

- **220 tests, all passing:** unit, integration, invariant and property-based (Hypothesis), in CI on Python 3.12 and Node 20.
- **Runs with zero credentials.** Merchant decisions, the buyer guard and simulated PayPal declines all work offline, so anyone can run the full flow without sandbox keys.
- **Neither side can forge the other.** The merchant can't fake an "agent accepted" message without the buyer's private key, and the buyer can't fake an offer without the merchant's.
- **A real sandbox payment, end to end:** order created, approved by a sandbox buyer and captured, with the redacted log committed.

### Built during the hackathon

- The PayPal client (Orders v2, Vault v3, stored credentials, webhook verification, an Agent Toolkit adapter), sandbox-verified so far for order create and capture; PRP v0.1 with Ed25519 signing; the buyer agent service, mandate store and 12-check guard; the bandit learning loop; Ask Pact; and the Next.js app, linked visualizer and AG Grid console.

### AG Grid

The Merchant Console (`/merchant`) uses AG Grid for the **decision ledger**: every recovery attempt, sortable and filterable by failure class and by provenance (`sandbox`, `fixture`, `simulated`), with NEV columns pinned. Selecting a row opens a **master-detail** inspector showing the full arithmetic, the rule trace and the signed Ed25519 payload.

### What's next for Pact

- **Finish the sandbox spike:** enable saving payment methods on the sandbox app, then run steps S2–S8 (saved-method charges, test-card declines, stored-credential labels, webhooks, toolkit).
- **Publish PRP as an open RFC** for agent-to-merchant payment negotiation.
- **Subscription renewals:** extend recovery to recurring billing failures (`BILLING.SUBSCRIPTION.PAYMENT.FAILED`).
- **Hardware key storage:** keep signing keys in AWS Nitro Enclaves or Apple Secure Enclave for institutional deployments.
