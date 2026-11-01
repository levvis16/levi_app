import pytest
from fastapi import HTTPException

from auth import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip():
    hashed = hash_password("secret123")

    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert verify_password("other", hashed) is False


def test_token_roundtrip():
    token = create_access_token({"sub": "lil"})
    payload = decode_token(token)

    assert payload["sub"] == "lil"


def test_decode_rejects_garbage_token():
    with pytest.raises(HTTPException) as exc:
        decode_token("not-a-jwt")

    assert exc.value.status_code == 401