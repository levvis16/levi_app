import logging
import os

from fastapi import Depends, HTTPException, status
from faststream.rabbit.fastapi import RabbitRouter
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_user
from database.models import Dialog, Message, User
from database.session import async_session, get_db
from realtime import invalidate_dialogs_cache, publish_to_user

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support")
HELP_QUEUE = "help"
HELP_REPLY_QUEUE = "help.reply"

router = RabbitRouter(RABBITMQ_URL, tags=["help"])


class HelpReply(BaseModel):
    ticket_id: int
    user_id: int
    dialog_id: int
    text: str


def message_event(dialog_id: int, message: Message, sender_name: str) -> dict:
    created_at = message.created_at
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    return {
        "type": "new_message",
        "dialog_id": dialog_id,
        "message": {
            "id": message.id,
            "dialog_id": dialog_id,
            "sender_id": message.sender_id,
            "sender_name": sender_name,
            "text": message.text,
            "created_at": created_at,
            "is_read": bool(message.is_read),
            "attachments": message.attachments or [],
            "reply_to": message.reply_to,
        },
    }


async def find_support_user(db: AsyncSession) -> User | None:
    result = await db.execute(select(User).where(User.name == SUPPORT_USERNAME))
    return result.scalar_one_or_none()


async def find_pair_dialog(db: AsyncSession, first_id: int, second_id: int) -> Dialog | None:
    result = await db.execute(
        select(Dialog)
        .join(Dialog.users)
        .where(User.id.in_([first_id, second_id]))
        .options(selectinload(Dialog.users))
    )
    for dialog in result.scalars().unique().all():
        member_ids = {member.id for member in dialog.users}
        if member_ids == {first_id, second_id}:
            return dialog
    return None


@router.post("/help")
async def help_command(
    name: str,
    message: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    text = message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is empty")

    support = await find_support_user(db)
    if support is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Support user is not configured")
    if support.id == user.id:
        raise HTTPException(status_code=400, detail="Support user cannot open a help dialog with itself")

    dialog = await find_pair_dialog(db, user.id, support.id)
    if dialog is None:
        dialog = Dialog(users=[user, support])
        db.add(dialog)
        await db.flush()

    ticket = Message(
        dialog_id=dialog.id,
        sender_id=user.id,
        text=text,
        created_at=func.now(),
        is_read=False,
        attachments=[],
        reply_to=None,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    payload = {
        "ticket_id": ticket.id,
        "user_id": user.id,
        "dialog_id": dialog.id,
        "user_name": name.strip() or user.name,
        "text": text,
    }
    await router.broker.publish(payload, queue=HELP_QUEUE)
    await publish_to_user(support.id, message_event(dialog.id, ticket, user.name))
    await invalidate_dialogs_cache(user.id)
    await invalidate_dialogs_cache(support.id)
    return {"data": "ok", "ticket_id": ticket.id, "dialog_id": dialog.id}


async def save_support_reply(db: AsyncSession, reply: HelpReply) -> Message | None:
    text = reply.text.strip()
    if not text:
        return None

    support = await find_support_user(db)
    if support is None:
        logger.warning("support user %s is missing, reply dropped", SUPPORT_USERNAME)
        return None

    dialog = await db.get(Dialog, reply.dialog_id)
    if dialog is None:
        logger.info("help reply dropped, dialog %s is missing", reply.dialog_id)
        return None

    await db.refresh(dialog, attribute_names=["users"])
    member_ids = {member.id for member in dialog.users}
    if reply.user_id not in member_ids or support.id not in member_ids:
        logger.info("help reply dropped, dialog %s members do not match", reply.dialog_id)
        return None

    ticket = await db.get(Message, reply.ticket_id)
    if ticket is None or ticket.dialog_id != dialog.id or ticket.sender_id != reply.user_id:
        logger.info("help reply dropped, ticket %s does not match the dialog", reply.ticket_id)
        return None

    answer = Message(
        dialog_id=dialog.id,
        sender_id=support.id,
        text=text,
        created_at=func.now(),
        is_read=False,
        attachments=[],
        reply_to=None,
    )
    db.add(answer)
    await db.commit()
    await db.refresh(answer)
    await publish_to_user(reply.user_id, message_event(dialog.id, answer, support.name))
    await invalidate_dialogs_cache(reply.user_id)
    await invalidate_dialogs_cache(support.id)
    return answer


@router.subscriber(HELP_REPLY_QUEUE)
async def on_help_reply(data: dict):
    try:
        reply = HelpReply.model_validate(data)
    except ValidationError:
        logger.exception("bad help reply payload")
        return

    async with async_session() as db:
        await save_support_reply(db, reply)
