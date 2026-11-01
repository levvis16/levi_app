import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock

from auth import hash_password
from database.schemas import UserCreate
from routers.user import (
    ADMIN_USERNAME,
    create_user,
    delete_user,
    get_one_user,
    login_user,
    register_user,
)


def user_payload(name="lil", age=20, password="secret"):
    return UserCreate(name=name, age=age, password=password)


def test_age_must_be_in_range():
    with pytest.raises(ValidationError):
        user_payload(age=15)
    with pytest.raises(ValidationError):
        user_payload(age=116)


def db_with_lookup(found):
    result = MagicMock()
    result.scalar_one_or_none.return_value = found
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_register_saves_hashed_password():
    db = db_with_lookup(None)

    async def refresh(obj):
        obj.id = 1

    db.refresh.side_effect = refresh

    created = await register_user(user_payload(), db)

    assert created.id == 1
    assert created.name == "lil"
    assert created.password != "secret"
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_register_rejects_duplicate_name():
    db = db_with_lookup(MagicMock())

    with pytest.raises(HTTPException) as exc:
        await register_user(user_payload(), db)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Username already registered"


@pytest.mark.asyncio
async def test_create_user_conflict_is_409():
    db = db_with_lookup(MagicMock())

    with pytest.raises(HTTPException) as exc:
        await create_user(user_payload(), db)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_login_returns_bearer_token():
    stored = MagicMock()
    stored.name = "lil"
    stored.password = hash_password("secret")
    form = MagicMock()
    form.username = "lil"
    form.password = "secret"

    data = await login_user(form_data=form, db=db_with_lookup(stored))

    assert data["token_type"] == "bearer"
    assert data["access_token"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password():
    stored = MagicMock()
    stored.name = "lil"
    stored.password = hash_password("secret")
    form = MagicMock()
    form.username = "lil"
    form.password = "nope"

    with pytest.raises(HTTPException) as exc:
        await login_user(form_data=form, db=db_with_lookup(stored))

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_missing_user_is_404():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await get_one_user(5, db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_user_is_admin_only():
    stranger = MagicMock()
    stranger.name = "lil"

    with pytest.raises(HTTPException) as exc:
        await delete_user(2, current_user=stranger, db=AsyncMock())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_delete_missing_user_is_404():
    admin = MagicMock()
    admin.name = ADMIN_USERNAME
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await delete_user(2, current_user=admin, db=db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_deletes_user():
    admin = MagicMock()
    admin.name = ADMIN_USERNAME
    victim = MagicMock()
    db = AsyncMock()
    db.get.return_value = victim

    assert await delete_user(2, current_user=admin, db=db) is None
    db.delete.assert_awaited_once_with(victim)
    db.commit.assert_awaited()