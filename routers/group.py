from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from main_app.database.database import get_db
from main_app.database.models import Group, Message, User, user_group
from main_app.database.schemas import GroupCreate, GroupResponse, UserShort, MessageCreate, MessageOut
from main_app.key_logic.hash import get_current_user
from main_app.routers.dialogs import publish_to_user

router = APIRouter(prefix='/groups', tags=['groups'])

@router.post('/', response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    group: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_group = Group(**group.model_dump())
    db.add(db_group)
    await db.commit()
    await db.refresh(db_group)
    
    stmt = insert(user_group).values(user_id=current_user.id, group_id=db_group.id)
    await db.execute(stmt)
    await db.commit()
    
    return db_group

@router.get('/', response_model=list[GroupResponse])
async def get_my_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Group).join(user_group).where(user_group.c.user_id == current_user.id)
    )
    groups = result.scalars().all()
    return groups

@router.get('/{group_id}', response_model=GroupResponse)
async def get_group(group_id: int, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')
    return group


@router.post('/{group_id}/users/{user_id}')
async def add_user_to_group(group_id: int, user_id: int, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    
    stmt = insert(user_group).values(user_id=user_id, group_id=group_id)
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}


@router.delete('/{group_id}/users/{user_id}')
async def remove_user_from_group(group_id: int, user_id: int, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    
    stmt = delete(user_group).where(
        user_group.c.user_id == user_id,
        user_group.c.group_id == group_id
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}


@router.get('/{group_id}/users', response_model=list[UserShort])
async def get_group_users(group_id: int, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')
    
    result = await db.execute(
        select(User).join(user_group).where(user_group.c.group_id == group_id)
    )
    return result.scalars().all()



@router.get('/{group_id}/messages', response_model=list[MessageOut])
async def get_group_messages(
    group_id: int,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')
    
    result = await db.execute(
        select(Message)
        .where(Message.group_id == group_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    
    output = []
    for msg in messages:
        sender = await db.get(User, msg.sender_id)
        output.append(MessageOut(
            id=msg.id,
            dialog_id=None,                        
            group_id=msg.group_id,
            sender_id=msg.sender_id,
            sender_name=sender.name if sender else "Unknown",
            text=msg.text,
            created_at=msg.created_at,
            is_read=msg.is_read,
            attachments = msg.attachments or []
        ))
    return output


@router.post('/{group_id}/messages', status_code=201)
async def send_group_message(
    group_id: int,
    msg_data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')

    db_message = Message(
        group_id=group_id,
        sender_id=current_user.id,
        text=msg_data.text or "",
        attachments=msg_data.attachments or [],
    )
    db.add(db_message)
    await db.commit()
    await db.refresh(db_message)

    members_result = await db.execute(
        select(User).join(user_group).where(user_group.c.group_id == group_id)
    )
    members = members_result.scalars().all()

    for member in members:
        if member.id != current_user.id:
            await publish_to_user(member.id, {
                "type": "new_group_message",
                "group_id": group_id,
                "message": {
                    "id": db_message.id,
                    "group_id": group_id,
                    "sender_id": current_user.id,
                    "sender_name": current_user.name,
                    "text": db_message.text,
                    "created_at": db_message.created_at.isoformat(),
                    "is_read": False,
                    "attachments": db_message.attachments or []
                }
            })

    return db_message