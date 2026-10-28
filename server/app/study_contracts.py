from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StudyJobCreate(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")


class StudyExcerpt(BaseModel):
    source: str = Field(min_length=1, max_length=255)
    page: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=500)
    score: float = Field(ge=0, le=1)


class StudyOutcome(BaseModel):
    success: bool
    modelName: str = Field(min_length=1, max_length=80)
    elapsedMs: int = Field(ge=0, le=600_000)
    excerpts: list[StudyExcerpt] = Field(default_factory=list, max_length=3)
    error: str | None = Field(default=None, max_length=500)


class StudyJobView(BaseModel):
    jobId: int
    status: str
    query: str
    result: StudyOutcome | None
    createdAt: datetime
    updatedAt: datetime


class StudyClaimView(BaseModel):
    jobId: int
    query: str
    maxResults: int


class StudyClaimResponse(BaseModel):
    job: StudyClaimView | None
