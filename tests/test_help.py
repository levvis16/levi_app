from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from database.models import Dialog, Message, User
from routers.broker import HelpReply, help_command, router, save_support_reply
from telegram_app.help_text import build_help_reply, format_help_message, parse_help_meta


def person(user_id, name):
    return User(id=user_id, name=name, age=20, password="hashed")


def support_result(user):
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    return result


def dialogs_result(dialogs):
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = dialogs
    return result


def stamp_message(db):
    async def refresh(obj, attribute_names=None):
        if attribute_names:
            return
        if isinstance(obj, Message):
            if obj.id is None:
                obj.id = 15
            obj.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            obj.is_read = False

    db.refresh.side_effect = refresh


@pytest.mark.asyncio
async def test_help_publishes_ticket(monkeypatch):
    publish_queue = AsyncMock()
    publish_user = AsyncMock()
    monkeypatch.setattr(router.broker, "publish", publish_queue)
    monkeypatch.setattr("routers.broker.publish_to_user", publish_user)
    monkeypatch.setattr("routers.broker.invalidate_dialogs_cache", AsyncMock())

    me = person(1, "lil")
    support = person(2, "support")
    db = AsyncMock()
    db.add = MagicMock()

    async def flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, Dialog) and obj.id is None:
                obj.id = 8

    db.flush.side_effect = flush
    db.execute.side_effect = [support_result(support), dialogs_result([])]
    stamp_message(db)

    result = await help_command("lil", "не открывается чат", user=me, db=db)

    assert result == {"data": "ok", "ticket_id": 15, "dialog_id": 8}
    payload = publish_queue.await_args.args[0]
    assert payload == {
        "ticket_id": 15,
        "user_id": 1,
        "dialog_id": 8,
        "user_name": "lil",
        "text": "не открывается чат",
    }
    assert publish_queue.await_args.kwargs["queue"] == "help"
    assert publish_user.await_args.args[0] == support.id
    assert publish_user.await_args.args[1]["message"]["text"] == "не открывается чат"


@pytest.mark.asyncio
async def test_help_requires_support_user(monkeypatch):
    publish_queue = AsyncMock()
    monkeypatch.setattr(router.broker, "publish", publish_queue)
    db = AsyncMock()
    db.execute.return_value = support_result(None)

    with pytest.raises(HTTPException) as exc:
        await help_command("lil", "не открывается чат", user=person(1, "lil"), db=db)

    assert exc.value.status_code == 503
    publish_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_help_reuses_existing_dialog(monkeypatch):
    monkeypatch.setattr(router.broker, "publish", AsyncMock())
    monkeypatch.setattr("routers.broker.publish_to_user", AsyncMock())
    monkeypatch.setattr("routers.broker.invalidate_dialogs_cache", AsyncMock())

    me = person(1, "lil")
    support = person(2, "support")
    existing = MagicMock()
    existing.id = 4
    existing.users = [me, support]
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [support_result(support), dialogs_result([existing])]
    stamp_message(db)

    result = await help_command("lil", "ещё вопрос", user=me, db=db)

    assert result["dialog_id"] == 4
    assert isinstance(db.add.call_args.args[0], Message)
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_support_reply_publishes_to_user(monkeypatch):
    publish_user = AsyncMock()
    monkeypatch.setattr("routers.broker.publish_to_user", publish_user)
    monkeypatch.setattr("routers.broker.invalidate_dialogs_cache", AsyncMock())

    support = person(2, "support")
    dialog = MagicMock()
    dialog.id = 8
    dialog.users = [person(1, "lil"), support]
    ticket = MagicMock()
    ticket.dialog_id = 8
    ticket.sender_id = 1
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = support_result(support)
    db.get.side_effect = [dialog, ticket]
    stamp_message(db)

    answer = await save_support_reply(
        db,
        HelpReply(ticket_id=15, user_id=1, dialog_id=8, text="  попробуй обновить страницу  "),
    )

    assert answer.text == "попробуй обновить страницу"
    assert answer.sender_id == support.id
    assert publish_user.await_args.args[0] == 1
    event = publish_user.await_args.args[1]
    assert event["type"] == "new_message"
    assert event["dialog_id"] == 8
    assert event["message"]["sender_name"] == "support"


@pytest.mark.asyncio
async def test_support_reply_rejects_foreign_ticket(monkeypatch):
    publish_user = AsyncMock()
    monkeypatch.setattr("routers.broker.publish_to_user", publish_user)

    support = person(2, "support")
    dialog = MagicMock()
    dialog.id = 8
    dialog.users = [person(1, "lil"), support]
    ticket = MagicMock()
    ticket.dialog_id = 8
    ticket.sender_id = 99
    db = AsyncMock()
    db.execute.return_value = support_result(support)
    db.get.side_effect = [dialog, ticket]

    answer = await save_support_reply(
        db,
        HelpReply(ticket_id=15, user_id=1, dialog_id=8, text="чужой ответ"),
    )

    assert answer is None
    db.commit.assert_not_awaited()
    publish_user.assert_not_awaited()


def test_help_message_roundtrip():
    payload = {
        "ticket_id": 15,
        "user_id": 1,
        "dialog_id": 8,
        "user_name": "lil",
        "text": "не открывается чат",
    }

    text = format_help_message(payload)

    assert parse_help_meta(text) == {"ticket_id": 15, "user_id": 1, "dialog_id": 8}
    assert build_help_reply(text, " обнови страницу ") == {
        "ticket_id": 15,
        "user_id": 1,
        "dialog_id": 8,
        "text": "обнови страницу",
    }
    assert build_help_reply("обычное сообщение", "ответ") is None
    assert build_help_reply(text, "   ") is None
