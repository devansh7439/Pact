# Devpost Submission — Pact

**PayPal AI Hackathon 2026**

---

## General Info

- **Project Name:** Pact: Payment Recovery for AI Agents on PayPal
- **Tagline / Elevator Pitch:** When an agent's payment fails, nobody's watching. Pact diagnoses declines, evaluates net expected value, and executes signed recovery offers on PayPal within human mandates.
- **Repository:** https://github.com/devansh7439/Pact

---

## Built With

`paypal-orders-v2`, `paypal-vault-v3`, `paypal-agent-toolkit`, `python`, `fastapi`, `ed25519`, `scikit-learn`, `ag-grid`, `next.js`, `react`, `typescript`, `tailwind-css`, `pydantic`, `sqlite`, `thompson-sampling`, `bayesian-bandits`, `ai-agents`

---

## Project Story

### Inspiration

AI agents are starting to buy goods, book travel, and settle invoices on our behalf. When a human's card declines, they see the error, pick a different card, or top up their balance. When an **AI agent's** payment declines, **nobody is sitting at the checkout screen**. 

Every existing recovery tool (dunning emails, SMS, push notifications, "update your billing info" banners) assumes a human is reading the message. Agents either retry blindly into the processor—burning fees and triggering risk blocks—or fail silently, abandoning the order.

We built **Pact** to fix this. Pact is the payment recovery infrastructure for agentic commerce on PayPal: a merchant-side decision engine that scores recovery options using expected net value, and a buyer-side guard that cryptographically verifies recovery offers against human spending mandates before moving a single cent.

### What it does

Pact introduces an open, two-sided protocol—the **Pact Recovery Protocol (PRP v0.1)**—with two independent, non-custodial guardrails:

1. **Merchant Recovery Engine (`pact-merchant`):**
   - **Diagnoses Decline Signals:** Interprets 34 PayPal processor codes (`00N7`, `5100`–`5210`, `9500` Suspected Fraud) and 20 Orders v2 API issues (`INSTRUMENT_DECLINED`, `PAYER_ACTION_REQUIRED`).
   - **Computes Net Expected Value (NEV):** Evaluates every recovery action $a$ against doing nothing (the baseline $a_0$):
     $$\text{NEV}(a) = (\hat{P}(a) - \hat{P}(a_0)) \times (\text{Amount} \times \text{Margin}) - \text{Fee}(a) - \text{Cost}(a)$$
     If no action clears the merchant's profit floor (e.g., chasing a $4 add-on), Pact **drops the recovery** rather than wasting processor fees.
   - **Issues Signed PRP Offers:** Returns an `HTTP 402 Payment Required` response containing machine-readable options signed with the merchant's Ed25519 private key.
   - **10% Live Causal Holdout:** Reserves a deterministic 10% holdout group (salted SHA-256 hash) to measure true causal recovery lift against organic retries.

2. **Buyer Agent Guard (`pact-buyer`):**
   - **12 Hard Invariants (G1–G12):** Evaluates recovery offers against Maya's pre-approved mandate (weekly ceiling, per-order cap, authorized funding priority, category whitelist, merchant domain).
   - **Autonomous Alternate Funding:** If Maya's primary card fails for insufficient funds (`5120`), her agent autonomously switches to her pre-vaulted PayPal wallet without human intervention.
   - **Zero Autonomy on Risk:** On suspected fraud (`9500`) or exceeded retry limits, autonomous actions are strictly barred, delivering an instant one-tap approval link to Maya's inbox.
   - **Adversarial Prompt Shield:** Recovery offers are strictly parsed as data schemas; prompt injection attacks embedded in checkout text are quarantined and dropped.

### How we built it

- **PayPal Orders v2 & Vault v3:**
  - Real-time order capture (`POST /v2/checkout/orders/{id}/capture`) with idempotency headers (`PayPal-Request-Id`).
  - Saved PayPal wallet and card payment tokens via Vault v3 setup tokens (`POST /v3/vault/setup-tokens` exchanged for permanent `vault_id`s).
  - Stored-credential indicators: Charges declare `payment_initiator: CUSTOMER`, `payment_type: ONE_TIME`, and `usage: SUBSEQUENT` to accurately reflect the agent acting as the customer's authorized delegate.
- **PayPal Webhooks with Signature Verification:**
  - Consumes and verifies 7 webhook events (`PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DECLINED`, `VAULT.PAYMENT-TOKEN.CREATED`, etc.) using PayPal's cryptographic verification API (`POST /v1/notifications/verify-webhook-signature`).
- **Cryptographic Protocol (PRP v0.1):**
  - High-speed Ed25519 asymmetric signatures over canonical JSON, binding HTTP method, URL path, timestamp (±300s skew check), and anti-replay nonces.
- **Machine Learning & Decision Economics:**
  - Calibrated scikit-learn Logistic Regression / Gradient Boosting propensity model trained on decline features.
  - Bayesian Multi-Armed Bandit (Beta-Bernoulli conjugate priors via Thompson Sampling) to continuously learn recovery efficacy per failure class while bounding exploration risk.
- **Frontend & Visualization:**
  - Next.js 14, React, TypeScript, and Tailwind CSS.
  - Interactive AG Grid decision ledger with pinned NEV columns and master-detail drawer.
  - Two-pane linked view visualizing the merchant diagnosis and buyer guard checklist side-by-side on a unified chronological timeline.

### AI tools used and how

In Pact, **models advise, but deterministic policies and human mandates decide**:
- **Calibrated Propensity Model (scikit-learn):** Predicts recovery probability per action $\hat{P}(a)$ and baseline probability $\hat{P}(a_0)$ to calculate expected revenue lift. Displayed transparently in the per-option inspector.
- **Bayesian Multi-Armed Bandit:** Dynamically adjusts action selection priors using Thompson Sampling across failure classes without risking capital beyond the configured floor.
- **Natural Language Parsing & Customer Explanations (LLM):** Parses unstructured shopper requests into structured JSON mandates and drafts empathetic, dark-pattern-free customer recovery emails.
- **PayPal Agent Toolkit:** Read-only integration powering **Ask Pact**, allowing merchants to audit historical declines, explain algorithmic decisions, and query PayPal order states without moving money.
- **Strict Boundary Guardrail:** No LLM or generative model has access to tools that execute captures, modify amounts, or alter authorizations.

### Challenges we ran into

1. **Autonomous Agency vs. Payment Consent:** An agent's internal mandate does not constitute legal payment authorization to charge a payment method. We solved this by enforcing a two-tier consent model: PayPal Vault authorization is established directly by the human at onboarding; the agent's mandate only controls *when the agent is permitted to request that authorization*.
2. **Measuring True Causal Lift:** Blind retries often recover payments organically (e.g. temporary issuer hiccups), leading traditional recovery systems to claim false credit. We implemented a strict 10% live causal holdout group with Wilson 95% confidence intervals to measure real incremental revenue.
3. **Adversarial Text Injections in Payment Metadata:** Payment memo fields and error payloads can carry prompt injections. We treated all incoming offer fields as untrusted data, routing them through strict Pydantic schemas and regex scanners before processing.

### Accomplishments that we're proud of

- **220 Automated Tests Passing:** Complete test coverage spanning unit, integration, invariant, and property-based tests running in CI on Python 3.12 and Node 20.
- **Zero-Credential Offline Reliability:** The entire suite, including merchant decisions, buyer guardrails, and simulated PayPal processor declines, runs offline without requiring sandbox credentials.
- **Real Two-Sided Cryptographic Independence:** Neither party can forge actions on behalf of the other. The merchant cannot fabricate an "agent accepted" response without the buyer's private key.
- **End-to-End Sandbox Verification:** Verified real sandbox recoveries using PayPal test cards and processor decline codes (`5110`, `5120`, `9500`).

### Built during the hackathon & pre-existing work disclosure

In full compliance with the hackathon rules regarding pre-existing work:
- **Everything else was created entirely during the hackathon:**
  - Complete PayPal integration (Orders v2, Vault v3, stored credentials, Webhook signature verification, PayPal Agent Toolkit).
  - The PRP v0.1 protocol with Ed25519 request/response signing.
  - The entire buyer agent service (`buyer_agent/`), mandate store, and 12-invariant guard (`guard.py`).
  - The Bayesian Multi-Armed Bandit learning loop (`merchant/engine/bandit.py`).
  - The Ask Pact read-only recovery assistant (`merchant/assistant/`).
  - The Next.js web application, linked visualizer, and AG Grid decision console.

### Sponsor Prizes: AG Grid

We utilized **AG Grid** in the Merchant Console (`/merchant`) where high-density financial data requires industrial-grade performance:
- **Decision Ledger:** Rendered complex recovery attempts with sortable columns, real-time filtering by failure class and provenance (`sandbox`, `fixture`, `simulated`), and pinned Net Expected Value (NEV) financial calculations.
- **Master-Detail Flow:** Enabled one-click row selection to slide out the decision inspector, exposing the full underlying arithmetic, rule trace, and signed Ed25519 payload.

### What's next for Pact

- **Standardizing PRP:** Publishing PRP (Pact Recovery Protocol) as an open RFC for agent-to-agent and merchant-to-agent payment negotiations.
- **Subscription Renewals:** Expanding autonomous recovery to recurring PayPal billing failures (`BILLING.SUBSCRIPTION.PAYMENT.FAILED`).
- **Hardware Enclave Signing:** Storing buyer and merchant Ed25519 private keys in secure hardware enclaves (AWS Nitro / Apple Secure Enclave) for institutional agent deployments.
