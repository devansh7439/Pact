# 11 · Demo & submission

Judges may score from the text, images and video alone, without testing the
project, so the video and write-up carry as much weight as the code.

## 1. Video script (target 2:50)

| Time | Screen | Voice-over (draft) |
|---|---|---|
| 0:00–0:15 | Title over the buyer view, an agent's order failing | "AI agents are starting to buy things for us. When a person's card is declined, they try another one. When an agent's card is declined — nobody's watching." |
| 0:15–0:30 | Linked view: merchant pane · buyer pane · shared timeline | "Pact is payment recovery for AI agents, on PayPal. The merchant side decides whether recovery is worth it. The buyer side checks every option against the limits Maya set. Each side signs with its own key, and neither lets a model move money." |
| 0:30–1:10 | **S1** live in the linked view: decline 5120 → per-option table (merchant pane) → 402 offer → guard checklist all ✓ (buyer pane) → PayPal capture → verified → RECOVERED | "Insufficient funds on Maya's card. The model scores each way to recover — paying with her saved PayPal balance adds the most over doing nothing. Her agent runs its checklist: same amount, in budget, allowed source, not the failed card. Paid — through PayPal's sandbox. No human needed." |
| 1:10–1:30 | **S2**: 9500 suspected fraud → only payer action → Maya gets a one-tap link | "Suspected fraud. PayPal's guidance is: don't retry that card. Pact won't let anyone try — not even its own agent. Maya decides." |
| 1:30–1:55 | **S3**: card declines → agent switches to PayPal → that declines too (labelled: sandbox negative test) → second offer → guard ESCALATE | "The merchant is still willing to try. Maya's agent isn't — she allowed one automatic retry, and it's been used. So it stops and asks her. Two guardrails, two owners." |
| 1:55–2:15 | **S4**: $4 add-on, expired card → DROP with arithmetic | "And sometimes the right move is nothing. Chasing a four-dollar add-on costs more than it's worth, so Pact doesn't." |
| 2:15–2:25 | **S5** flash: injection offer rejected | "Recovery offers are text arriving at something that can spend money. They're signed, and the agent never takes instructions from them." |
| 2:25–2:45 | Holdout panel and AG Grid ledger (deadline mode: per-option table close-up instead) | "Pact only takes credit for what it caused — not what would have come back anyway. Every decision is recorded, with the options it turned down and why." |
| 2:45–2:50 | End card: repo, live demo URL | "Pact. When nobody's watching, someone should be." |

Recording notes: use the hosted demo, 1080p, cursor highlighting, captions, no
copyrighted music, no third-party logos beyond PayPal's own sandbox pages that
appear naturally.

## 2. Devpost write-up outline

1. **Inspiration** — agent purchases fail silently; recovery tools assume a human.
2. **What it does** — the two halves, the four scenarios, the holdout.
3. **How we built it** — architecture image; PayPal APIs used (Orders v2, Vault v3
   payment tokens, stored-credential indicators, webhooks with signature
   verification, Agent Toolkit); the model and its per-option table; PRP v0.1 with
   Ed25519 signatures.
   - **Consent, stated plainly:** Maya's PayPal approval at onboarding is what lets
     the merchant charge her saved method; her mandate only limits when her agent
     may ask. Every charge declares how it was initiated (the encoding chosen in
     the spike, with the reason).
4. **AI tools used and how** — (required section)
   - Calibrated propensity model (scikit-learn): recovery probability per action,
     shown as the per-option table (chance with and without, lift, expected value),
     labelled as trained on simulated data.
   - LLM via an OpenAI-compatible API (name the model used): mandate drafting,
     purchase-intent parsing, diagnosis fallback with a confidence floor,
     customer and console explanations.
   - PayPal Agent Toolkit: read-only tools inside Ask Pact.
   - What AI is **not** allowed to do, and why.
5. **Challenges** — the honest ones from the build log.
6. **Accomplishments** — invariants proven, real sandbox recoveries.
7. **What we learned**
8. **What's next** — publishing PRP as an open draft, subscription renewals, more
   funding types, key rotation tooling.
9. **Built during the hackathon** — a short list of what was built in the
   submission period, plus the one-line prior-work disclosure exactly as it
   appears in the README. The rules allow updated projects when the update is
   significant and explained; saying it plainly removes any doubt.
10. **Data honesty** — what is sandbox, fixture and simulated.

## 3. Testing instructions (template)

```
Live demo: https://<pact-web>.onrender.com/judge
(Free hosting sleeps when idle — the first load can take ~60 s.)

1. Click "Reset", then run any scenario. Each runs against the PayPal sandbox and
   opens the linked view: merchant side on the left, Maya's agent on the right.
2. For S2/S3, open Maya's inbox (/buyer) and use the PayPal link.
   Sandbox login: <maya-sandbox-email> / <password>
3. If S6 is included: open Arjun's inbox (/customer/arjun).
   Sandbox login: <arjun-sandbox-email> / <password>

Run locally: see README → "Running it". Without credentials it runs in fixture mode.
```

The rules require including any sandbox logins needed to test — sandbox accounts
only; never real credentials.

## 4. Compliance checklist

- [ ] Public repo (GitHub), all source + assets + run instructions
- [ ] `LICENSE` (MIT) visible in the repo's About section
- [ ] Meaningful PayPal integration via the sandbox — Orders, Vault, webhooks
- [ ] Meaningful AI — listed in the "AI tools used" section
- [ ] Working demo: hosted URL **and** run instructions
- [ ] Video < 3:00, public on YouTube, shows the product working, no unlicensed music
- [ ] Text description of features
- [ ] Built-during-hackathon section
- [ ] One sponsor prize selected (AG Grid) and its use described concretely
- [ ] Everything in English
- [ ] Demo stays up and free to test until judging ends

## 5. AG Grid sponsor angle

Use it where a grid is genuinely the right tool, and say so in the write-up:

- Decision ledger: row grouping by failure class → outcome, pinned NEV column,
  conditional styling for DROP / HELD_OUT / RECOVERED, master-detail row expanding
  into the stage trace.
- Audit trail: append-only rows streaming in, filter by intent.
- Buyer view: guard decisions with the rule that fired.

Use only Community-edition features unless an Enterprise trial licence is
confirmed (master-detail and row grouping may be Enterprise — check before
building, and use expandable rows if not).
