import json
from pathlib import Path

from app.contracts import AccountCredentials, AccountProfile, AccountTokenResponse, ChatHistoryItem, ChatHistoryResponse, DemoSessionResponse, DemoSessionStatus, ErrorBody, HudSchema, Job, MemoryCandidate, Permission
from app.life_contracts import LifeApprovalView, LifeItemDraft, LifeItemUpdate, LifeItemView, LifeItemsView, LifePlanCreate, LifePlanDecision, DemoLifePlanDecision, LifePlanEdit, LifePlanView, MorningReportView, JobSummaryView, JobEventView, JobCancelView, SavedItemRef, SavedTaskView, SavedScheduleView, SleepSourceView, LifeSuggestionRequest, LifeSuggestionView, PermissionGrantView, PermissionRevoke, PermissionRevokeView
from app.memory_contracts import MemoryCandidateCreate, MemoryCandidateEdit, MemoryCandidateView, MemoryDecision, MemoryRevokeView, MemoryDeleteView
from app.pc_contracts import PairCodeView, PairConsume, WorkerTokenView, DeviceView, RevokeDeviceView, HeartbeatView
from app.study_contracts import StudyJobCreate, StudyExcerpt, StudyOutcome, StudyJobView, StudyClaimView, StudyClaimResponse


OUT = Path(__file__).resolve().parents[2] / "shared" / "contracts"
OUT.mkdir(parents=True, exist_ok=True)
for model in (ErrorBody, Job, Permission, MemoryCandidate, HudSchema, DemoSessionResponse, DemoSessionStatus, ChatHistoryItem, ChatHistoryResponse, AccountCredentials, AccountProfile, AccountTokenResponse, LifeItemDraft, LifeItemUpdate, LifeItemView, LifeItemsView, LifePlanCreate, LifePlanDecision, DemoLifePlanDecision, LifePlanEdit, LifePlanView, MorningReportView, LifeApprovalView, JobSummaryView, JobEventView, JobCancelView, SavedItemRef, SavedTaskView, SavedScheduleView, SleepSourceView, LifeSuggestionRequest, LifeSuggestionView, PermissionGrantView, PermissionRevoke, PermissionRevokeView, MemoryCandidateCreate, MemoryCandidateEdit, MemoryCandidateView, MemoryDecision, MemoryRevokeView, MemoryDeleteView, PairCodeView, PairConsume, WorkerTokenView, DeviceView, RevokeDeviceView, HeartbeatView, StudyJobCreate, StudyExcerpt, StudyOutcome, StudyJobView, StudyClaimView, StudyClaimResponse):
    target = OUT / f"{model.__name__}.schema.json"
    target.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
