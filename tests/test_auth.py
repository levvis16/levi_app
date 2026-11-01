import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock
from auth import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
    get_current_user
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


def fake_db(user):
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_returns_user_for_valid_token():
    user = MagicMock(id=1, name="lil")
    token = create_access_token({"sub": "lil"})
    current = await get_current_user(token=token, db=fake_db(user))
    assert current is user

@pytest.mark.asyncio
async def test_missing_user_is_401():
    token = create_access_token({"sub": "lil"})
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token, db=fake_db(None))
    assert exc.value.status_code == 401
    assert exc.value.detail == "User not found"