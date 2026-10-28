from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MemoryCandidateCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=1000)
    evidenceRef: str = Field(min_length=1, max_length=512)
    purpose: Literal["planning", "conversation"]
    expiresAt: datetime

    @model_validator(mode="after")
    def timezone_required(self):
        if self.expiresAt.tzinfo is None:
            raise ValueError("有效期必须包含时区。")
        return self


class MemoryCandidateEdit(BaseModel):
    summary: str = Field(min_length=1, max_length=1000)
    purpose: Literal["planning", "conversation"]
    expiresAt: datetime

    @model_validator(mode="after")
    def timezone_required(self):
        if self.expiresAt.tzinfo is None:
            raise ValueError("有效期必须包含时区。")
        return self


class MemoryDecision(BaseModel):
    decision: Literal["confirm", "reject"]


class MemoryCandidateView(BaseModel):
    id: int
    summary: str
    evidenceRef: str
    purpose: str
    expiresAt: datetime
    status: str
    memoryId: int | None


class MemoryRevokeView(BaseModel):
    revoked: bool


class MemoryDeleteView(BaseModel):
    deleted: bool
