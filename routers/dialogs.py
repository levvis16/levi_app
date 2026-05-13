from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List
from sqlalchemy.orm import selectinload

from database.database import get_db
from database.models import User, Dialog, Message, user_dialog
from database.schemas import DialogCreate, DialogOut, MessageCreate, MessageOut
from key_logic.hash import get_current_user, decode_token 

router = APIRouter(prefix="/dialogs", tags=["Dialogs"])

active_connections: dict[int, WebSocket] = {}

@router.get("/", response_model=List[DialogOut])
async def get_my_dialogs(db: AsyncSession=Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(Dialog).join(Dialog.users).where(User.id == current_user.id).options(
        selectinload(Dialog.messages),
        selectinload(Dialog.users)
    )
    result = await db.execute(stmt)
    dialogs = result.scalars().all()

    result_list = []
    for dialog in dialogs:
        companion = next((u for u in dialog.users if u.id != current_user.id), None)
        if not companion:
            continue

        last_msg = dialog.messages[-1].text if dialog.messages else None
        result_list.append(DialogOut(
            id = dialog.id,
            created_at=dialog.created_at,
            last_message=last_msg,
            companion_id= companion.id,
            companion_name= companion.name,
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
    ).options(selectinload(Dialog.users))
    
    result = await db.execute(stmt)
    dialogs = result.scalars().all()
    
    for dialog in dialogs:
        users_in_dialog = {u.id for u in dialog.users}
        if {current_user.id, companion.id}.issubset(users_in_dialog):
            last_msg = dialog.messages[-1].text if dialog.messages else None
            return DialogOut(
                id=dialog.id,
                created_at=dialog.created_at,
                last_message=last_msg,
                companion_id=companion.id,
                companion_name=companion.name,
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
    )

@router.post('/{dialog_id}/messages', response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(dialog_id: int, msg_data: MessageCreate, db: AsyncSession=Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    dialog = await db.get(Dialog, dialog_id)
    if not dialog:
        raise HTTPException(status_code=404, detail="chat not created")
    await db.refresh(dialog, attribute_names=['users'])
    if current_user not in dialog.users:
        raise HTTPException(status_code=403, detail="the not your chat")
    
    new_msg = Message(
        dialog_id = dialog.id,
        sender_id = current_user.id,
        text = msg_data.text,
    )
    db.add(new_msg)
    await db.commit()
    await db.refresh(new_msg)

    result = await db.execute(
        select(Dialog).where(Dialog.id == dialog_id).options(selectinload(Dialog.users))
    )
    dialog = result.scalar_one()
    recipient = next((u for u in dialog.users if u.id != current_user.id), None)

    if recipient and recipient.id in active_connections:
        ws = active_connections[recipient.id]
        await ws.send_json({
            "event": "new_message",
            "data": {
                "message_id": new_msg.id,
                "dialog_id": dialog_id,
                "sender_id": current_user.id,
                "sender_name": current_user.name,
                "text": new_msg.text,
                "created_at": new_msg.created_at.isoformat()
            }
        })

    return new_msg

@router.get("/{dialog_id}/messages", response_model=List[MessageOut])
async def get_messages(
    dialog_id: int,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Message).where(Message.dialog_id == dialog_id).order_by(desc(Message.created_at)).offset(offset).limit(limit)
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages

@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008, reason="Invalid token payload")
            return
    except Exception as e:
        print(f"Auth error: {e}")
        await websocket.close(code=1008, reason="Invalid token")
        return
    
    await websocket.accept()
    active_connections[user_id] = websocket
    print(f"✅ User {user_id} connected. Total active: {len(active_connections)}")
    
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
            else:
                await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        if user_id in active_connections:
            del active_connections[user_id]
        print(f"🔌 User {user_id} disconnected")
