from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, update
from typing import List, Optional
from sqlalchemy.orm import selectinload
from datetime import datetime
import asyncio
import json
import os

import redis.asyncio as aioredis

from main_app.database.database import get_db
from main_app.database.models import User, Dialog, Message, user_dialog, Group
from main_app.database.schemas import DialogCreate, DialogOut, MessageCreate, MessageOut
from main_app.key_logic.hash import get_current_user, decode_token

router = APIRouter(prefix="/dialogs", tags=["Dialogs"])

active_connections: dict[int, WebSocket] = {}

redis_pool: aioredis.ConnectionPool = None

def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)

async def invalidate_dialogs_cache(user_id: int):
    r = get_redis()
    await r.delete(f"user:{user_id}:dialogs")


async def get_cached_dialogs(user_id: int) -> Optional[List[dict]]:
    r = get_redis()
    cached = await r.get(f"user:{user_id}:dialogs")
    if cached:
        return json.loads(cached)
    return None


async def set_cached_dialogs(user_id: int, dialogs_data: List[dict], ttl: int = 60):
    r = get_redis()
    await r.setex(f"user:{user_id}:dialogs", ttl, json.dumps(dialogs_data))


async def publish_to_user(user_id: int, payload: dict):
    r = get_redis()
    await r.publish(f"user:{user_id}", json.dumps(payload))


async def listen_for_messages(user_id: int, websocket: WebSocket):
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"user:{user_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                if websocket.client_state.value == 1:
                    await websocket.send_json(data)
    except Exception as e:
        print(f"Redis listener error for user {user_id}: {e}")
    finally:
        await pubsub.unsubscribe(f"user:{user_id}")


@router.get("/", response_model=List[DialogOut])
async def get_my_dialogs(
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    cached = await get_cached_dialogs(current_user.id)
    if cached is not None:
        return cached
    
    stmt = select(Dialog).join(Dialog.users).where(User.id == current_user.id).options(
        selectinload(Dialog.users),  # users оставляем, нужно для companion
    )
    result = await db.execute(stmt)
    dialogs = result.scalars().all()
    
    result_list = []
    for dialog in dialogs:
        companion = next((u for u in dialog.users if u.id != current_user.id), None)
        if not companion:
            continue
        
        unread_count = await db.scalar(
            select(func.count(Message.id))
            .where(Message.dialog_id == dialog.id)
            .where(Message.sender_id != current_user.id)
            .where(Message.is_read == False)
        )
        
        last_msg_result = await db.execute(
            select(Message.text)
            .where(Message.dialog_id == dialog.id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        last_message = last_msg_result.scalar_one_or_none()
        
        result_list.append({
            "id": dialog.id,
            "created_at": dialog.created_at.isoformat() if dialog.created_at else None,
            "last_message": last_message,
            "companion_id": companion.id,
            "companion_name": companion.name,
            "unread_count": unread_count
        })
    
    await set_cached_dialogs(current_user.id, result_list, ttl=60)
    
    return result_list

@router.post("/", response_model=DialogOut, status_code=status.HTTP_201_CREATED)
async def create_or_get_dialog(
    dialog_data: DialogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    companion = await db.get(User, dialog_data.user_id_2)
    if not companion:
        raise HTTPException(status_code=404, detail="User not found")

    stmt = select(Dialog).join(Dialog.users).where(
        User.id.in_([current_user.id, companion.id])
    )
    result = await db.execute(stmt)
    dialogs = result.scalars().all()

    for dialog in dialogs:
        await db.refresh(dialog, attribute_names=["users"])
        if current_user in dialog.users and companion in dialog.users:
            last_msg_result = await db.execute(
                select(Message.text)
                .where(Message.dialog_id == dialog.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_msg = last_msg_result.scalar_one_or_none()
            return DialogOut(
                id=dialog.id,
                created_at=dialog.created_at,
                last_message=last_msg,
                companion_id=companion.id,
                companion_name=companion.name,
                unread_count=0
            )

    new_dialog = Dialog(users=[current_user, companion])
    db.add(new_dialog)
    await db.commit()
    await db.refresh(new_dialog)
    if new_dialog:  
        await invalidate_dialogs_cache(current_user.id)
        await invalidate_dialogs_cache(companion.id)
    return DialogOut(
        id=new_dialog.id,
        created_at=new_dialog.created_at,
        last_message=None,
        companion_id=companion.id,
        companion_name=companion.name,
        unread_count=0
    )


@router.delete('/{dialog_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_dialog(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")

    await db.refresh(dialog, attribute_names=["users"])
    if current_user not in dialog.users:
        raise HTTPException(status_code=403, detail="You are not a member of this dialog")

    companion = next((u for u in dialog.users if u.id != current_user.id), None)

    await db.delete(dialog)
    await db.commit()
    await invalidate_dialogs_cache(current_user.id)
    if companion:
        await invalidate_dialogs_cache(companion.id)

    return None


@router.post("/{dialog_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    dialog_id: int,
    msg_data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")

    await db.refresh(dialog, attribute_names=["users"])
    if current_user not in dialog.users:
        raise HTTPException(status_code=403, detail="Not your dialog")

    new_msg = Message(
        dialog_id=dialog.id,
        created_at = func.now(),
        sender_id=current_user.id,
        text=msg_data.text or "",
        attachments=msg_data.attachments or [],
        reply_to=msg_data.reply_to
    )
    db.add(new_msg)
    await db.commit()
    await db.refresh(new_msg)

    recipient = next((u for u in dialog.users if u.id != current_user.id), None)
    if recipient:
        await publish_to_user(recipient.id, {
            "type": "new_message",
            "dialog_id": dialog_id,
            "message": {
                "id": new_msg.id,
                "dialog_id": dialog_id,
                "sender_id": current_user.id,
                "sender_name": current_user.name,
                "text": new_msg.text,
                "created_at": new_msg.created_at.isoformat(),
                "is_read": new_msg.is_read,
                "attachments": new_msg.attachments or [],
                "reply_to": new_msg.reply_to
            }
        })
        await invalidate_dialogs_cache(recipient.id)

    await invalidate_dialogs_cache(current_user.id)
    return MessageOut(
        id=new_msg.id,
        dialog_id=new_msg.dialog_id,
        sender_id=new_msg.sender_id,
        sender_name=current_user.name,
        text=new_msg.text,
        created_at=new_msg.created_at,
        is_read=new_msg.is_read,
        attachments=new_msg.attachments or [],
        reply_to=msg_data.reply_to
    )


@router.get("/{dialog_id}/messages", response_model=list[MessageOut])
async def get_messages(
    dialog_id: int,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    await db.refresh(dialog, attribute_names=["users"])
    if current_user not in dialog.users:
        raise HTTPException(status_code=403, detail="Not your dialog")

    stmt = select(Message).where(Message.dialog_id == dialog_id).order_by(desc(Message.created_at)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    messages = result.scalars().all()

    result_messages = []
    for msg in messages:
        sender = next((u for u in dialog.users if u.id == msg.sender_id), None)
        sender_name = sender.name if sender else "Unknown"
        result_messages.append(MessageOut(
            id=msg.id,
            dialog_id=msg.dialog_id,
            sender_id=msg.sender_id,
            sender_name=sender_name,
            text=msg.text,
            created_at=msg.created_at,
            is_read=msg.is_read,
            attachments=msg.attachments or [],
            reply_to=msg.reply_to
        ))

    return result_messages


@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        if not username:
            await websocket.close(code=1008, reason="Invalid token payload")
            return
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return

    result = await db.execute(select(User).where(User.name == username))
    user = result.scalar_one_or_none()
    if not user:
        await websocket.close(code=1008, reason="User not found")
        return

    user_id = user.id

    await websocket.accept()
    active_connections[user_id] = websocket

    # Запускаем listener Redis в фоне
    redis_task = asyncio.create_task(listen_for_messages(user_id, websocket))

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if data.get("type") == "invalidate_dialogs":
                await websocket.send_json({"type": "dialogs_invalidated"})

            elif data.get("type") == "mark_read":
                dialog_id = data.get("dialog_id")

                if not dialog_id:
                    await websocket.send_json({"type": "error", "detail": "dialog_id is required"})
                    continue

                dialog = await db.get(Dialog, dialog_id)
                if not dialog:
                    await websocket.send_json({"type": "error", "detail": "Dialog not found"})
                    continue

                await db.refresh(dialog, attribute_names=["users"])
                if user_id not in [u.id for u in dialog.users]:
                    await websocket.send_json({"type": "error", "detail": "Not your dialog"})
                    continue

                await db.execute(
                    update(Message)
                    .where(Message.dialog_id == dialog_id)
                    .where(Message.sender_id != user_id)
                    .where(Message.is_read == False)
                    .values(is_read=True)
                )
                await db.commit()

                companion = next((u for u in dialog.users if u.id != user_id), None)
                if companion:
                    await publish_to_user(companion.id, {
                        "type": "messages_read",
                        "dialog_id": dialog_id
                    })

                    await invalidate_dialogs_cache(companion.id)

                await invalidate_dialogs_cache(user_id)
            else:
                await websocket.send_json({"type": "error", "detail": "Unknown message type"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error for user {user_id}: {e}")
    finally:
        redis_task.cancel()
        active_connections.pop(user_id, None)


@router.post('/{dialog_id}/read')
async def mark_as_read(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await db.execute(
        update(Message)
        .where(Message.dialog_id == dialog_id)
        .where(Message.sender_id != current_user.id)
        .where(Message.is_read == False)
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}