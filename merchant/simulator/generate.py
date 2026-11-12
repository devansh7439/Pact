"""Synthetic PayPal declines for training and evaluation. Every row is SIMULATED.

The generator follows an anti-circularity design:

  1. Outcomes are driven by latent variables the model never sees (true
     reliability, intent, issuer health).
  2. Observable features are noisy proxies (`customer_success_rate` is a small,
     noisy sample of true reliability), never copies.
  3. Outcomes are Bernoulli draws, so even a perfect model cannot beat the Bayes
     rate — an AUC near 0.99 here would mean a leak, not skill.

Changes for Pact: PayPal decline signals (processor codes / Orders issues),
USD cents, an agent vs human channel, and the count of other saved, consented
funding sources (what alternate-funding recovery depends on).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from merchant.engine.taxonomy import ALL_ENTRIES, FailureClass, SignalKind

#: Decline mix. Insufficient funds and generic/do-not-honor dominate real card
#: declines; risk and merchant-config are rare but are exactly where blind retry
#: wastes money. Weights are per taxonomy code.
CODE_WEIGHTS: dict[str, float] = {
    "5120": 24.0,  # insufficient funds
    "5100": 14.0,  # generic decline
    "0500": 12.0,  # do not honor
    "5400": 7.0,   # expired card
    "5180": 3.0,   # invalid or restricted
    "1330": 1.5,   # invalid account
    "00N7": 4.0,   # CVV failure
    "9500": 3.0,   # suspected fraud
    "9520": 1.0,   # lost or stolen
    "INSTRUMENT_DECLINED": 8.0,
    "TRANSACTION_REFUSED": 3.0,
    "PAYER_ACTION_REQUIRED": 5.0,
    "PAYER_CANNOT_PAY": 2.0,
    "COMPLIANCE_VIOLATION": 0.5,
    "PAYEE_ACCOUNT_RESTRICTED": 0.8,
    "PAYEE_ACCOUNT_LOCKED_OR_CLOSED": 0.3,
    "ORDER_ALREADY_CAPTURED": 0.8,
    "DUPLICATE_INVOICE_ID": 0.4,
}
_ENTRY = {e.code: e for e in ALL_ENTRIES}
assert set(CODE_WEIGHTS) <= set(_ENTRY), "simulator weights reference unmapped codes"

#: Share of events with no usable signal, so the exception path is exercised by data.
UNMAPPED_RATE = 0.04
AGENT_SHARE = 0.40
MAX_CUSTOMER_POOL = 50_000

FIRST_NAMES = ("Maya", "Arjun", "Sam", "Alex", "Priya", "Jordan", "Lena", "Omar", "Grace",
               "Diego", "Hana", "Noah", "Zara", "Leo", "Ivy", "Mateo", "Aisha", "Ben")
LAST_NAMES = ("Lee", "Patel", "Garcia", "Kim", "Nguyen", "Smith", "Okafor", "Rossi",
              "Cohen", "Silva", "Khan", "Novak", "Brown", "Tanaka", "Moreau", "Haddad")


@dataclass(slots=True)
class SyntheticEvent:
    """One failed PayPal attempt on a payment intent.

    Three groups of fields, and the split is what keeps evaluation honest:
      - decline signal (`id` .. `error_description`): what PayPal returns;
      - merchant-side context (`channel` onward): history a real merchant holds;
      - latent truth (`_true_*`): never a model input, only the oracle reads it.
    """

    # -- PayPal decline signal ------------------------------------------------
    id: str
    paypal_order_id: str
    amount: int
    currency: str
    funding_kind: str
    created_at: str
    processor_response_code: str | None
    issue: str | None
    error_description: str

    # -- Merchant-side observable context ------------------------------------
    channel: str
    alternate_funding_count: int
    customer_id: str
    customer_name: str
    customer_email: str
    customer_success_rate: float
    customer_tenure_days: int
    prior_payment_count: int
    prior_failure_count: int
    hours_since_last_success: float
    attempt_number: int
    hour_of_day: int
    day_of_week: int

    # -- Latent ground truth: never a model input ----------------------------
    _true_reliability: float
    _true_intent: float
    _true_issuer_health: float
    _true_base_propensity: float

    def features(self) -> dict[str, object]:
        """The model's input. Latent fields are structurally excluded."""
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _amount_minor(rng: random.Random) -> int:
    """Heavy-tailed ticket size: median ~$37, clamped to $1–$2,000."""
    dollars = rng.lognormvariate(mu=3.6, sigma=1.0)
    return max(100, min(int(dollars * 100), 200_000))


def _true_base_propensity(reliability: float, intent: float, issuer_health: float,
                          failure_class: FailureClass, amount_minor: int,
                          attempt_number: int, channel: str) -> float:
    """Latent P(customer completes payment given any remedy). A smooth interaction
    of latent factors, not a per-class lookup the model could read off the code."""
    base = 0.55 * reliability + 0.35 * intent + 0.10 * issuer_health
    base -= min(0.18, (amount_minor / 50_000) * 0.05)       # large tickets: more deliberation
    base *= 0.86 ** max(0, attempt_number - 1)              # repeated failures: weaker case
    if channel == "agent":
        base += 0.03                                        # the errand was delegated on purpose
    tilt = {
        FailureClass.INSUFFICIENT_FUNDS: -0.04,
        FailureClass.INSTRUMENT_INVALID: -0.02,
        FailureClass.AUTH_FAILURE: 0.02,
        FailureClass.RISK_BLOCKED: -0.10,
    }.get(failure_class, 0.0)
    return max(0.02, min(0.97, base + tilt))


def generate_events(n: int, seed: int = 20261111) -> list[SyntheticEvent]:
    """A batch, chronologically ordered. Fixed seed: reviewers get identical data."""
    events = list(stream_events(n, seed=seed))
    events.sort(key=lambda e: e.created_at)
    return events


def stream_events(n: int, seed: int = 20261111) -> Iterator[SyntheticEvent]:
    """Yield events lazily (generation order, not chronological)."""
    if n < 1:
        raise ValueError(f"n must be positive, got {n}")
    rng = random.Random(seed)

    # ~8 events per customer: recovery populations are heavily repeat, and that
    # history is most of what a merchant can learn from. Capped so setup stays bounded.
    n_customers = max(4, min(n // 8, MAX_CUSTOMER_POOL))
    customers: list[dict] = []
    for i in range(n_customers):
        is_agent = rng.random() < AGENT_SHARE
        customers.append({
            "customer_id": f"cus_{i:05d}",
            "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "reliability": rng.betavariate(4.2, 2.6),
            "tenure_days": rng.randint(1, 1400),
            "channel": "agent" if is_agent else "human",
            # Agent principals saved sources at onboarding; humans less often.
            "alternates": (rng.choices((0, 1, 2), weights=(2, 5, 3))[0] if is_agent
                           else rng.choices((0, 1), weights=(6, 4))[0]),
            "prior_payments": 0,
            "prior_failures": 0,
        })

    issuer_health = 0.85
    base_time = datetime(2026, 11, 1, tzinfo=timezone.utc)

    for i in range(n):
        cust = customers[rng.randrange(n_customers)]
        issuer_health = max(0.25, min(0.98, issuer_health + rng.gauss(0, 0.06)))

        if rng.random() < UNMAPPED_RATE:
            code, entry, fc = None, None, FailureClass.UNKNOWN
            processor_code, issue = None, None
            description = "The transaction could not be completed."
        else:
            weights = dict(CODE_WEIGHTS)
            # Generic/issuer declines get likelier while issuers are unhealthy.
            for c in ("5100", "0500", "INSTRUMENT_DECLINED"):
                weights[c] += (1.0 - issuer_health) * 18.0
            code = _weighted_choice(rng, weights)
            entry = _ENTRY[code]
            fc = entry.failure_class
            processor_code = code if entry.kind is SignalKind.PROCESSOR else None
            issue = code if entry.kind is SignalKind.ISSUE else None
            description = entry.guidance

        amount = _amount_minor(rng)
        timestamp = base_time + timedelta(minutes=rng.randint(0, 60 * 24 * 3))
        attempt_number = 1
        if cust["prior_failures"] > 0 and rng.random() < 0.30:
            attempt_number = 2
        intent = max(0.03, min(0.97, rng.betavariate(3.0, 2.4)))
        true_prop = _true_base_propensity(cust["reliability"], intent, issuer_health, fc,
                                          amount, attempt_number, cust["channel"])

        observed_n = max(1, min(cust["prior_payments"], 40))
        noise = rng.gauss(0, 0.11 / observed_n ** 0.5)
        success_rate = max(0.0, min(1.0, cust["reliability"] + noise))

        h = lambda tag: hashlib.md5(f"{seed}:{tag}:{i}".encode()).hexdigest()[:20]  # noqa: E731
        yield SyntheticEvent(
            id=f"pi_{h('i')}",
            paypal_order_id=h("o").upper()[:17],
            amount=amount,
            currency="USD",
            funding_kind="CARD" if rng.random() < 0.75 else "PAYPAL_WALLET",
            created_at=timestamp.isoformat(),
            processor_response_code=processor_code,
            issue=issue,
            error_description=description,
            channel=cust["channel"],
            alternate_funding_count=cust["alternates"],
            customer_id=cust["customer_id"],
            customer_name=cust["name"],
            customer_email=f"{cust['name'].split()[0].lower()}{cust['customer_id'][-4:]}@example.com",
            customer_success_rate=round(success_rate, 4),
            customer_tenure_days=cust["tenure_days"],
            prior_payment_count=cust["prior_payments"],
            prior_failure_count=cust["prior_failures"],
            hours_since_last_success=round(rng.expovariate(1 / 72.0), 2),
            attempt_number=attempt_number,
            hour_of_day=timestamp.hour,
            day_of_week=timestamp.weekday(),
            _true_reliability=round(cust["reliability"], 4),
            _true_intent=round(intent, 4),
            _true_issuer_health=round(issuer_health, 4),
            _true_base_propensity=round(true_prop, 4),
        )

        cust["prior_failures"] += 1
        if rng.random() < cust["reliability"]:
            cust["prior_payments"] += 1
