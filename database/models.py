from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Table, Column, ForeignKey, Integer, Text
from sqlalchemy import String, CheckConstraint
from datetime import datetime

class Base(DeclarativeBase):
    pass

user_group = Table(
    'user_group',
    Base.metadata,
    Column('user_id', ForeignKey('users.id'), primary_key=True),
    Column('group_id', ForeignKey('groups.id'), primary_key=True),
)

user_dialog = Table(
    "user_dialog",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("dialog_id", Integer, ForeignKey("dialogs.id"), primary_key=True),
)

class Dialog(Base):
    __tablename__ = "dialogs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship(secondary=user_dialog, back_populates="dialogs")
    messages: Mapped[list["Message"]] = relationship(back_populates="dialog", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    is_read: Mapped[bool] = mapped_column(default=False)

    dialog: Mapped["Dialog"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship(back_populates="messages") 

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    age: Mapped[int] = mapped_column()
    password: Mapped[str] = mapped_column(String(356), unique=True)

    groups: Mapped[list['Group']] = relationship(
        secondary=user_group, back_populates='users'
    )
    dialogs: Mapped[list["Dialog"]] = relationship(secondary=user_dialog, back_populates="users")
    messages: Mapped[list["Message"]] = relationship(back_populates="sender")
    __table_args__ = (CheckConstraint('age >=16 and age <=115', name='check_age_range'), )


class Group(Base):
    __tablename__ = 'groups'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(300))

    users: Mapped[list['User']] = relationship(
        secondary=user_group, back_populates='groups'
    )

