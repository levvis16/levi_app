from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List
from sqlalchemy.orm import selectinload

from database import get_db
from models import User, Dialog, Message, user_dialog
from schemas import DialogCreate, DialogOut, MessageCreate, MessageOut
from key_logic.hash import get_current_user 

router = APIRouter(prefix="/dialogs", tags=["Dialogs"])

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