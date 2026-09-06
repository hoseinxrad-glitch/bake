import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, Table
)
from sqlalchemy.orm import relationship
from database import Base

room_members = Table(
    "room_members",
    Base.metadata,
    Column("room_id", Integer, ForeignKey("rooms.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_online = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    is_bot = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    rooms = relationship("Room", secondary=room_members, back_populates="members")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)  # only used for groups/channels
    is_group = Column(Boolean, default=False)
    room_type = Column(String, default="direct")  # direct | group | channel
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    members = relationship("User", secondary=room_members, back_populates="rooms")
    messages = relationship("Message", back_populates="room", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(String, nullable=True)  # text content, may be empty for pure file messages
    message_type = Column(String, default="text")  # text | image | file | voice
    file_url = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)  # bytes
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_read = Column(Boolean, default=False)

    room = relationship("Room", back_populates="messages")
    sender = relationship("User")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
