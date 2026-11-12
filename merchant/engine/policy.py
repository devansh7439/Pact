"""The deterministic policy engine (doc 05 §3).

No model inference, no LLM, no randomness: the same inputs give the same
decision, and the decision can be read off the code. The model answers "how
likely is this to work?", the LLM answers "how do we say it?", and only this
module answers "should we spend money on this?".

Three ordered stages, and the order is load-bearing:

  1. Hard constraints — terminal stops (already paid, undiagnosed, attempt cap,
     agent not registered, high value) and narrowing rules (risk, same
     instrument, consent, opt-out, contact frequency). The score is not read.
  2. Eligibility — which actions are coherent for this class *and channel*.
  3. Economics — price what survives; act only if the best clears the floor.

Every candidate action ends up as a row in the per-option table, with either its
valuation or the rule that removed it, so the console can show what the engine
refused to consider as well as what it chose.

Channel-aware: agent and human channels get different action sets.
HARD_RISK_NO_AUTONOMY narrows to payer action / review rather than dropping, and
HARD_NO_SAME_INSTRUMENT, HARD_CONSENT_INVALID and HARD_AGENT_NOT_REGISTERED guard
the agent channel. LLM diagnoses carry a reduced confidence ceiling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from merchant.engine.diagnosis import autonomy_ceiling as ai_autonomy_ceiling
from merchant.engine.economics import (
    DEFAULT_POLICY,
    OFFER_ACTIONS,
    MerchantPolicy,
    RecoveryAction,
    Valuation,
    value_action,
)
from merchant.engine.taxonomy import Classification, FailureClass
from shared.money import fmt

A = RecoveryAction


class Channel(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


#: Stage 2 — eligibility by class and channel (doc 05 table). DROP is always the
#: baseline and is not listed. RETRY_SAME_INSTRUMENT appears nowhere: no PayPal
#: class permits it autonomously.
ELIGIBLE: dict[FailureClass, dict[Channel, frozenset[RecoveryAction]]] = {
    FailureClass.INSUFFICIENT_FUNDS: {
        Channel.AGENT: frozenset({A.ALTERNATE_FUNDING_OFFER, A.RETRY_AFTER_OFFER,
                                  A.PAYER_ACTION_OFFER, A.ESCALATE}),
        Channel.HUMAN: frozenset({A.CHECKOUT_LINK, A.ESCALATE}),
    },
    FailureClass.INSTRUMENT_INVALID: {
        Channel.AGENT: frozenset({A.ALTERNATE_FUNDING_OFFER, A.PAYER_ACTION_OFFER, A.ESCALATE}),
        Channel.HUMAN: frozenset({A.CHECKOUT_LINK, A.ESCALATE}),
    },
    FailureClass.ISSUER_DECLINED: {
        Channel.AGENT: frozenset({A.ALTERNATE_FUNDING_OFFER, A.PAYER_ACTION_OFFER, A.ESCALATE}),
        Channel.HUMAN: frozenset({A.CHECKOUT_LINK, A.ESCALATE}),
    },
    FailureClass.AUTH_FAILURE: {
        Channel.AGENT: frozenset({A.PAYER_ACTION_OFFER, A.ESCALATE}),
        Channel.HUMAN: frozenset({A.CHECKOUT_LINK, A.ESCALATE}),
    },
    FailureClass.RISK_BLOCKED: {
        Channel.AGENT: frozenset({A.PAYER_ACTION_OFFER, A.ESCALATE}),
        Channel.HUMAN: frozenset({A.ESCALATE}),
    },
    FailureClass.MERCHANT_CONFIG: {
        Channel.AGENT: frozenset({A.ESCALATE}),
        Channel.HUMAN: frozenset({A.ESCALATE}),
    },
    FailureClass.ALREADY_PAID: {Channel.AGENT: frozenset(), Channel.HUMAN: frozenset()},
    FailureClass.UNKNOWN: {Channel.AGENT: frozenset(), Channel.HUMAN: frozenset()},
}

#: Candidate rows shown in the per-option table, per channel.
CANDIDATES: dict[Channel, tuple[RecoveryAction, ...]] = {
    Channel.AGENT: (A.ALTERNATE_FUNDING_OFFER, A.PAYER_ACTION_OFFER, A.RETRY_AFTER_OFFER,
                    A.RETRY_SAME_INSTRUMENT, A.ESCALATE),
    Channel.HUMAN: (A.CHECKOUT_LINK, A.RETRY_SAME_INSTRUMENT, A.ESCALATE),
}

#: Actions that need a saved, consented funding source other than the failed one.
NEEDS_SAVED_SOURCE: frozenset[RecoveryAction] = frozenset(
    {A.ALTERNATE_FUNDING_OFFER, A.RETRY_AFTER_OFFER})

#: Actions that put a merchant message in front of a human customer.
CUSTOMER_CONTACT: frozenset[RecoveryAction] = frozenset({A.CHECKOUT_LINK})


@dataclass(frozen=True, slots=True)
class FundingSource:
    """A saved funding source as the engine sees it. `vault_id` never appears here.

    consent_valid is the HARD_CONSENT_INVALID check, evaluated by the caller:
    saved method active, owned by this customer, covered by an unexpired
    registered mandate, agent registration active. It is re-checked immediately
    before every PayPal call by the executor — this is only the decision-time pass.
    """

    alias: str
    kind: str  # "CARD" | "PAYPAL_WALLET"
    consent_valid: bool = True


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Everything known about a payment intent at decision time."""

    channel: Channel = Channel.HUMAN
    #: Every alias that has already declined on *this intent*, not just the latest.
    #: After S3's card and then wallet both decline, neither may be offered again.
    failed_funding_aliases: tuple[str, ...] = ()
    funding_sources: tuple[FundingSource, ...] = ()
    agent_registered: bool = True
    attempts_so_far: int = 0
    contacts_today: int = 0
    hours_since_last_contact: float | None = None
    customer_opted_out: bool = False
    already_recovered: bool = False
    kill_switch_active: bool = False
    currency_code: str = "USD"


class Verdict(str, Enum):
    CHOSEN = "chosen"
    OFFERED = "offered"            # included in the PRP offer as a fallback option
    BELOW_FLOOR = "below_floor"
    NOT_BEST = "not_best"          # cleared the floor, but a better action was chosen
    REMOVED = "removed"
    BASELINE = "baseline"


@dataclass(frozen=True, slots=True)
class OptionRow:
    """One row of the per-option table (doc 05 §3)."""

    action: RecoveryAction
    verdict: Verdict
    valuation: Valuation | None = None
    removed_by: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "verdict": self.verdict.value,
            "removed_by": self.removed_by,
            **(self.valuation.to_dict() if self.valuation else {}),
        }


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """A decision with the complete reasoning that produced it.

    Attributes:
        action: What to do. For the agent channel, the best offer action; the
            offer itself carries every action in `offer_actions` plus CANCEL.
        rule_id: Stable id of the rule that decided.
        options: The per-option table, every candidate plus the DROP baseline.
        offer_actions: Agent channel only — actions to include in the PRP offer.
        eligible_funding_aliases: Aliases the offer may list (never the failed
            one when retry is disallowed; only consent-valid ones).
        execution_blocked_by: Set when the decision is recorded but must not be
            executed (HARD_KILL_SWITCH).
    """

    action: RecoveryAction
    rationale: str
    rule_id: str
    valuation: Valuation | None = None
    options: tuple[OptionRow, ...] = ()
    offer_actions: tuple[RecoveryAction, ...] = ()
    eligible_funding_aliases: tuple[str, ...] = ()
    constraints_applied: tuple[str, ...] = ()
    is_exception: bool = False
    retry_after_hours: float | None = None
    execution_blocked_by: str | None = None

    @property
    def considered(self) -> tuple[Valuation, ...]:
        """Priced candidates, best first."""
        priced = [r.valuation for r in self.options
                  if r.valuation is not None and r.verdict is not Verdict.BASELINE]
        return tuple(sorted(priced, key=lambda v: v.net_ev_minor, reverse=True))


@dataclass
class _Trace:
    applied: list[str] = field(default_factory=list)
    removed: dict[RecoveryAction, str] = field(default_factory=dict)

    def remove(self, actions: frozenset[RecoveryAction] | set[RecoveryAction],
               rule: str, pool: set[RecoveryAction]) -> None:
        hit = pool & set(actions)
        for a in hit:
            self.removed.setdefault(a, rule)
        pool -= hit
        if hit:
            self.applied.append(rule)


def _stop(action: RecoveryAction, rule_id: str, rationale: str, ctx: RecoveryContext,
          *, exception: bool = False) -> PolicyDecision:
    rows = tuple(OptionRow(a, Verdict.REMOVED, removed_by=rule_id)
                 for a in CANDIDATES[ctx.channel] if a is not action)
    return PolicyDecision(
        action=action, rule_id=rule_id, rationale=rationale,
        options=rows + (OptionRow(A.DROP, Verdict.BASELINE),),
        constraints_applied=(rule_id,), is_exception=exception,
        execution_blocked_by="HARD_KILL_SWITCH" if ctx.kill_switch_active else None,
    )


def decide(
    classification: Classification,
    amount_minor: int,
    base_propensity: float,
    context: RecoveryContext | None = None,
    policy: MerchantPolicy = DEFAULT_POLICY,
    effectiveness_for: Callable[[str, RecoveryAction], float] | None = None,
) -> PolicyDecision:
    """Choose a recovery action for one failed payment intent."""
    ctx = context or RecoveryContext()
    fc = classification.failure_class
    m = lambda v: fmt(v, ctx.currency_code)  # noqa: E731

    # -- Stage 1a: terminal hard constraints ------------------------------
    if fc is FailureClass.ALREADY_PAID or ctx.already_recovered:
        return _stop(A.DROP, "HARD_ALREADY_PAID",
                     "A capture for this intent already completed. Acting again risks "
                     "charging the customer twice; nothing is owed.", ctx)

    if not classification.confident or fc is FailureClass.UNKNOWN:
        return _stop(A.DROP, "HARD_UNDIAGNOSED",
                     f"Decline could not be confidently diagnosed. {classification.note} "
                     "The engine does not guess an intervention; routed to the exception queue.",
                     ctx, exception=True)

    if ctx.attempts_so_far >= policy.max_attempts_per_payment:
        return _stop(A.DROP, "HARD_ATTEMPT_CAP",
                     f"Attempt cap reached: {ctx.attempts_so_far} of "
                     f"{policy.max_attempts_per_payment} recovery attempts already made.", ctx)

    if ctx.channel is Channel.AGENT and not ctx.agent_registered:
        return _stop(A.DROP, "HARD_AGENT_NOT_REGISTERED",
                     "Agent-channel purchase without an active registration and mandate. "
                     "No offer can be issued.", ctx, exception=True)

    ceiling = policy.max_autonomous_amount_minor
    if classification.diagnosed_by == "llm":
        ceiling = ai_autonomy_ceiling(ceiling)
    if policy.require_human_above_threshold and amount_minor > ceiling:
        basis = " (reduced: diagnosis came from the LLM fallback)" \
            if classification.diagnosed_by == "llm" else ""
        return _stop(A.ESCALATE, "HARD_HIGH_VALUE_ESCALATION",
                     f"{m(amount_minor)} exceeds the autonomy ceiling of {m(ceiling)}{basis}. "
                     "Routed to the review queue before any action.", ctx)

    # -- Stage 1b: narrowing hard constraints -----------------------------
    trace = _Trace()
    candidates = CANDIDATES[ctx.channel]
    pool: set[RecoveryAction] = set(candidates)

    if fc is FailureClass.RISK_BLOCKED:
        keep = {A.PAYER_ACTION_OFFER} if ctx.channel is Channel.AGENT else {A.ESCALATE}
        trace.remove(pool - keep, "HARD_RISK_NO_AUTONOMY", pool)

    if not classification.retry_same_instrument:
        trace.remove({A.RETRY_SAME_INSTRUMENT}, "HARD_NO_SAME_INSTRUMENT", pool)

    unfailed = tuple(s for s in ctx.funding_sources
                     if classification.retry_same_instrument
                     or s.alias not in ctx.failed_funding_aliases)
    aliases = tuple(s.alias for s in unfailed if s.consent_valid)
    if not aliases:
        # Name the real reason: every saved source has already declined on this
        # intent, versus untried sources that lack valid consent (or none saved).
        rule = ("HARD_NO_SAME_INSTRUMENT" if ctx.funding_sources and not unfailed
                else "HARD_CONSENT_INVALID")
        trace.remove(NEEDS_SAVED_SOURCE, rule, pool)

    if ctx.channel is Channel.HUMAN:
        # When the customer may not be contacted, escalating to ops is no way
        # around it: ops recovering a customer-actionable decline means contacting
        # the customer. Only config faults and risk reviews stay escalatable.
        # (Without this, a contact-capped payment falls through to ESCALATE —
        # 109 of 1,000 decisions in the evaluation batch.)
        no_contact = set(CUSTOMER_CONTACT)
        if fc not in (FailureClass.MERCHANT_CONFIG, FailureClass.RISK_BLOCKED):
            no_contact.add(A.ESCALATE)
        if ctx.customer_opted_out:
            trace.remove(no_contact, "HARD_OPT_OUT", pool)
        elif ctx.contacts_today >= policy.max_contacts_per_customer_per_day:
            trace.remove(no_contact, "CONTACT_DAILY_CAP", pool)
        elif (ctx.hours_since_last_contact is not None
              and ctx.hours_since_last_contact < policy.cooldown_hours):
            trace.remove(no_contact, "CONTACT_COOLDOWN", pool)

    # -- Stage 2: eligibility ---------------------------------------------
    trace.remove(pool - ELIGIBLE[fc][ctx.channel], "NOT_ELIGIBLE_FOR_CLASS", pool)

    if not pool:
        rows = tuple(OptionRow(a, Verdict.REMOVED, removed_by=trace.removed.get(a))
                     for a in candidates) + (OptionRow(A.DROP, Verdict.BASELINE),)
        return PolicyDecision(
            action=A.DROP, rule_id="NO_VIABLE_ACTION",
            rationale=(f"{fc.value}: every candidate action was removed by a guardrail "
                       f"({', '.join(dict.fromkeys(trace.applied)) or 'eligibility'})."),
            options=rows, constraints_applied=tuple(dict.fromkeys(trace.applied)),
            is_exception=fc is FailureClass.RISK_BLOCKED,
            execution_blocked_by="HARD_KILL_SWITCH" if ctx.kill_switch_active else None,
        )

    # -- Stage 3: economics -----------------------------------------------
    def price(a: RecoveryAction) -> Valuation:
        return value_action(a, amount_minor, base_propensity, fc.value, policy,
                            effectiveness_for, ctx.currency_code)

    priced = sorted((price(a) for a in pool), key=lambda v: v.net_ev_minor, reverse=True)
    best = priced[0]
    baseline = price(A.DROP)
    clears = {v.action for v in priced if v.net_ev_minor >= policy.min_net_ev_minor}
    applied = tuple(dict.fromkeys(trace.applied))
    blocked = "HARD_KILL_SWITCH" if ctx.kill_switch_active else None

    if best.net_ev_minor < policy.min_net_ev_minor:
        rows = _rows(candidates, priced, trace, chosen=None, offered=set(), clears=clears)
        return PolicyDecision(
            action=A.DROP, rule_id="ECON_BELOW_FLOOR",
            rationale=(f"Best available action ({best.action.value}) nets "
                       f"{m(best.net_ev_minor)}, below the {m(policy.min_net_ev_minor)} floor. "
                       f"{best.explain()}. Chasing this costs more than it is worth."),
            valuation=best, options=rows + (OptionRow(A.DROP, Verdict.CHOSEN, baseline),),
            constraints_applied=applied, execution_blocked_by=blocked,
        )

    offered: set[RecoveryAction] = set()
    if ctx.channel is Channel.AGENT and best.action in OFFER_ACTIONS:
        offered = {a for a in clears if a in OFFER_ACTIONS}

    retry_after = None
    if A.RETRY_AFTER_OFFER in offered or best.action is A.RETRY_AFTER_OFFER:
        retry_after = classification.typical_resolution_hours or 24.0

    rows = _rows(candidates, priced, trace, chosen=best.action, offered=offered, clears=clears)
    offer_note = ""
    if offered:
        offer_note = (f" Offer carries {len(offered)} option(s) plus CANCEL: "
                      f"{', '.join(sorted(a.value for a in offered))}.")
    return PolicyDecision(
        action=best.action, rule_id=f"ECON_MAX_NEV__{fc.value}",
        rationale=(f"{fc.value}: {best.action.value} has the highest net expected value of "
                   f"{len(priced)} eligible action(s). {best.explain()}.{offer_note}"),
        valuation=best,
        options=rows + (OptionRow(A.DROP, Verdict.BASELINE, baseline),),
        offer_actions=tuple(a for a in candidates if a in offered),
        eligible_funding_aliases=aliases if offered & set(NEEDS_SAVED_SOURCE) else (),
        constraints_applied=applied, retry_after_hours=retry_after,
        execution_blocked_by=blocked,
    )


def _rows(candidates: tuple[RecoveryAction, ...], priced: list[Valuation], trace: _Trace, *,
          chosen: RecoveryAction | None, offered: set[RecoveryAction],
          clears: set[RecoveryAction]) -> tuple[OptionRow, ...]:
    by_action = {v.action: v for v in priced}
    rows: list[OptionRow] = []
    for a in candidates:
        if a in trace.removed:
            rows.append(OptionRow(a, Verdict.REMOVED, removed_by=trace.removed[a]))
        elif a == chosen:
            rows.append(OptionRow(a, Verdict.CHOSEN, by_action[a]))
        elif a in offered:
            rows.append(OptionRow(a, Verdict.OFFERED, by_action[a]))
        elif a in clears:
            rows.append(OptionRow(a, Verdict.NOT_BEST, by_action[a]))
        else:
            rows.append(OptionRow(a, Verdict.BELOW_FLOOR, by_action.get(a)))
    return tuple(rows)
