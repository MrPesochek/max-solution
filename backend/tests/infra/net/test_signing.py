from app.infra.net.signing import sign_webhook, verify_webhook_signature


def test_sign_format() -> None:
    sig = sign_webhook(b"secret", 1700000000, b'{"a":1}')
    assert sig.startswith("sha256=")
    assert len(sig) == len("sha256=") + 64


def test_verify_roundtrip() -> None:
    secret = b"secret"
    ts = 1700000000
    body = b'{"a":1}'
    sig = sign_webhook(secret, ts, body)
    assert verify_webhook_signature(secret, ts, body, sig, max_age_seconds=300, now=ts + 10)


def test_verify_rejects_wrong_secret() -> None:
    ts = 1700000000
    body = b"payload"
    sig = sign_webhook(b"secret-a", ts, body)
    assert not verify_webhook_signature(b"secret-b", ts, body, sig, max_age_seconds=300, now=ts)


def test_verify_rejects_tampered_body() -> None:
    secret = b"secret"
    ts = 1700000000
    sig = sign_webhook(secret, ts, b"original")
    assert not verify_webhook_signature(secret, ts, b"tampered", sig, max_age_seconds=300, now=ts)


def test_verify_rejects_stale_timestamp() -> None:
    secret = b"secret"
    ts = 1700000000
    body = b"payload"
    sig = sign_webhook(secret, ts, body)
    assert not verify_webhook_signature(secret, ts, body, sig, max_age_seconds=60, now=ts + 61)


def test_verify_rejects_future_timestamp_beyond_skew() -> None:
    secret = b"secret"
    ts = 1700000000
    body = b"payload"
    sig = sign_webhook(secret, ts, body)
    assert not verify_webhook_signature(secret, ts, body, sig, max_age_seconds=60, now=ts - 61)
