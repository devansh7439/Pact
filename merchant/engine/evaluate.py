"""Evaluation harness: does the decision policy earn its keep? Every number is SIMULATED.

Three strategies run over the same batch, judged by
the same oracle and the same per-intent random draws, so the comparison is
paired and the difference is the policy's effect alone:

  do_nothing  — the organic baseline every recovery claim must subtract.
  blind_retry — re-present the same instrument N times, whatever the decline.
  pact        — diagnose, price, act only where NEV clears the floor.

Agent-channel offers are scored by their chosen (best) action. The buyer's guard
may pick a different option, or escalate; that is buyer-side and not modelled here.

    python -m merchant.engine.evaluate
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from merchant.engine.economics import (
    ACTION_COSTS,
    DEFAULT_POLICY,
    MerchantPolicy,
    RecoveryAction,
)
from merchant.engine.policy import (
    Channel,
    FundingSource,
    PolicyDecision,
    RecoveryContext,
    decide,
)
from merchant.engine.taxonomy import Classification, FailureClass, classify
from merchant.simulator.generate import SyntheticEvent
from merchant.simulator.oracle import observe, observe_do_nothing
from shared.money import fmt

#: Classes where no intervention can succeed: money spent here is wasted, not unlucky.
STRUCTURALLY_UNRECOVERABLE: frozenset[FailureClass] = frozenset({FailureClass.ALREADY_PAID})

CONTACT_ACTIONS = frozenset({RecoveryAction.CHECKOUT_LINK})


@dataclass(slots=True)
class StrategyResult:
    name: str
    n_events: int
    revenue_at_risk_minor: int
    actions_taken: int = 0
    action_breakdown: dict[str, int] = field(default_factory=dict)
    action_cost_minor: int = 0
    gross_recovered_minor: int = 0
    organic_recovered_minor: int = 0
    incremental_recovered_minor: int = 0
    wasted_actions: int = 0
    wasted_cost_minor: int = 0
    actions_on_unrecoverable: int = 0
    exceptions: int = 0

    @property
    def net_value_minor(self) -> int:
        """Incremental revenue caused, less what was spent causing it."""
        return self.incremental_recovered_minor - self.action_cost_minor

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "net_value_minor": self.net_value_minor,
                "provenance": "simulated"}


def context_for(event: SyntheticEvent, contacts_today: int = 0) -> RecoveryContext:
    """What the merchant knows about this intent: channel, saved sources, history."""
    channel = Channel(event.channel)
    sources = (FundingSource("primary", event.funding_kind),) + tuple(
        FundingSource(f"alt-{i + 1}", "PAYPAL_WALLET" if i == 0 else "CARD")
        for i in range(event.alternate_funding_count))
    return RecoveryContext(
        channel=channel, failed_funding_aliases=("primary",), funding_sources=sources,
        agent_registered=True, attempts_so_far=max(0, event.attempt_number - 1),
        contacts_today=contacts_today, currency_code=event.currency,
    )


def _classify(e: SyntheticEvent) -> Classification:
    return classify(e.processor_response_code, e.issue)


def run_do_nothing(events, classes) -> StrategyResult:
    r = StrategyResult("Do nothing", len(events), sum(e.amount for e in events))
    for e, c in zip(events, classes):
        o = observe_do_nothing(e, c.failure_class.value)
        r.gross_recovered_minor += o.recovered_minor
        r.organic_recovered_minor += o.recovered_minor
    return r


def run_blind_retry(events, classes, attempts: int = 3) -> StrategyResult:
    r = StrategyResult(f"Blind retry (x{attempts})", len(events), sum(e.amount for e in events))
    per_attempt = ACTION_COSTS[RecoveryAction.RETRY_SAME_INSTRUMENT].total_minor
    for e, c in zip(events, classes):
        spend = per_attempt * attempts
        r.actions_taken += attempts
        r.action_cost_minor += spend
        o = observe(e, RecoveryAction.RETRY_SAME_INSTRUMENT, c.failure_class.value)
        r.gross_recovered_minor += o.recovered_minor
        r.organic_recovered_minor += e.amount if o.would_have_recovered_organically else 0
        r.incremental_recovered_minor += o.incremental_minor
        if not o.recovered:
            r.wasted_actions += attempts
            r.wasted_cost_minor += spend
        if c.failure_class in STRUCTURALLY_UNRECOVERABLE:
            r.actions_on_unrecoverable += attempts
    r.action_breakdown = {RecoveryAction.RETRY_SAME_INSTRUMENT.value: r.actions_taken}
    return r


def run_pact(events, classes, propensities, policy: MerchantPolicy = DEFAULT_POLICY,
             ) -> tuple[StrategyResult, list[tuple[SyntheticEvent, Classification, PolicyDecision]]]:
    r = StrategyResult("Pact", len(events), sum(e.amount for e in events))
    breakdown: Counter[str] = Counter()
    decisions = []
    contacts: Counter[str] = Counter()  # contact caps are per customer, across the batch

    for e, c, p in zip(events, classes, propensities):
        d = decide(c, e.amount, p, context_for(e, contacts[e.customer_id]), policy)
        decisions.append((e, c, d))
        if d.is_exception:
            r.exceptions += 1
        if d.action is RecoveryAction.DROP:
            o = observe_do_nothing(e, c.failure_class.value)
            r.gross_recovered_minor += o.recovered_minor
            r.organic_recovered_minor += o.recovered_minor
            continue
        cost = ACTION_COSTS[d.action].total_minor
        r.actions_taken += 1
        breakdown[d.action.value] += 1
        r.action_cost_minor += cost
        if d.action in CONTACT_ACTIONS:
            contacts[e.customer_id] += 1
        o = observe(e, d.action, c.failure_class.value)
        r.gross_recovered_minor += o.recovered_minor
        r.organic_recovered_minor += e.amount if o.would_have_recovered_organically else 0
        r.incremental_recovered_minor += o.incremental_minor
        if not o.recovered:
            r.wasted_actions += 1
            r.wasted_cost_minor += cost
        if c.failure_class in STRUCTURALLY_UNRECOVERABLE:
            r.actions_on_unrecoverable += 1
    r.action_breakdown = dict(breakdown)
    return r, decisions


def evaluate_batch(events: list[SyntheticEvent], policy: MerchantPolicy = DEFAULT_POLICY,
                   propensities: list[float] | None = None) -> dict[str, Any]:
    """Run all three strategies. `propensities` defaults to the trained model's output."""
    classes = [_classify(e) for e in events]
    if propensities is None:
        from merchant.ml.predict import predict_propensity_batch
        propensities = predict_propensity_batch(events)
    nothing = run_do_nothing(events, classes)
    blind = run_blind_retry(events, classes)
    pact, decisions = run_pact(events, classes, propensities, policy)
    return {
        "provenance": "simulated",
        "batch_size": len(events),
        "revenue_at_risk_minor": sum(e.amount for e in events),
        "strategies": {"do_nothing": nothing.to_dict(), "blind_retry": blind.to_dict(),
                       "pact": pact.to_dict()},
        "delta_vs_blind": {
            "net_value_minor": pact.net_value_minor - blind.net_value_minor,
            "actions_saved": blind.actions_taken - pact.actions_taken,
            "cost_saved_minor": blind.action_cost_minor - pact.action_cost_minor,
            "wasted_actions_avoided": blind.wasted_actions - pact.wasted_actions,
        },
        "exceptions": pact.exceptions,
        "_decisions": decisions,
    }


def main() -> None:
    from merchant.simulator.generate import generate_events
    events = generate_events(1000, seed=77771111)  # different seed from training
    rep = evaluate_batch(events)
    s = rep["strategies"]
    print("=" * 74)
    print("  PACT - measured recovery over a held-out batch   [SIMULATED]")
    print("=" * 74)
    print(f"  batch {rep['batch_size']:,} failed payments, "
          f"{fmt(rep['revenue_at_risk_minor'])} at risk")
    print(f"  {'':<20}{'actions':>9}{'spend':>12}{'incremental':>14}{'net value':>13}")
    for k in ("do_nothing", "blind_retry", "pact"):
        x = s[k]
        print(f"  {x['name']:<20}{x['actions_taken']:>9,}{fmt(x['action_cost_minor']):>12}"
              f"{fmt(x['incremental_recovered_minor']):>14}{fmt(x['net_value_minor']):>13}")
    print("  Pact action mix:", ", ".join(
        f"{a} {n}" for a, n in sorted(s["pact"]["action_breakdown"].items(), key=lambda kv: -kv[1])))
    print(f"  of {fmt(s['pact']['gross_recovered_minor'])} gross, "
          f"{fmt(s['pact']['organic_recovered_minor'])} would have arrived anyway; "
          f"exceptions {rep['exceptions']}")


if __name__ == "__main__":
    main()
