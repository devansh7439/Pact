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
    # Direct triggers & sandbox triggers
    _p("5120", "INSUFFICIENT_FUNDS", FC.INSUFFICIENT_FUNDS,
       "Funds short right now. Offer another funding source, or retry later.",
       resolution_hours=48.0),
    _p("5110", "INSUFFICIENT_FUNDS_DEBIT", FC.INSUFFICIENT_FUNDS,
       "Debit account has insufficient funds. Offer another funding source.",
       resolution_hours=48.0),
    _p("5130", "EXCEEDS_WITHDRAWAL_LIMIT", FC.INSUFFICIENT_FUNDS,
       "Exceeds withdrawal amount limit. Offer another funding source.",
       resolution_hours=24.0),
    _p("5190", "EXCEEDS_ACTIVITY_COUNT_LIMIT", FC.INSUFFICIENT_FUNDS,
       "Card activity count limit exceeded for period. Offer another funding source.",
       resolution_hours=24.0),
    _p("5400", "EXPIRED_CARD", FC.INSTRUMENT_INVALID,
       "Card has expired. Use another funding source."),
    _p("5140", "CARD_EXPIRED", FC.INSTRUMENT_INVALID,
       "Card expiration date passed. Offer another funding source."),
    _p("5180", "INVALID_OR_RESTRICTED_CARD", FC.INSTRUMENT_INVALID,
       "PayPal: use another card; do not retry this one."),
    _p("5210", "RESTRICTED_CARD", FC.INSTRUMENT_INVALID,
       "Card is restricted by issuer. Offer another funding source."),
    _p("1300", "INVALID_DATA_FORMAT", FC.INSTRUMENT_INVALID,
       "Invalid card data format. Offer another funding source."),
    _p("1310", "INVALID_EXPIRATION_DATE", FC.INSTRUMENT_INVALID,
       "Invalid card expiration date. Offer another funding source."),
    _p("1330", "INVALID_ACCOUNT", FC.INSTRUMENT_INVALID,
       "Account is invalid. Use another funding source."),
    _p("1340", "ACCOUNT_CLOSED", FC.INSTRUMENT_INVALID,
       "Account has been closed. Offer another funding source."),
    _p("1350", "EXPIRED_CARD_PICK_UP", FC.INSTRUMENT_INVALID,
       "Expired card status pickup. Offer another funding source.", actionable=False),
    _p("0500", "DO_NOT_HONOR", FC.ISSUER_DECLINED,
       "Issuer declined without a reason. Do not retry autonomously; offer another source."),
    _p("0100", "REFERRAL_TO_CARD_ISSUER", FC.ISSUER_DECLINED,
       "Referral to card issuer. Payer must contact their bank."),
    _p("5100", "GENERIC_DECLINE", FC.ISSUER_DECLINED,
       "Generic decline. Offer another source or a payer-approved checkout."),
    _p("5160", "TRANSACTION_NOT_PERMITTED_TO_CARDHOLDER", FC.ISSUER_DECLINED,
       "Transaction not permitted to cardholder. Offer another source."),
    _p("1370", "DISALLOWED_TRANSACTION", FC.ISSUER_DECLINED,
       "Card issuer does not permit this transaction type. Offer another source."),
    _p("5910", "ISSUER_UNAVAILABLE", FC.ISSUER_DECLINED,
       "Issuer system temporarily unavailable. Retry after backoff or offer alternate.",
       resolution_hours=2.0),
    _p("00N7", "CVV2_FAILURE_POSSIBLE_RETRY_WITH_CVV", FC.AUTH_FAILURE,
       "CVV check failed. Only the payer can fix this, by re-entering details."),
    _p("0800", "HONOR_WITH_ID", FC.AUTH_FAILURE,
       "Authentication required by card issuer with ID verification."),
    _p("1320", "INVALID_CVV2", FC.AUTH_FAILURE,
       "Card verification value invalid. Payer action required."),
    _p("1360", "PIN_TRIES_EXCEEDED", FC.AUTH_FAILURE,
       "Allowable PIN tries exceeded. Payer re-authentication required."),
    _p("1380", "CRYPTOGRAPHIC_FAILURE", FC.AUTH_FAILURE,
       "Cryptographic chip or token verification failure. Payer re-entry required."),
    _p("1390", "CARD_AUTHENTICATION_FAILED", FC.AUTH_FAILURE,
       "Card authentication failed (3DS/SCA). Payer action required."),
    _p("5150", "PIN_INCORRECT", FC.AUTH_FAILURE,
       "PIN or security token incorrect. Payer action required."),
    _p("9500", "SUSPECTED_FRAUD", FC.RISK_BLOCKED,
       "PayPal: use another card; do not retry this one. Payer re-authentication only.",
       actionable=False),
    _p("9510", "SECURITY_VIOLATION", FC.RISK_BLOCKED,
       "Security violation detected on card instrument. Payer re-authentication only.",
       actionable=False),
    _p("9520", "LOST_OR_STOLEN", FC.RISK_BLOCKED,
       "PayPal: use another card; do not retry this one. Payer re-authentication only.",
       actionable=False),
    _p("9530", "STOLEN_CARD_PICK_UP", FC.RISK_BLOCKED,
       "Reported stolen card. Autonomous retry strictly forbidden.",
       actionable=False),
    _p("9540", "COUNTERFEIT_CARD", FC.RISK_BLOCKED,
       "Counterfeit card indicator. Never retry.",
       actionable=False),
    _p("5170", "TRANSACTION_NOT_PERMITTED_TO_TERMINAL", FC.MERCHANT_CONFIG,
       "Merchant terminal not permitted for this transaction type. Ops review.",
       actionable=False),
    _p("5920", "SYSTEM_ERROR", FC.MERCHANT_CONFIG,
       "Payment processor system error. Ops review.",
       actionable=False),
    _p("9600", "PROCESSOR_UNAVAILABLE", FC.MERCHANT_CONFIG,
       "Payment network processor unavailable. Ops review.",
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
       "Payer cannot pay with this source. Offer another.", status="VERIFIED"),
    _i("COMPLIANCE_VIOLATION", FC.RISK_BLOCKED,
       "Blocked for compliance. Never retried; payer or review only.",
       actionable=False, status="VERIFIED"),
    _i("PAYEE_ACCOUNT_RESTRICTED", FC.MERCHANT_CONFIG,
       "Our PayPal account is restricted. Ops must fix this; never contact the customer.",
       actionable=False, status="VERIFIED"),
    _i("PAYEE_ACCOUNT_LOCKED_OR_CLOSED", FC.MERCHANT_CONFIG,
       "Our PayPal account is locked or closed. Ops must fix this.",
       actionable=False, status="VERIFIED"),
    _i("ORDER_ALREADY_CAPTURED", FC.ALREADY_PAID,
       "Already captured. Stop; never collect twice.", actionable=False, status="VERIFIED"),
    _i("DUPLICATE_INVOICE_ID", FC.ALREADY_PAID,
       "Duplicate invoice: a payment for this order exists. Stop.",
       actionable=False, status="VERIFIED"),
    _i("AGREEMENT_ALREADY_CANCELLED", FC.INSTRUMENT_INVALID,
       "Billing agreement or mandate was cancelled. Request new agreement.",
       actionable=True, status="VERIFIED"),
    _i("CARD_TYPE_UNSUPPORTED", FC.INSTRUMENT_INVALID,
       "Card type unsupported by merchant or region. Offer alternate source.",
       actionable=True, status="VERIFIED"),
    _i("CURRENCY_NOT_ALLOWED_FOR_CARD", FC.INSTRUMENT_INVALID,
       "Card does not support this transaction currency. Offer alternate source.",
       actionable=True, status="VERIFIED"),
    _i("DOMESTIC_TRANSACTION_REQUIRED", FC.ISSUER_DECLINED,
       "Card requires domestic processing. Offer another funding source.",
       actionable=True, status="VERIFIED"),
    _i("INSUFFICIENT_FUNDS", FC.INSUFFICIENT_FUNDS,
       "Instrument has insufficient funds. Offer alternate source or retry after funds deposit.",
       actionable=True, status="VERIFIED"),
    _i("INVALID_SECURITY_CODE", FC.AUTH_FAILURE,
       "Security code invalid. Payer must verify details.",
       actionable=True, status="VERIFIED"),
    _i("MAX_NUMBER_OF_PAYMENT_ATTEMPTS_EXCEEDED", FC.RISK_BLOCKED,
       "Exceeded maximum payment attempts. Payer verification required.",
       actionable=False, status="VERIFIED"),
    _i("REDIRECT_PAYER_FOR_ALTERNATE_FUNDING", FC.INSUFFICIENT_FUNDS,
       "PayPal requested payer redirect for alternate funding. Offer alternate wallet.",
       actionable=True, status="VERIFIED"),
    _i("TRANSACTION_LIMIT_EXCEEDED", FC.INSUFFICIENT_FUNDS,
       "PayPal account or card transaction limit exceeded. Offer alternate source.",
       actionable=True, status="VERIFIED"),
    _i("PAYMENT_SOURCE_CANNOT_BE_USED", FC.INSTRUMENT_INVALID,
       "Payment source cannot be used for this transaction. Offer alternate source.",
       actionable=True, status="VERIFIED"),
    _i("PAYMENT_SOURCE_INFO_CANNOT_BE_VERIFIED", FC.AUTH_FAILURE,
       "Payment source information could not be verified. Payer authentication required.",
       actionable=True, status="VERIFIED"),
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
