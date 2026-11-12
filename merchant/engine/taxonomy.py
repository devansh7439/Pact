"""PayPal decline taxonomy.

Maps every PayPal decline signal we can observe to a *failure class* — the level
at which recovery economics actually differ (doc 05 §1). A decline reaches us in
one of two places, and `classify` reads both:

1. A capture with `status: DECLINED` carrying
   `processor_response.response_code` (card declines).
2. An HTTP 422 whose `details[].issue` names the problem (Orders v2 errors).

The processor code is more specific than the issue, so it wins when both are
present. Anything neither maps is returned *unconfident* and lands on the
exception queue (or the LLM fallback in `diagnosis.py`) — it is never guessed.

Sources:
  - Sandbox decline triggers and codes:
    https://developer.paypal.com/tools/sandbox/card-testing/
  - Orders v2 `processor_response`:
    https://developer.paypal.com/docs/api/orders/v2/
  - Orders v2 error issues:
    https://developer.paypal.com/api/rest/reference/orders/v2/errors/

`status` on each entry follows the blueprint legend: VERIFIED entries were
checked against PayPal's docs when the blueprint was written; DESIGN entries use
a documented issue name with a class mapping that is our own decision.

Build task still open (doc 05): transcribe the *full* processor response code
list into `_PROCESSOR`, with `test_every_code_has_one_class` covering it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INSTRUMENT_INVALID = "INSTRUMENT_INVALID"
    ISSUER_DECLINED = "ISSUER_DECLINED"
    AUTH_FAILURE = "AUTH_FAILURE"
    RISK_BLOCKED = "RISK_BLOCKED"
    MERCHANT_CONFIG = "MERCHANT_CONFIG"
    ALREADY_PAID = "ALREADY_PAID"
    UNKNOWN = "UNKNOWN"


class SignalKind(str, Enum):
    PROCESSOR = "processor_response_code"
    ISSUE = "issue"


@dataclass(frozen=True, slots=True)
class TaxonomyEntry:
    """One PayPal decline signal and what it implies.

    Attributes:
        code: Processor response code (e.g. "5120") or Orders issue string.
        kind: Which of the two signals this is.
        name: PayPal's name for it.
        failure_class: Recovery-relevant grouping.
        retry_same_instrument: Whether re-presenting the *same* funding source
            autonomously could plausibly succeed. False whenever PayPal says to
            use another card, and for every class where only the payer can fix it.
        customer_actionable: Whether the customer can do anything about it.
        guidance: PayPal's documented next step (or ours, for DESIGN entries).
        typical_resolution_hours: Rough time for the blocking condition to clear
            on its own; sizes RETRY_AFTER windows. None means waiting won't help.
        status: VERIFIED or DESIGN (see module docstring).
    """

    code: str
    kind: SignalKind
    name: str
    failure_class: FailureClass
    retry_same_instrument: bool
    customer_actionable: bool
    guidance: str
    typical_resolution_hours: float | None = None
    status: str = "VERIFIED"


def _p(code: str, name: str, fc: FailureClass, guidance: str, *,
       actionable: bool = True, retry_same: bool = False,
       resolution_hours: float | None = None) -> TaxonomyEntry:
    return TaxonomyEntry(code, SignalKind.PROCESSOR, name, fc, retry_same, actionable,
                         guidance, resolution_hours)


def _i(code: str, fc: FailureClass, guidance: str, *, actionable: bool = True,
       status: str = "VERIFIED") -> TaxonomyEntry:
    return TaxonomyEntry(code, SignalKind.ISSUE, code, fc, False, actionable, guidance,
                         None, status)


FC = FailureClass

_PROCESSOR: tuple[TaxonomyEntry, ...] = (
    _p("5120", "INSUFFICIENT_FUNDS", FC.INSUFFICIENT_FUNDS,
       "Funds short right now. Offer another funding source, or retry later.",
       resolution_hours=48.0),
    _p("5400", "EXPIRED_CARD", FC.INSTRUMENT_INVALID,
       "Card has expired. Use another funding source."),
    _p("5180", "INVALID_OR_RESTRICTED_CARD", FC.INSTRUMENT_INVALID,
       "PayPal: use another card; do not retry this one."),
    _p("1330", "INVALID_ACCOUNT", FC.INSTRUMENT_INVALID,
       "Account is invalid. Use another funding source."),
    _p("0500", "DO_NOT_HONOR", FC.ISSUER_DECLINED,
       "Issuer declined without a reason. Do not retry autonomously; offer another source."),
    _p("5100", "GENERIC_DECLINE", FC.ISSUER_DECLINED,
       "Generic decline. Offer another source or a payer-approved checkout."),
    _p("00N7", "CVV2_FAILURE_POSSIBLE_RETRY_WITH_CVV", FC.AUTH_FAILURE,
       "CVV check failed. Only the payer can fix this, by re-entering details."),
    _p("9500", "SUSPECTED_FRAUD", FC.RISK_BLOCKED,
       "PayPal: use another card; do not retry this one. Payer re-authentication only.",
       actionable=False),
    _p("9520", "LOST_OR_STOLEN", FC.RISK_BLOCKED,
       "PayPal: use another card; do not retry this one. Payer re-authentication only.",
       actionable=False),
)

_ISSUES: tuple[TaxonomyEntry, ...] = (
    _i("INSTRUMENT_DECLINED", FC.ISSUER_DECLINED,
       "The funding source was declined. Offer another source."),
    _i("TRANSACTION_REFUSED", FC.ISSUER_DECLINED,
       "The transaction was refused. Offer another source."),
    _i("PAYER_ACTION_REQUIRED", FC.AUTH_FAILURE,
       "The payer must complete an action (e.g. 3DS) on PayPal."),
    _i("PAYER_CANNOT_PAY", FC.ISSUER_DECLINED,
       "Payer cannot pay with this source. Offer another.", status="DESIGN"),
    _i("COMPLIANCE_VIOLATION", FC.RISK_BLOCKED,
       "Blocked for compliance. Never retried; payer or review only.",
       actionable=False, status="DESIGN"),
    _i("PAYEE_ACCOUNT_RESTRICTED", FC.MERCHANT_CONFIG,
       "Our PayPal account is restricted. Ops must fix this; never contact the customer.",
       actionable=False, status="DESIGN"),
    _i("PAYEE_ACCOUNT_LOCKED_OR_CLOSED", FC.MERCHANT_CONFIG,
       "Our PayPal account is locked or closed. Ops must fix this.",
       actionable=False, status="DESIGN"),
    _i("ORDER_ALREADY_CAPTURED", FC.ALREADY_PAID,
       "Already captured. Stop; never collect twice.", actionable=False, status="DESIGN"),
    _i("DUPLICATE_INVOICE_ID", FC.ALREADY_PAID,
       "Duplicate invoice: a payment for this order exists. Stop.",
       actionable=False, status="DESIGN"),
)

PROCESSOR_CODES: dict[str, TaxonomyEntry] = {e.code: e for e in _PROCESSOR}
ISSUES: dict[str, TaxonomyEntry] = {e.code: e for e in _ISSUES}
ALL_ENTRIES: tuple[TaxonomyEntry, ...] = _PROCESSOR + _ISSUES

#: Sandbox card-name triggers (card-testing page) -> processor code. Used by the
#: spike scripts and the simulator; listed here so the mapping lives in one place.
SANDBOX_TRIGGERS: dict[str, str] = {
    "CCREJECT-REFUSED": "0500",
    "CCREJECT-SF": "9500",
    "CCREJECT-EC": "5400",
    "CCREJECT-IRC": "5180",
    "CCREJECT-IF": "5120",
    "CCREJECT-LS": "9520",
    "CCREJECT-IA": "1330",
    "CCREJECT-BANK_ERROR": "5100",
    "CCREJECT-CVV_F": "00N7",
}


@dataclass(frozen=True, slots=True)
class Classification:
    """Result of diagnosing one decline.

    `diagnosed_by` is "rules" for a taxonomy match and "llm" for an accepted
    model proposal (see diagnosis.py). LLM-derived classifications never permit
    same-instrument retry and run under a reduced autonomy ceiling.
    """

    failure_class: FailureClass
    entry: TaxonomyEntry | None
    confident: bool
    note: str
    diagnosed_by: str = "rules"

    @property
    def retry_same_instrument(self) -> bool:
        return bool(self.diagnosed_by == "rules" and self.entry
                    and self.entry.retry_same_instrument)

    @property
    def customer_actionable(self) -> bool:
        return bool(self.entry and self.entry.customer_actionable) or (
            self.diagnosed_by == "llm" and self.confident)

    @property
    def typical_resolution_hours(self) -> float | None:
        return self.entry.typical_resolution_hours if self.entry else None


def _norm_code(code: str | None) -> str:
    return (code or "").strip().upper()


def classify(processor_response_code: str | None = None,
             issue: str | None = None) -> Classification:
    """Diagnose a decline from its PayPal signals. Processor code first, then issue."""
    code = _norm_code(processor_response_code)
    if code and (entry := PROCESSOR_CODES.get(code)):
        return Classification(entry.failure_class, entry, True,
                              f"PayPal processor response {code} {entry.name}.")

    iss = _norm_code(issue)
    if iss and (entry := ISSUES.get(iss)):
        return Classification(entry.failure_class, entry, True,
                              f"PayPal Orders issue {iss}.")

    seen = ", ".join(s for s in (f"processor={code}" if code else "",
                                 f"issue={iss}" if iss else "") if s) or "no decline signal"
    return Classification(FailureClass.UNKNOWN, None, False,
                          f"Unmapped PayPal decline ({seen}). Routed to exceptions.")


def codes_for_class(failure_class: FailureClass) -> tuple[str, ...]:
    return tuple(e.code for e in ALL_ENTRIES if e.failure_class is failure_class)
