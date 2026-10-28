from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    requestId: str
    retryable: bool
    details: dict[str, str] | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    reply: str
    model: str
    requestId: str


class DemoSessionResponse(BaseModel):
    token: str
    expiresAt: str
    mode: Literal["demo"] = "demo"


class DemoSessionStatus(BaseModel):
    expiresAt: str
    mode: Literal["demo"] = "demo"


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    createdAt: str


class ChatHistoryResponse(BaseModel):
    messages: list[ChatHistoryItem]


class AccountCredentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class AccountProfile(BaseModel):
    id: int
    email: EmailStr


class AccountTokenResponse(BaseModel):
    token: str
    expiresAt: str
    mode: Literal["account"] = "account"


class Permission(BaseModel):
    version: Literal[1] = 1
    scope: str
    riskLevel: Literal["T0", "T1", "T2", "T3", "TS"]
    decision: Literal["allow_once", "allow_scope", "deny", "pending"]
    expiresAt: str | None = None


class MemoryCandidate(BaseModel):
    version: Literal[1] = 1
    candidateId: str
    summary: str
    evidenceRef: str
    purpose: str
    status: Literal["candidate", "confirmed", "rejected", "expired"]
    expiresAt: str | None = None


class Job(BaseModel):
    version: Literal[1] = 1
    jobId: str
    status: Literal[
        "queued", "running", "waiting_approval", "waiting_pc",
        "retry_scheduled", "succeeded", "failed", "cancelled",
    ]
    intent: str
    canCancel: bool


class HudWidget(BaseModel):
    id: str
    type: Literal[
        "weather_card", "schedule_timeline", "task_checklist", "sleep_summary",
        "knowledge_snippets", "study_plan", "agent_progress", "explanation_card",
        "permission_request", "avatar_stage", "error_state",
    ]
    dataRef: str | None = None
    text: str | None = Field(default=None, max_length=500)


class HudSchema(BaseModel):
    layoutVersion: Literal[1] = 1
    view: str
    mode: Literal["compact", "standard", "spatial"]
    widgets: list[HudWidget]
