from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from database.models import Group, Message, User
from database.schemas import GroupCreate, MessageCreate
from routers.group import (
    add_user_to_group,
    create_group,
    get_group,
    get_group_messages,
    remove_user_from_group,
    send_group_message,
)


def person(user_id, name):
    return User(id=user_id, name=name, age=20, password="hashed")


@pytest.mark.asyncio
async def test_create_group_adds_author():
    db = AsyncMock()
    db.add = MagicMock()

    async def refresh(obj):
        obj.id = 3

    db.refresh.side_effect = refresh
    me = person(1, "lil")

    group = await create_group(GroupCreate(name="room", description="чат"), db, me)

    assert group.id == 3
    assert group.name == "room"
    db.add.assert_called_once()
    assert db.commit.await_count == 2
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_missing_group_is_404():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await get_group(8, db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_user_missing_group():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await add_user_to_group(1, 2, db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Group not found"


@pytest.mark.asyncio
async def test_add_user_missing_user():
    db = AsyncMock()
    db.get.side_effect = [Group(id=1, name="room", description=""), None]

    with pytest.raises(HTTPException) as exc:
        await add_user_to_group(1, 2, db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "User not found"


@pytest.mark.asyncio
async def test_remove_user_from_group():
    db = AsyncMock()
    db.get.side_effect = [
        Group(id=1, name="room", description=""),
        person(2, "bob"),
    ]

    assert await remove_user_from_group(1, 2, db) == {"status": "ok"}
    db.execute.assert_awaited()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_group_messages_include_sender_name():
    me = person(1, "lil")
    bob = person(2, "bob")
    message = Message(
        id=9,
        group_id=1,
        sender_id=2,
        text="всем привет",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_read=False,
        attachments=[],
    )
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [message]
    db = AsyncMock()
    db.get.side_effect = [Group(id=1, name="room", description=""), bob]
    db.execute.return_value = rows

    messages = await get_group_messages(1, db=db, current_user=me)

    assert messages[0].text == "всем привет"
    assert messages[0].sender_name == "bob"


@pytest.mark.asyncio
async def test_send_group_message_notifies_others(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr("routers.group.publish_to_user", publish)
    me = person(1, "lil")
    bob = person(2, "bob")
    members = MagicMock()
    members.scalars.return_value.all.return_value = [me, bob]
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = Group(id=1, name="room", description="")
    db.execute.return_value = members

    async def refresh(obj):
        obj.id = 15
        obj.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        obj.attachments = obj.attachments or []
        obj.is_read = False

    db.refresh.side_effect = refresh

    saved = await send_group_message(1, MessageCreate(text="внутри"), db, me)

    assert saved.text == "внутри"
    assert saved.sender_id == me.id
    publish.assert_awaited_once()
    assert publish.await_args.args[0] == bob.id
    assert publish.await_args.args[1]["type"] == "new_group_message"


@pytest.mark.asyncio
async def test_send_group_message_missing_group():
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await send_group_message(1, MessageCreate(text="нет"), db, person(1, "lil"))

    assert exc.value.status_code == 404
