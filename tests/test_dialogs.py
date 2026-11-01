from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, WebSocketDisconnect
from unittest.mock import AsyncMock, MagicMock

from database.models import User
from database.schemas import DialogCreate, MessageCreate
from routers.dialogs import (
    create_or_get_dialog,
    delete_dialog,
    get_messages,
    get_my_dialogs,
    mark_as_read,
    send_message,
    websocket_endpoint,
)


def person(user_id, name):
    user = User(id=user_id, name=name, age=20, password="hashed")
    return user


def stamp_saved_row(db):
    async def refresh(obj, attribute_names=None):
        if attribute_names:
            return
        if getattr(obj, "id", None) is None:
            obj.id = 7
        created = getattr(obj, "created_at", None)
        if not isinstance(created, datetime):
            obj.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if hasattr(obj, "is_read") and not isinstance(obj.is_read, bool):
            obj.is_read = False

    db.refresh.side_effect = refresh


@pytest.mark.asyncio
async def test_dialogs_list_uses_cache(monkeypatch):
    cached = [{"id": 1, "companion_name": "bob"}]
    monkeypatch.setattr(
        "routers.dialogs.get_cached_dialogs", AsyncMock(return_value=cached)
    )
    me = MagicMock()
    me.id = 1

    result = await get_my_dialogs(db=AsyncMock(), current_user=me)

    assert result == cached


@pytest.mark.asyncio
async def test_create_dialog_missing_companion():
    db = AsyncMock()
    db.get.return_value = None
    me = person(1, "lil")

    with pytest.raises(HTTPException) as exc:
        await create_or_get_dialog(DialogCreate(user_id_2=9), db, me)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_dialog_returns_existing():
    me = person(1, "lil")
    bob = person(2, "bob")
    existing = MagicMock()
    existing.id = 4
    existing.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    existing.users = [me, bob]

    lookup = MagicMock()
    lookup.scalars.return_value.all.return_value = [existing]
    last_message = MagicMock()
    last_message.scalar_one_or_none.return_value = "привет"
    db = AsyncMock()
    db.get.return_value = bob
    db.execute.side_effect = [lookup, last_message]

    dialog = await create_or_get_dialog(DialogCreate(user_id_2=2), db, me)

    assert dialog.id == 4
    assert dialog.companion_name == "bob"
    assert dialog.last_message == "привет"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_dialog_saves_new_pair(monkeypatch):
    invalidate = AsyncMock()
    monkeypatch.setattr("routers.dialogs.invalidate_dialogs_cache", invalidate)
    me = person(1, "lil")
    bob = person(2, "bob")
    lookup = MagicMock()
    lookup.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = bob
    db.execute.return_value = lookup
    stamp_saved_row(db)

    dialog = await create_or_get_dialog(DialogCreate(user_id_2=2), db, me)

    assert dialog.id == 7
    assert dialog.companion_id == 2
    assert dialog.last_message is None
    db.add.assert_called_once()
    assert invalidate.await_count == 2


@pytest.mark.asyncio
async def test_delete_dialog_forbidden_for_stranger():
    me = person(1, "lil")
    owner = person(3, "ann")
    dialog = MagicMock()
    dialog.users = [owner]
    db = AsyncMock()
    db.get.return_value = dialog

    with pytest.raises(HTTPException) as exc:
        await delete_dialog(4, db, me)

    assert exc.value.status_code == 403
    db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_dialog_drops_cache(monkeypatch):
    invalidate = AsyncMock()
    monkeypatch.setattr("routers.dialogs.invalidate_dialogs_cache", invalidate)
    me = person(1, "lil")
    bob = person(2, "bob")
    dialog = MagicMock()
    dialog.users = [me, bob]
    db = AsyncMock()
    db.get.return_value = dialog

    assert await delete_dialog(4, db, me) is None
    db.delete.assert_awaited_once_with(dialog)
    assert invalidate.await_count == 2


@pytest.mark.asyncio
async def test_send_message_requires_membership():
    me = person(1, "lil")
    dialog = MagicMock()
    dialog.users = [person(2, "bob")]
    db = AsyncMock()
    db.get.return_value = dialog

    with pytest.raises(HTTPException) as exc:
        await send_message(4, MessageCreate(text="hi"), db, me)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_send_message_publishes_to_companion(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr("routers.dialogs.publish_to_user", publish)
    monkeypatch.setattr("routers.dialogs.invalidate_dialogs_cache", AsyncMock())
    me = person(1, "lil")
    bob = person(2, "bob")
    dialog = MagicMock()
    dialog.id = 4
    dialog.users = [me, bob]
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = dialog
    stamp_saved_row(db)
    reply = {"sender_name": "bob", "text": "раньше"}

    message = await send_message(
        4,
        MessageCreate(text="ответ", reply_to=reply),
        db,
        me,
    )

    assert message.text == "ответ"
    assert message.sender_name == "lil"
    assert message.reply_to == reply
    payload = publish.await_args.args[1]
    assert payload["type"] == "new_message"
    assert payload["message"]["text"] == "ответ"
    assert publish.await_args.args[0] == bob.id


@pytest.mark.asyncio
async def test_get_messages_hides_foreign_dialog():
    me = person(1, "lil")
    dialog = MagicMock()
    dialog.users = [person(2, "bob")]
    db = AsyncMock()
    db.get.return_value = dialog

    with pytest.raises(HTTPException) as exc:
        await get_messages(4, db=db, current_user=me)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_mark_as_read_commits():
    db = AsyncMock()
    me = person(1, "lil")

    assert await mark_as_read(4, db, me) == {"status": "ok"}
    db.execute.assert_awaited()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_websocket_rejects_bad_token():
    ws = AsyncMock()

    await websocket_endpoint(ws, "not-a-jwt", AsyncMock())

    ws.close.assert_awaited_once()
    assert ws.close.await_args.kwargs["code"] == 1008


@pytest.mark.asyncio
async def test_websocket_answers_ping(monkeypatch):
    monkeypatch.setattr("routers.dialogs.listen_for_messages", AsyncMock())
    me = person(1, "lil")
    found = MagicMock()
    found.scalar_one_or_none.return_value = me
    db = AsyncMock()
    db.execute.return_value = found
    ws = AsyncMock()
    ws.receive_json.side_effect = [{"type": "ping"}, WebSocketDisconnect()]

    from auth import create_access_token

    await websocket_endpoint(ws, create_access_token({"sub": "lil"}), db)

    ws.accept.assert_awaited()
    ws.send_json.assert_any_await({"type": "pong"})
