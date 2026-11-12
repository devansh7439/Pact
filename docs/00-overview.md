# 00 · Overview

> **Pact — payment recovery for AI agents, on PayPal.**
> When an agent's payment fails, nobody's watching. Pact is.

Positioning rule: lead with the **product** (recovery for agent buyers, working on
PayPal today); present the protocol as *how* it works, never as a standard we
claim to have set.

## 1. The problem

Payment recovery today is built around a human who is present, or who can be
brought back:

| Today's recovery move | Assumes |
|---|---|
| "Card declined — try another card" on the checkout page | Someone is looking at the page |
| Dunning email / SMS / WhatsApp nudge | Someone reads it and clicks |
| "Update your payment method" banner | Someone logs in |
| Automatic retry of the same instrument | The failure was transient |

Agent-initiated commerce breaks every row. PayPal is actively building for
purchases that originate from AI agents (Agent Ready, agentic commerce services,
the Agent Toolkit and MCP server). When an agent's payment is declined:

- there is no human on the page to pick another card;
- a nudge to the human arrives hours later, after the agent has given up or
  silently bought elsewhere;
- blind retries of a hard decline (fraud, lost card) are exactly what issuers
  penalise;
- the agent cannot safely "just try something else" — it has a budget, a scope
  and a human who never authorised improvisation.

The merchant loses the sale; the human never learns why their errand failed.

## 2. What Pact does

Two cooperating halves, one per side of the transaction:

**Merchant side — the Pact engine.** Diagnoses each decline from PayPal's
processor response, scores the chance of recovery, prices every possible
intervention, and acts only where the economics clear the merchant's floor. For
an agent buyer it issues a **signed recovery offer**; for a human buyer it sends
a fresh PayPal checkout with a clearly written message. It refuses when
recovering would cost more than it's worth, or when retrying would be unsafe.

**Buyer side — the buyer agent.** Holds a **mandate** the human approved once:
budget, per-purchase cap, allowed merchants, which saved PayPal funding sources
it may use and in what order. It evaluates each recovery offer against the
mandate with a deterministic guard; if an option fits, it recovers the payment
through PayPal on its own; if not, it escalates to the human with one tap.

**Shared principle:** models predict, policies decide, LLMs explain. No LLM
output can move money.

## 3. Who it's for

| Audience | Pain | What they get |
|---|---|---|
| Small and mid-sized PayPal merchants starting to receive agent traffic | Agent-initiated declines are invisible lost sales | Recovered revenue, measured honestly, with an audit trail |
| People delegating purchases to agents | Errands fail silently | Their agent fixes it within their rules, or asks them |
| Agent builders | No standard way to handle a declined payment | A small, signed, documented recovery protocol (PRP v0.1) |

Human-checkout recovery uses the same engine, so the product is useful on day
one and grows with agent traffic.

## 4. Positioning — what this is *not*

- **Not a retry scheduler.** PayPal already retries failed subscription
  payments. Pact decides *whether* a recovery is worth pursuing and *how*,
  and it can decide "no".
- **Not a chatbot wrapped around the Orders API.** The interesting part is the
  decision and the two independent guardrails, not the conversation.
- **Not a dashboard that claims every recovered dollar.** A live holdout
  measures what Pact actually *caused*.

## 5. Differentiators (in pitch order)

1. **Recovery for agent buyers** — the first-class case, not an afterthought.
2. **Two guardrails, two owners** — the merchant's policy and the human's mandate;
   either can say no, neither can be overridden by a model, and each side signs
   with its own Ed25519 key so neither can speak for the other.
3. **Signed offers, untrusted text** — a recovery offer is treated as a
   prompt-injection vector into someone's wallet, and defended as one.
4. **Economically rational refusal** — the agent visibly declines to act when the
   expected value is negative or the risk is too high.
5. **Incremental truth** — a live holdout reports caused revenue, not gross.

## 6. Judging-criteria map

All five criteria are equally weighted.

| Criterion | How we score | Evidence to show |
|---|---|---|
| Technological implementation | Orders v2, Vault v3 payment tokens, webhooks + signature verification, PayPal Agent Toolkit, calibrated model with per-option probabilities, two-party Ed25519-signed protocol, property tests | Architecture diagram, test count, live sandbox transactions in the video, the per-option table |
| Design | One coherent product: merchant console + buyer's agent view, linked so the same transaction is visible from both sides; judge mode | Linked two-pane view; one-click scenarios |
| Potential impact | Real problem today (human declines) that compounds with agent commerce | Clear audience; incremental-lift panel; honest labelling of simulated vs real |
| Innovation | Agent-to-agent recovery protocol with mandate-bound autonomy | The protocol doc; the injection-defence demo |
| Presentation | 3-minute video built around four contrasting scenarios | [Demo script](11-demo-and-submission.md) |

## 7. Prize targets

- Grand prizes (1st/2nd/3rd).
- Special awards that fit: Best Use of Agentic Commerce, Best Use of PayPal + AI,
  Most Creative, Best Demo Delivery.
- **One** sponsor prize (the rules allow one Grand *or* Honorable Mention plus at
  most one Sponsor prize): **AG Grid**, used for the decision ledger and audit
  trail.
