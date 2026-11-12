import pytest

from shared.prp import keys, signing
from shared.prp.signing import MemoryNonceStore, PRPAuthError

NOW = 1_763_030_400
MER = "mer_kettle_crumb#k1"


@pytest.fixture
def mer_key():
    return keys.generate()


def resolver(*pairs):
    table = {kid: priv.public_key() for kid, priv in pairs}
    return table.get


def _sign(priv, body, *, kid=MER, method="POST", path="/agent/v1/checkout", ts=NOW, nonce=None):
    return signing.sign(priv, kid, method, path, body, timestamp=ts, nonce=nonce)


def _verify(msg, resolve, *, method="POST", path="/agent/v1/checkout", now=NOW, nonces=None):
    return signing.verify(
        msg.headers, method, path, msg.body, resolve, nonces or MemoryNonceStore(), now=now
    )


def test_roundtrip(mer_key):
    body = {"b": 1, "a": {"z": "é", "y": [1, 2]}}
    msg = _sign(mer_key, body)
    assert msg.body == b'{"a":{"y":[1,2],"z":"\xc3\xa9"},"b":1}'
    v = _verify(msg, resolver((MER, mer_key)))
    assert v.body == body and v.raw == msg.body and v.key_id == MER


def test_empty_body_roundtrip(mer_key):
    msg = _sign(mer_key, None, method="GET", path="/agent/v1/offers/off_x")
    assert msg.body == b"" and "Content-Type" not in msg.headers
    v = _verify(msg, resolver((MER, mer_key)), method="GET", path="/agent/v1/offers/off_x")
    assert v.body is None


def test_floats_refused_at_sign_time(mer_key):
    with pytest.raises(TypeError):
        _sign(mer_key, {"amount": 32.0})


def test_unknown_key(mer_key):
    with pytest.raises(PRPAuthError) as e:
        _verify(_sign(mer_key, {"a": 1}), resolver())
    assert e.value.code == "UNKNOWN_KEY"


@pytest.mark.parametrize("skew", [301, -301, 10_000])
def test_clock_skew(mer_key, skew):
    msg = _sign(mer_key, {"a": 1}, ts=NOW - skew)
    with pytest.raises(PRPAuthError) as e:
        _verify(msg, resolver((MER, mer_key)))
    assert e.value.code == "CLOCK_SKEW"


def test_skew_boundary_accepted(mer_key):
    _verify(_sign(mer_key, {"a": 1}, ts=NOW - 300), resolver((MER, mer_key)))


def test_replayed_nonce(mer_key):
    store = MemoryNonceStore()
    msg = _sign(mer_key, {"a": 1})
    r = resolver((MER, mer_key))
    _verify(msg, r, nonces=store)
    with pytest.raises(PRPAuthError) as e:
        _verify(msg, r, nonces=store, now=NOW + 60)
    assert e.value.code == "REPLAYED_NONCE"


def test_nonce_expires_after_ttl_but_skew_still_blocks(mer_key):
    store = MemoryNonceStore()
    msg = _sign(mer_key, {"a": 1})
    r = resolver((MER, mer_key))
    _verify(msg, r, nonces=store)
    # After 10 min the nonce is forgotten, but the timestamp is far outside skew.
    with pytest.raises(PRPAuthError) as e:
        _verify(msg, r, nonces=store, now=NOW + 601)
    assert e.value.code == "CLOCK_SKEW"


def test_forged_request_does_not_burn_nonce(mer_key):
    store = MemoryNonceStore()
    r = resolver((MER, mer_key))
    good = _sign(mer_key, {"a": 1}, nonce="n-1")
    forged = signing.SignedMessage(headers=dict(good.headers), body=b'{"a":2}')
    with pytest.raises(PRPAuthError):
        _verify(forged, r, nonces=store)
    _verify(good, r, nonces=store)  # still accepted


def test_tampered_body(mer_key):
    msg = _sign(mer_key, {"amount": {"value_minor": 3200}})
    bad = signing.SignedMessage(msg.headers, msg.body.replace(b"3200", b"9999"))
    with pytest.raises(PRPAuthError) as e:
        _verify(bad, resolver((MER, mer_key)))
    assert e.value.code == "BAD_SIGNATURE"


def test_signature_binds_route(mer_key):
    msg = _sign(mer_key, {"a": 1}, path="/agent/v1/offers/off_X/decline")
    with pytest.raises(PRPAuthError) as e:
        _verify(msg, resolver((MER, mer_key)), path="/agent/v1/offers/off_X/accept")
    assert e.value.code == "BAD_SIGNATURE"
    with pytest.raises(PRPAuthError):
        _verify(msg, resolver((MER, mer_key)), method="PUT", path="/agent/v1/offers/off_X/decline")


def test_keys_not_interchangeable(mer_key):
    agent_key = keys.generate()
    msg = _sign(agent_key, {"a": 1}, kid=MER)  # agent claims to be the merchant
    with pytest.raises(PRPAuthError) as e:
        _verify(msg, resolver((MER, mer_key), ("agt_maya#k1", agent_key)))
    assert e.value.code == "BAD_SIGNATURE"


def test_non_canonical_body_rejected(mer_key):
    # Validly signed, but bytes aren't canonical (whitespace) -> rejected.
    raw = b'{"a": 1}'
    ts, nonce = NOW, "n-2"
    sig = mer_key.sign(signing.signing_input("POST", "/p", ts, nonce, raw))
    headers = {
        "prp-key-id": MER,
        "prp-timestamp": str(ts),
        "prp-nonce": nonce,
        "prp-signature": "v1=" + keys.b64u_encode(sig),
    }
    with pytest.raises(PRPAuthError) as e:
        signing.verify(headers, "POST", "/p", raw, resolver((MER, mer_key)), MemoryNonceStore(), now=NOW)
    assert e.value.code == "BAD_SIGNATURE"


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":1.5}', b'{"a":NaN}', b"\xff"])
def test_parse_canonical_rejects(raw):
    with pytest.raises(PRPAuthError):
        signing.parse_canonical(raw)


def test_missing_header(mer_key):
    msg = _sign(mer_key, {"a": 1})
    headers = {k: v for k, v in msg.headers.items() if k != signing.H_SIGNATURE}
    with pytest.raises(PRPAuthError) as e:
        signing.verify(headers, "POST", "/agent/v1/checkout", msg.body, resolver((MER, mer_key)), MemoryNonceStore(), now=NOW)
    assert e.value.code == "BAD_SIGNATURE"


def test_key_serialisation_roundtrip(mer_key):
    pub = mer_key.public_key()
    assert keys.public_to_b64(keys.public_from_b64(keys.public_to_b64(pub))) == keys.public_to_b64(pub)
    priv2 = keys.private_from_b64(keys.private_to_b64(mer_key))
    assert keys.fingerprint(priv2.public_key()) == keys.fingerprint(pub)
    assert keys.key_id("agt_maya", 2) == "agt_maya#k2"
