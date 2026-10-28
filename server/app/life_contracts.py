"""Input contracts for the approved life-task workflow."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LifeItemDraft(BaseModel):
    kind: Literal["task", "schedule"]
    title: str = Field(min_length=1, max_length=255)
    dueAt: datetime | None = None
    startsAt: datetime | None = None
    endsAt: datetime | None = None

    @model_validator(mode="after")
    def validate_times(self):
        times = (self.dueAt, self.startsAt, self.endsAt)
        if any(value is not None and value.tzinfo is None for value in times):
            raise ValueError("时间必须包含时区。")
        if self.kind == "schedule":
            if self.startsAt is None or self.endsAt is None or self.endsAt <= self.startsAt:
                raise ValueError("日程必须提供有效的开始和结束时间。")
            if self.dueAt is not None:
                raise ValueError("日程不能包含待办截止时间。")
        elif self.startsAt is not None or self.endsAt is not None:
            raise ValueError("待办不能包含日程开始或结束时间。")
        return self


class LifePlanCreate(BaseModel):
    intent: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    items: list[LifeItemDraft] | None = Field(default=None, min_length=1, max_length=8)


class LifeSuggestionRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=500)


class LifeSuggestionView(BaseModel):
    items: list[LifeItemDraft] = Field(min_length=1, max_length=8)
    questions: list[str] = Field(default_factory=list, max_length=3)
    model: str


class LifePlanEdit(BaseModel):
    items: list[LifeItemDraft] = Field(min_length=1, max_length=8)


class LifePlanDecision(BaseModel):
    decision: Literal["allow_once", "allow_scope", "deny"]


class DemoLifePlanDecision(BaseModel):
    decision: Literal["allow_once", "deny"]


class PermissionGrantView(BaseModel):
    id: int
    scope: str
    dataSource: str
    grantType: str
    expiresAt: datetime | None


class PermissionRevoke(BaseModel):
    scope: str = Field(min_length=1, max_length=120)


class PermissionRevokeView(BaseModel):
    revoked: bool


class LifeItemUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    status: Literal["open", "done", "planned", "completed", "cancelled"]
    dueAt: datetime | None = None
    startsAt: datetime | None = None
    endsAt: datetime | None = None

    @model_validator(mode="after")
    def validate_aware_times(self):
        if any(value is not None and value.tzinfo is None for value in (self.dueAt, self.startsAt, self.endsAt)):
            raise ValueError("时间必须包含时区。")
        return self


class SavedItemRef(BaseModel):
    kind: Literal["task", "schedule"]
    id: int


class LifeApprovalView(BaseModel):
    id: int
    decision: str
    scope: str
    expiresAt: datetime


class LifePlanView(BaseModel):
    jobId: int
    status: str
    intent: str
    items: list[LifeItemDraft]
    saved: list[SavedItemRef]
    memoryUsed: list[str] = Field(default_factory=list)
    approval: LifeApprovalView


class SavedTaskView(BaseModel):
    id: int
    title: str
    dueAt: datetime | None
    status: str


class SavedScheduleView(BaseModel):
    id: int
    title: str
    startsAt: datetime
    endsAt: datetime
    status: str


class LifeItemsView(BaseModel):
    tasks: list[SavedTaskView]
    schedules: list[SavedScheduleView]


class LifeItemView(BaseModel):
    id: int
    kind: Literal["task", "schedule"]
    title: str
    status: str


class SleepSourceView(BaseModel):
    status: Literal["not_authorized", "not_synced", "failed", "available"]
    source: str
    minutes: int | None


class MorningReportView(BaseModel):
    date: str
    tasks: list[SavedTaskView]
    schedules: list[SavedScheduleView]
    sleep: SleepSourceView
    sources: dict[str, str]


class JobSummaryView(BaseModel):
    jobId: int
    status: str
    decision: str
    preview: str
    latestEvent: str | None
    createdAt: datetime
    updatedAt: datetime
    approvalExpiresAt: datetime


class JobEventView(BaseModel):
    seq: int
    type: str
    summary: str
    timestamp: datetime


class JobCancelView(BaseModel):
    cancelled: bool
