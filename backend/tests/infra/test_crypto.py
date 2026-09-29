import base64

import pytest
from cryptography.fernet import Fernet

from app.infra.crypto import (
    SecretBox,
    SecretBoxError,
    constant_time_equals,
    generate_token,
    hash_token,
    token_prefix,
)


def test_hash_token_is_sha256_and_deterministic() -> None:
    h1 = hash_token("abc")
    h2 = hash_token("abc")
    assert h1 == h2
    assert len(h1) == 32
    assert hash_token("abd") != h1


def test_generate_token_is_urlsafe_without_padding_and_unique() -> None:
    t1 = generate_token()
    t2 = generate_token()
    assert t1 != t2
    assert "=" not in t1
    assert all(c not in t1 for c in "+/")
    assert len(t1) == 43


def test_generate_token_respects_nbytes() -> None:
    token = generate_token(nbytes=16)
    decoded = base64.urlsafe_b64decode(token + "==")
    assert len(decoded) == 16


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc")
    assert constant_time_equals(b"abc", b"abc")
    assert not constant_time_equals("abc", "abd")
    assert not constant_time_equals("abc", "abcd")


def test_secret_box_encrypt_decrypt_roundtrip() -> None:
    key = Fernet.generate_key().decode()
    box = SecretBox(key)
    ciphertext = box.encrypt(b"top secret")
    assert box.decrypt(ciphertext) == b"top secret"
    assert ciphertext != b"top secret"


def test_secret_box_requires_key() -> None:
    with pytest.raises(SecretBoxError):
        SecretBox("")
    with pytest.raises(SecretBoxError):
        SecretBox(None)


def test_secret_box_rejects_malformed_key() -> None:
    with pytest.raises(SecretBoxError):
        SecretBox("not-a-valid-fernet-key")


def test_secret_box_wrong_key_fails_to_decrypt() -> None:
    box1 = SecretBox(Fernet.generate_key().decode())
    box2 = SecretBox(Fernet.generate_key().decode())
    ciphertext = box1.encrypt(b"data")
    with pytest.raises(SecretBoxError):
        box2.decrypt(ciphertext)


def test_secret_box_rotation_keeps_old_ciphertexts_readable() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_ciphertext = SecretBox(old_key).encrypt(b"data")

    box = SecretBox(f"{new_key}, {old_key}")
    assert box.decrypt(old_ciphertext) == b"data"
    assert SecretBox(new_key).decrypt(box.encrypt(b"fresh")) == b"fresh"
    assert SecretBox(new_key).decrypt(box.rotate(old_ciphertext)) == b"data"


def test_token_prefix_does_not_reveal_token() -> None:
    token = generate_token()
    assert token_prefix(token) == hash_token(token).hex()[:8]
    assert token_prefix(token) != token[:8]
