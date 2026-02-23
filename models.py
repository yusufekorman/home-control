import secrets
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from pydantic import BaseModel
import enum

from database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class HttpMethod(str, enum.Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


# ─── SQLAlchemy Models ─────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    ip_address = Column(String(256), nullable=False)
    base_url = Column(String(512), nullable=False)  # e.g. http://192.168.1.x
    auth_header_name = Column(String(128), nullable=True)
    auth_header_value = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True)
    icon = Column(String(64), default="device")  # icon key for UI
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    actions = relationship("DeviceAction", back_populates="device", cascade="all, delete-orphan")
    logs = relationship("DeviceLog", back_populates="device", cascade="all, delete-orphan")


class DeviceAction(Base):
    __tablename__ = "device_actions"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    path = Column(String(512), nullable=False)      # e.g. /api/relay/toggle
    method = Column(String(10), default="GET")       # HTTP method
    body = Column(Text, nullable=True)               # optional JSON body
    extra_headers = Column(Text, nullable=True)      # optional JSON headers
    created_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="actions")


class DeviceLog(Base):
    __tablename__ = "device_logs"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    action_name = Column(String(128), nullable=True)
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    triggered_by = Column(String(64), default="web")  # web | api | mcp
    created_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="logs")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    key_prefix = Column(String(8), nullable=False)
    key_hash = Column(String(256), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─── Pydantic Schemas ──────────────────────────────────────────────────────────

class DeviceActionBase(BaseModel):
    name: str
    description: str = ""
    path: str
    method: str = "GET"
    body: Optional[str] = None
    extra_headers: Optional[str] = None

class DeviceActionCreate(DeviceActionBase):
    pass

class DeviceActionRead(DeviceActionBase):
    id: int
    device_id: int
    created_at: datetime
    class Config:
        from_attributes = True


class DeviceBase(BaseModel):
    name: str
    description: str = ""
    ip_address: str
    base_url: str
    auth_header_name: Optional[str] = None
    auth_header_value: Optional[str] = None
    is_active: bool = True
    icon: str = "device"

class DeviceCreate(DeviceBase):
    pass

class DeviceUpdate(DeviceBase):
    pass

class DeviceRead(DeviceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    actions: List[DeviceActionRead] = []
    class Config:
        from_attributes = True


class DeviceLogRead(BaseModel):
    id: int
    device_id: int
    action_name: Optional[str]
    status_code: Optional[int]
    response_body: Optional[str]
    error: Optional[str]
    triggered_by: str
    created_at: datetime
    class Config:
        from_attributes = True


class ApiKeyRead(BaseModel):
    id: int
    name: str
    key_prefix: str
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime
    class Config:
        from_attributes = True

class ApiKeyCreate(BaseModel):
    name: str

class ApiKeyCreated(ApiKeyRead):
    """Returned once on creation – includes the raw key"""
    raw_key: str


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False

class UserRead(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: datetime
    class Config:
        from_attributes = True
