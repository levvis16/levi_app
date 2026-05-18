from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

#сомнительно, но окэй
class GroupShort(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class UserShort(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class GroupResponse(BaseModel):
    id: int
    name: str
    description: str
    #users: list[UserShort] = []

    class Config:
        from_attributes = True    

class UserCreate(BaseModel):
    name: str
    age: int = Field(ge=16, le=115)
    password: str

class GroupCreate(BaseModel):
    name: str
    description: str = ''


class UserResponse(BaseModel):
    id: int
    name: str
    age: int
    #groups: list[GroupShort] = []

    class Config:
        from_attributes = True


class DialogCreate(BaseModel):
    user_id_2: int

class DialogOut(BaseModel):
    id: int
    created_at: datetime
    last_message: Optional[str] = None
    companion_id: int
    companion_name: str
    unread_count: int = 0

class MessageCreate(BaseModel):
    text: str | None = None
    attachments: list[dict] | None = []

class MessageOut(BaseModel):
    id: int
    dialog_id: Optional[int] = None 
    sender_id: Optional[int] = None
    sender_name: str | None = None  
    text: str
    created_at: datetime
    is_read: bool
    unread_count: int=0
    attachments: list[dict] | None = []