"""Pydantic v2 models for PRP v0.1, mirroring schemas/*.schema.json.

All models forbid unknown fields (offer rule R7: unknown fields or option kinds
make an offer invalid). Money is `StrictInt` minor units, so a float can never
be coerced in. Business rules (R1-R5) are not checked here; the merchant's
offer builder and the buyer's guard enforce them.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

PRPVersion = Literal["0.1"]

FailureClass = Literal[
    "INSUFFICIENT_FUNDS",
    "INSTRUMENT_INVALID",
    "ISSUER_DECLINED",
    "AUTH_FAILURE",
    "RISK_BLOCKED",
    "UNKNOWN",
]
OptionKind = Literal["ALTERNATE_FUNDING", "RETRY_AFTER", "PAYER_ACTION", "CANCEL"]
Outcome = Literal["RECOVERED", "RECOVERED_BY_HUMAN", "ORGANIC", "LOST", "PENDING"]
ErrorCode = Literal[
    "BAD_SIGNATURE",
    "UNKNOWN_KEY",
    "REPLAYED_NONCE",
    "CLOCK_SKEW",
    "OUTSIDE_MANDATE",
    "CONSENT_INVALID",
    "OFFER_EXPIRED",
    "OFFER_ALREADY_ACCEPTED",
    "INVALID_OPTION",
    "ALIAS_NOT_ALLOWED",
    "KILL_SWITCH_ACTIVE",
    "PAYPAL_ERROR",
]

Alias = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")]
MerchantId = Annotated[str, Field(pattern=r"^mer_[0-9a-z_]{3,40}$")]
OfferId = Annotated[str, Field(pattern=r"^off_[0-9A-Za-z]{10,40}$")]
IntentId = Annotated[str, Field(pattern=r"^pi_[0-9A-Za-z]{10,40}$")]
OptionId = Annotated[str, Field(pattern=r"^opt_[0-9a-z_]{1,32}$")]
DecisionRef = Annotated[str, Field(pattern=r"^dec_[0-9A-Za-z]{10,40}$")]
MandateId = Annotated[str, Field(pattern=r"^mdt_[0-9A-Za-z]{10,40}$")]
GuardDecisionRef = Annotated[str, Field(pattern=r"^gd_[0-9A-Za-z]{10,40}$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
PositiveMinor = Annotated[StrictInt, Field(ge=1)]


def _unique(items: list) -> list:
    if len(set(items)) != len(items):
        raise ValueError("items must be unique")
    return items


AliasList = Annotated[list[Alias], Field(min_length=1), AfterValidator(_unique)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Money(_Strict):
    currency_code: CurrencyCode
    value_minor: PositiveMinor


class Merchant(_Strict):
    id: MerchantId
    name: Annotated[str, Field(min_length=1, max_length=80)]


class PayPalFailureDetail(_Strict):
    processor_response_code: Annotated[str, Field(pattern=r"^[0-9A-Z]{4}$")] | None = None
    processor_response_name: Annotated[str, Field(pattern=r"^[A-Z0-9_]{2,64}$")] | None = None
    issue: Annotated[str, Field(pattern=r"^[A-Z0-9_]{2,64}$")] | None = None


class Failure(_Strict):
    class_: FailureClass = Field(alias="class")
    retry_same_instrument: StrictBool
    failed_funding_alias: Alias
    paypal: PayPalFailureDetail | None = None

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class AlternateFundingOption(_Strict):
    option_id: OptionId
    kind: Literal["ALTERNATE_FUNDING"]
    eligible_funding_aliases: AliasList


class RetryAfterOption(_Strict):
    option_id: OptionId
    kind: Literal["RETRY_AFTER"]
    not_before: AwareDatetime
    eligible_funding_aliases: AliasList


class PayerActionOption(_Strict):
    option_id: OptionId
    kind: Literal["PAYER_ACTION"]


class CancelOption(_Strict):
    option_id: OptionId
    kind: Literal["CANCEL"]


OfferOption = Annotated[
    Union[AlternateFundingOption, RetryAfterOption, PayerActionOption, CancelOption],
    Field(discriminator="kind"),
]


class Display(_Strict):
    """Human-readable copy from the merchant. UNTRUSTED: never a decision input (R6)."""

    untrusted: Literal[True]
    locale: Annotated[str, Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
    text: Annotated[str, Field(max_length=500)]


class RecoveryOffer(_Strict):
    prp_version: PRPVersion
    offer_id: OfferId
    intent_id: IntentId
    merchant: Merchant
    created_at: AwareDatetime
    expires_at: AwareDatetime
    amount: Money
    failure: Failure
    options: Annotated[list[OfferOption], Field(min_length=1, max_length=6)]
    decision_ref: DecisionRef
    display: Display

    def option(self, option_id: str) -> OfferOption | None:
        return next((o for o in self.options if o.option_id == option_id), None)


class Acceptance(_Strict):
    """Body of POST /agent/v1/offers/{offer_id}/accept (recovery_response.schema.json).

    `funding_alias` is required for ALTERNATE_FUNDING / RETRY_AFTER; the schema
    cannot express that (the option kind is not in this body), so the merchant
    enforces it in accept check 3.
    """

    prp_version: PRPVersion
    offer_id: OfferId
    option_id: OptionId
    funding_alias: Alias | None = None
    mandate_id: MandateId
    agent_decision_ref: GuardDecisionRef
    idempotency_key: Annotated[str, Field(min_length=8, max_length=108)]


class ErrorDetail(_Strict):
    code: ErrorCode
    message: str = ""


class PRPError(_Strict):
    prp_version: PRPVersion = "0.1"
    error: ErrorDetail


# --------------------------------------------------------------------------- #
# Mandate (mandate.schema.json)
# --------------------------------------------------------------------------- #


class Principal(_Strict):
    display_name: Annotated[str, Field(min_length=1, max_length=60)]
    paypal_payer_id: Annotated[str, Field(pattern=r"^[A-Z0-9]{8,20}$")] | None = None


class Budget(_Strict):
    period: Literal["DAY", "WEEK", "MONTH"]
    limit_minor: PositiveMinor


class FundingSource(_Strict):
    alias: Alias
    kind: Literal["CARD", "PAYPAL_WALLET"]
    priority: Annotated[StrictInt, Field(ge=1, le=5)]


class RecoveryPolicy(_Strict):
    allow_alternate_funding: StrictBool
    allow_retry_after: StrictBool
    max_autonomous_recoveries_per_purchase: Annotated[StrictInt, Field(ge=0, le=3)]
    always_escalate_classes: Annotated[list[FailureClass], AfterValidator(_unique)]

    @model_validator(mode="after")
    def _risk_blocked_always_escalates(self) -> RecoveryPolicy:
        if "RISK_BLOCKED" not in self.always_escalate_classes:
            raise ValueError("always_escalate_classes must contain RISK_BLOCKED")
        return self


class Mandate(_Strict):
    mandate_id: MandateId
    principal: Principal
    merchant_scope: Annotated[list[MerchantId], Field(min_length=1), AfterValidator(_unique)]
    currency_code: CurrencyCode
    budget: Budget
    per_purchase_cap_minor: PositiveMinor
    allowed_categories: Annotated[
        list[Annotated[str, Field(pattern=r"^[a-z0-9-]{2,40}$")]], AfterValidator(_unique)
    ]
    funding: Annotated[list[FundingSource], Field(min_length=1, max_length=5)]
    recovery: RecoveryPolicy
    approved_at: AwareDatetime | None = None
    approval_ref: Annotated[str, Field(pattern=r"^onb_[0-9A-Za-z]{10,40}$")] | None = None
    expires_at: AwareDatetime

    def funding_by_alias(self, alias: str) -> FundingSource | None:
        return next((f for f in self.funding if f.alias == alias), None)
