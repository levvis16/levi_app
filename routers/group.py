from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Group as GroupModel
from schemas import GroupCreate, GroupResponse

router = APIRouter(prefix='/groups', tags=['groups'])

@router.post('/', response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(group: GroupCreate, db: AsyncSession = Depends(get_db)):
    db_group = GroupModel(**group.model_dump())
    db.add(db_group)
    await db.commit()
    await db.refresh(db_group)
    return db_group

@router.get('/{group_id}', response_model=GroupResponse, status_code=status.HTTP_200_OK)
async def get_group(group_id: int, db: AsyncSession = Depends(get_db)):
    group = await db.get(GroupModel, group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found')
    return group

