"""Doc 08 invariants on the buyer side and in shared PRP signing (hypothesis)."""

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from buyer_agent import fixtures as fx
from buyer_agent.guard import GuardInput, guard
from shared.prp import keys, signing
from shared.prp.signing import MemoryNonceStore, PRPAuthError

NOW = fx.T0 + timedelta(minutes=1)
ALIASES = ["primary-card", "paypal-wallet", "backup-card", "stranger-card"]
CLASSES = ["INSUFFICIENT_FUNDS", "INSTRUMENT_INVALID", "ISSUER_DECLINED", "AUTH_FAILURE", "RISK_BLOCKED", "UNKNOWN"]

# Fixed keys: hypothesis replays examples, and keygen per example is wasteful.
MER_KEY = keys.generate()
AGT_KEY = keys.generate()
MER_KID, AGT_KID = "mer_kettle_crumb#k1", "agt_maya#k1"
RESOLVE = {MER_KID: MER_KEY.public_key(), AGT_KID: AGT_KEY.public_key()}.get


@st.composite
def options(draw):
    out = []
    for i in range(draw(st.integers(1, 6))):
        kind = draw(st.sampled_from(["ALTERNATE_FUNDING", "RETRY_AFTER", "PAYER_ACTION", "CANCEL"]))
        opt = {"option_id": f"opt_{i}", "kind": kind}
        if kind in ("ALTERNATE_FUNDING", "RETRY_AFTER"):
            opt["eligible_funding_aliases"] = draw(st.lists(st.sampled_from(ALIASES), min_size=1, max_size=3, unique=True))
        if kind == "RETRY_AFTER":
            opt["not_before"] = "2026-11-20T10:20:00Z"
        out.append(opt)
    return out


@st.composite
def scenarios(draw):
    amount = draw(st.integers(1, 20_000))
    failed = draw(st.sampled_from(ALIASES))
    earlier = frozenset(draw(st.lists(st.sampled_from(ALIASES), max_size=2)))
    offer = fx.s1_offer(
        amount={"value_minor": amount},
        failure={
            "class": draw(st.sampled_from(CLASSES)),
            "retry_same_instrument": draw(st.booleans()),
            "failed_funding_alias": failed,
        },
        options=draw(options()),
    )
    mandate = fx.maya_mandate(
        budget={"limit_minor": draw(st.integers(1, 20_000))},
        per_purchase_cap_minor=draw(st.integers(1, 20_000)),
        recovery={
            "allow_alternate_funding": draw(st.booleans()),
            "allow_retry_after": draw(st.booleans()),
            "max_autonomous_recoveries_per_purchase": draw(st.integers(0, 3)),
        },
    )
    inp = GuardInput(
        offer=offer,
        signature_ok=True,
        mandate=mandate,
        purchase=fx.purchase(amount_minor=amount, funding_alias=failed,
                             autonomous_recoveries=draw(st.integers(0, 3)),
                             failed_aliases=earlier | {failed}),
        spent_this_period_minor=draw(st.integers(0, 20_000)),
        now=NOW,
        paused=draw(st.booleans()),
    )
    return inp


@settings(max_examples=400, deadline=None)
@given(scenarios())
def test_guard_respects_budget(inp):  # I5
    r = guard(inp)
    if r.decision == "ACCEPT":
        amt = inp.purchase.amount_minor
        m = inp.mandate
        assert amt <= m.per_purchase_cap_minor
        assert amt <= m.budget.limit_minor - inp.spent_this_period_minor
        assert inp.purchase.autonomous_recoveries < m.recovery.max_autonomous_recoveries_per_purchase
        assert not inp.paused


@settings(max_examples=400, deadline=None)
@given(scenarios())
def test_guard_never_accepts_failed_alias_or_risk(inp):  # buyer side of I2 / I3
    r = guard(inp)
    if r.decision == "ACCEPT":
        f = inp.offer["failure"]
        assert f["class"] not in inp.mandate.recovery.always_escalate_classes
        assert f["class"] != "RISK_BLOCKED"
        if not f["retry_same_instrument"]:
            assert r.alias not in inp.purchase.failed_aliases
        else:
            assert r.alias not in inp.purchase.failed_aliases - {f["failed_funding_alias"]}
        assert inp.mandate.funding_by_alias(r.alias) is not None


@settings(max_examples=300, deadline=None)
@given(scenarios(), st.text(max_size=500))
def test_guard_ignores_prose(inp, text):  # I6
    base = guard(inp)
    offer = dict(inp.offer, display=dict(inp.offer["display"], text=text))
    other = guard(GuardInput(**{**inp.__dict__, "offer": offer}))
    assert other == base


@st.composite
def faults(draw):
    return draw(st.sampled_from(["body", "path", "method", "ts", "nonce", "sig", "kid", "replay", "key"]))


@settings(max_examples=200, deadline=None)
@given(faults(), st.integers(0, 10_000))
def test_bad_signature_rejected(fault, amount):  # I7
    now = 1_763_030_400
    body = fx.s1_offer(amount={"value_minor": amount + 1})
    path = "/agent/v1/checkout"
    key = AGT_KEY if fault == "key" else MER_KEY
    msg = signing.sign(key, MER_KID, "POST", path, body, timestamp=now)
    headers, raw, v_path, v_method, v_now = dict(msg.headers), msg.body, path, "POST", now
    store = MemoryNonceStore()
    if fault == "body":
        raw = raw.replace(b'"value_minor":', b'"value_minor":9')
    elif fault == "path":
        v_path = "/agent/v1/offers/off_x/accept"
    elif fault == "method":
        v_method = "PUT"
    elif fault == "ts":
        v_now = now + 301
    elif fault == "nonce":
        headers[signing.H_NONCE] = "different"
    elif fault == "sig":
        headers[signing.H_SIGNATURE] = "v1=" + keys.b64u_encode(b"\x00" * 64)
    elif fault == "kid":
        headers[signing.H_KEY_ID] = "mer_unknown#k1"
    elif fault == "replay":
        signing.verify(headers, v_method, v_path, raw, RESOLVE, store, now=v_now)

    try:
        signing.verify(headers, v_method, v_path, raw, RESOLVE, store, now=v_now)
        sig_ok = True
    except PRPAuthError:
        sig_ok = False
    assert not sig_ok

    r = guard(GuardInput(offer=None, signature_ok=sig_ok, mandate=fx.maya_mandate(),
                         purchase=fx.purchase(), spent_this_period_minor=0, now=NOW))
    assert (r.decision, r.rule_fired) == ("REJECT", "G1")


@settings(max_examples=100, deadline=None)
@given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(), max_size=5))
def test_keys_not_interchangeable(body):  # I17
    for signer, claimed in ((AGT_KEY, MER_KID), (MER_KEY, AGT_KID)):
        msg = signing.sign(signer, claimed, "POST", "/x", body, timestamp=1_000)
        try:
            signing.verify(msg.headers, "POST", "/x", msg.body, RESOLVE, MemoryNonceStore(), now=1_000)
            raise AssertionError("cross-party signature verified")
        except PRPAuthError as e:
            assert e.code == "BAD_SIGNATURE"


@settings(max_examples=100, deadline=None)
@given(st.sampled_from(["accept", "decline"]), st.sampled_from(["GET", "POST", "PUT"]))
def test_signature_binds_route(signed_action, other_method):  # I18
    other_action = "accept" if signed_action == "decline" else "decline"
    msg = signing.sign(AGT_KEY, AGT_KID, "POST", f"/agent/v1/offers/off_X/{signed_action}", {"a": 1}, timestamp=1_000)
    for method, path in (("POST", f"/agent/v1/offers/off_X/{other_action}"),
                         (other_method if other_method != "POST" else "PUT", f"/agent/v1/offers/off_X/{signed_action}")):
        try:
            signing.verify(msg.headers, method, path, msg.body, RESOLVE, MemoryNonceStore(), now=1_000)
            raise AssertionError("signature verified on a different route")
        except PRPAuthError as e:
            assert e.code == "BAD_SIGNATURE"
