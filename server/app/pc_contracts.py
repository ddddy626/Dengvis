from datetime import datetime

from pydantic import BaseModel, Field


class PairCodeView(BaseModel):
    code: str
    expiresAt: datetime


class PairConsume(BaseModel):
    code: str = Field(min_length=30, max_length=128)


class WorkerTokenView(BaseModel):
    token: str
    deviceId: int
    expiresAt: datetime


class DeviceView(BaseModel):
    deviceId: int
    online: bool
    lastSeen: datetime | None
    revoked: bool


class RevokeDeviceView(BaseModel):
    revoked: bool


class HeartbeatView(BaseModel):
    online: bool
    deviceId: int
