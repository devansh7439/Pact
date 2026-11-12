# Pact — payment recovery for AI agents, on PayPal

> **When an agent's payment fails, nobody's watching. Pact is.**

PayPal AI Hackathon 2026 · v0.3 (building) — see [changelog](#blueprint-changelog)

This repository holds the design blueprint and the build, which lands phase by
phase as described in [`docs/10-build-plan.md`](docs/10-build-plan.md).

## Running it

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt          # macOS/Linux
python -m pytest                       # offline: no PayPal or LLM credentials needed
python -m merchant.ml.train            # trains the propensity model (SIMULATED data)
python -m merchant.engine.evaluate     # do-nothing vs blind retry vs Pact, paired
```

---

## The one-paragraph pitch

AI agents are starting to buy things on people's behalf. When a human's card is
declined, they see the error and try another card. When an *agent's* payment is
declined, there is no human on the checkout page — and every recovery tool in
existence (emails, SMS, "update your card" banners) assumes there is. Pact is
the recovery layer for agent-initiated payments on PayPal: the merchant side
diagnoses the decline, decides whether recovery is worth pursuing, and issues a
**signed, machine-readable recovery offer**; the buyer's agent evaluates it
against a **spending mandate** its human set in advance, and either recovers the
payment autonomously through PayPal or escalates to the human. Two independent
guardrails — one per side, each signing with its own key — and an LLM that
explains everything but decides nothing. The same engine recovers ordinary human
checkouts too.

## Document map

| # | Document | Read it for |
|---|---|---|
| 00 | [Overview](docs/00-overview.md) | Problem, audience, positioning, judging-criteria map |
| 01 | [System design](docs/01-system-design.md) | Actors, end-to-end flows, sequence diagrams, demo scenarios |
| 02 | [Architecture](docs/02-architecture.md) | Services, modules, tech stack, repo layout |
| 03 | [Recovery protocol](docs/03-recovery-protocol.md) | The agent-to-agent recovery offer spec (PRP v0.1) |
| 04 | [PayPal integration](docs/04-paypal-integration.md) | Every PayPal API, webhook and sandbox trick we rely on |
| 05 | [Decision engine](docs/05-decision-engine.md) | PayPal decline taxonomy, expected value, guardrails, live holdout |
| 06 | [Buyer agent](docs/06-buyer-agent.md) | Mandates, the mandate guard, LLM role, prompt-injection defence |
| 07 | [Data model & API](docs/07-data-model-and-api.md) | Tables and HTTP endpoints for both services |
| 08 | [Safety & invariants](docs/08-safety-and-invariants.md) | Threat model and the properties tests must prove |
| 09 | [Feasibility spike](docs/09-spike-plan.md) | **Do this first.** Go / no-go for the agent version |
| 10 | [Build plan](docs/10-build-plan.md) | Phases, tasks, definition of done |
| 11 | [Demo & submission](docs/11-demo-and-submission.md) | Video script, Devpost write-up, compliance checklist |
| — | [Fallback: Pact Merchant](fallback/PACT-MERCHANT-FALLBACK.md) | The smaller merchant-only product if the spike fails |
| — | [`schemas/`](schemas/) | JSON Schemas for offers, responses and mandates |

## Status legend used across the docs

- **VERIFIED** — confirmed against PayPal's developer docs while writing this blueprint.
- **VERIFY IN SPIKE** — documented by PayPal but not yet proven on *our* sandbox app.
- **DESIGN** — our own decision; change it freely.

## Blueprint changelog

**v0.3** — started building:

- **Pact Recovery Protocol (PRP v0.1):** `PRP-*` headers, `prp_version`, `shared/prp/`.
- **Merchant engine on PayPal:** PayPal taxonomy, economics in
  USD cents with PayPal's fee, the three-stage policy with agent/human channels,
  consent and same-instrument rules, offer option sets and the per-option table,
  live holdout, simulator, model, evaluation. Status and fixes in doc 02 §4.
- **Per-option table** in doc 05 now shows numbers the code actually computes.

**v0.2** — changes after an external design review:

- **Ed25519 signatures in PRP v0.1** (was HMAC). Each party signs with its own key,
  so the merchant can no longer produce an "agent accepted" message the agent
  never sent — the two-guardrail claim now holds cryptographically.
- **Consent and stored-credential checks** added to the spike (step S4b) and to
  the PayPal doc: a mandate given to an agent is not, by itself, PayPal
  authorisation to charge a saved method.
- **Pre-attempt consent check** (`HARD_CONSENT_INVALID`) before every new PayPal
  attempt: saved method active and owned by this customer, mandate unexpired,
  agent registration active.
- **Per-option model table** in the decision inspector: recovery chance with and
  without each action, lift, and expected value — labelled SIMULATED.
- **Linked two-sided view**: one transaction, merchant and buyer panes side by side.
- **Visible guard checklist** on the buyer side, so the mandate shows even when a
  recovery succeeds.
- **Scenario cut**: S1–S4 core, S5 as a short flash, S6 optional.
- **Positioning**: product first, protocol as the how.
- **Deadline mode** in the build plan: a cut that fits roughly one day of work.

**v0.1** — initial blueprint.

## License

MIT — see [LICENSE](LICENSE).
