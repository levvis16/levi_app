from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, update
from typing import List, Optional
from sqlalchemy.orm import selectinload

from datetime import datetime
from database.database import get_db
from database.models import User, Dialog, Message, user_dialog, Group
from database.schemas import DialogCreate, DialogOut, MessageCreate, MessageOut
from key_logic.hash import get_current_user, decode_token 

router = APIRouter(prefix="/dialogs", tags=["Dialogs"])

active_connections: dict[int, WebSocket] = {}

@router.get("/", response_model=List[DialogOut])
async def get_my_dialogs(db: AsyncSession=Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(Dialog).join(Dialog.users).where(User.id == current_user.id).options(
        selectinload(Dialog.messages),
        selectinload(Dialog.users),
        
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

        last_msg = None
        result_list.append(DialogOut(
            id = dialog.id,
            created_at=dialog.created_at,
            last_message=last_msg,
            companion_id= companion.id,
            companion_name= companion.name,
            unread_count=unread_count
        ))
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
    
    await db.delete(dialog)
    await db.commit()
    
    return None


@router.post("/{dialog_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    dialog_id: int,
    msg_data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    
    print("Received message data:", msg_data)
    print("Attachments:", msg_data.attachments)
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    
    await db.refresh(dialog, attribute_names=["users"])
    if current_user not in dialog.users:
        raise HTTPException(status_code=403, detail="Not your dialog")
    
    new_msg = Message(
        dialog_id=dialog.id,
        sender_id=current_user.id,
        text=msg_data.text or "",
        attachments=msg_data.attachments or [],
        created_at=datetime.now()
    )
    db.add(new_msg)
    await db.commit()
    await db.refresh(new_msg)
    
    recipient = next((u for u in dialog.users if u.id != current_user.id), None)

    if recipient and recipient.name in active_connections:

        ws = active_connections[recipient.name]
        await ws.send_json({
            "event": "new_message",
            "data": {
                "id": new_msg.id,
                "dialog_id": dialog_id,
                "sender_id": current_user.id,
                "sender_name": current_user.name,
                "text": new_msg.text,
                "created_at": new_msg.created_at.isoformat(),
                "is_read": new_msg.is_read,
                "attachments": new_msg.attachments or []
            }
        })
    else:
        print("Recipient not in active_connections")
    return MessageOut(
        id=new_msg.id,
        dialog_id=new_msg.dialog_id,
        sender_id=new_msg.sender_id,
        sender_name=current_user.name,
        text=new_msg.text,
        created_at=new_msg.created_at,
        is_read=new_msg.is_read,
        attachments=new_msg.attachments or []
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
            attachments=msg.attachments or []
        ))
    
    return result_messages

@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008, reason="Invalid token payload")
            return
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return
    
    await websocket.accept()
    active_connections[user_id] = websocket
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            
            if data.get("type") == "new_message":
                dialog_id = data.get("dialog_id")
                
                sender = await db.get(User, user_id)
                message = Message(
                    dialog_id=dialog_id,
                    sender_id=user_id,
                    sender_name=sender.username,
                    text=data.get("text"),
                    is_read=False
                )
                db.add(message)
                await db.commit()
                await db.refresh(message)
                
                dialog = await db.get(Dialog, dialog_id)
                companion_id = dialog.user1_id if dialog.user1_id != user_id else dialog.user2_id
                
                if companion_id in active_connections:
                    await active_connections[companion_id].send_json({
                        "type": "new_message",
                        "dialog_id": dialog_id,
                        "message": {
                            "id": message.id,
                            "sender_id": user_id,
                            "sender_name": sender.username,
                            "text": message.text,
                            "created_at": message.created_at.isoformat(),
                            "is_read": False
                        }
                    })
                
                await websocket.send_json({"type": "message_sent", "message_id": message.id})
            
            elif data.get("type") == "new_group_message":
                group_id = data.get("group_id")
                
                group = await db.get(Group, group_id)
                if not group:
                    continue
                
                sender = await db.get(User, user_id)
                message = Message(
                    group_id=group_id,
                    sender_id=user_id,
                    sender_name=sender.username,
                    text=data.get("text"),
                    is_read=False
                )
                db.add(message)
                await db.commit()
                await db.refresh(message)
                
                await websocket.send_json({"type": "message_sent", "message_id": message.id})
            
            elif data.get("type") == "mark_read":
                dialog_id = data.get("dialog_id")
                
                await db.execute(
                    update(Message)
                    .where(Message.dialog_id == dialog_id)
                    .where(Message.sender_id != user_id)
                    .where(Message.is_read == False)
                    .values(is_read=True)
                )
                await db.commit()
                
                dialog = await db.get(Dialog, dialog_id)
                companion_id = dialog.user1_id if dialog.user1_id != user_id else dialog.user2_id
                
                if companion_id in active_connections:
                    await active_connections[companion_id].send_json({
                        "type": "messages_read",
                        "dialog_id": dialog_id
                    })
                    
    except WebSocketDisconnect:
        del active_connections[user_id]

@router.post('/{dialog_id}/read')
async def mark_as_read(
    dialog_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await db.execute(update(Message)
                     .where(Message.dialog_id == dialog_id)
                     .where(Message.sender_id != current_user.id)
                     .where(Message.is_read == False)
                     .values(is_read = True)
                     )
    await db.commit()
    return {"status": "ok"}