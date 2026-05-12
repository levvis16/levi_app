from fastapi import APIRouter, Depends, HTTPException, status

from database import get_db
from key_logic.hash import get_current_user, hash_password
from models import User as UserModel
from schemas import UserResponse, UserCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from key_logic.hash import verify_password, create_access_token
from fastapi.security import OAuth2PasswordRequestForm

from key_logic.cesar_shifr import shifr
from passlib.context import CryptContext
# проверка special_id
import os
from dotenv import load_dotenv

load_dotenv()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
SECRET_KEY = os.getenv("SECRET_KEY")

router = APIRouter(prefix='/users', tags=['users'])

@router.get('/', response_model=list[UserResponse])
async def get_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserModel).options(selectinload(UserModel.groups)))
    return result.scalars().all()

@router.post('/', response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserModel).where(UserModel.name == user.name)
    )
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=409, detail='User already registered')  
    
    hashed_password = shifr(user.password)  
    
    db_user = UserModel(
        name=user.name,
        age=user.age,
        password=hashed_password
    )
    
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    
    return db_user

@router.get('/{user_id}', response_model=UserResponse)
async def get_one_user(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(UserModel, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.delete('/{user_id}', status_code=204)
async def delete_user(
    user_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.name != ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Admins only")
    
    user_to_delete = await db.get(UserModel, user_id)
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.delete(user_to_delete)
    await db.commit()
    return None

#переменная для хэширования пароля
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post('/register', response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    # Проверка существующего пользователя
    result = await db.execute(select(UserModel).where(UserModel.name == user.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Хешируем пароль
    hashed = hash_password(user.password)
    
    db_user = UserModel(
        name=user.name,
        age=user.age,
        password=hashed  
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.post("/login")
async def login_user(
    username: str,   # просто поле
    password: str,   # просто поле
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserModel).where(UserModel.name == username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    token = create_access_token(data={"sub": user.name})
    
    return {"access_token": token, "token_type": "bearer"}