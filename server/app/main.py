from uuid import uuid4
import asyncio
from datetime import date

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from redis.exceptions import RedisError

from .contracts import AccountCredentials, AccountProfile, AccountTokenResponse, ChatHistoryResponse, ChatRequest, ChatResponse, DemoSessionResponse, DemoSessionStatus, ErrorBody
from .account_auth import account_id_for_token, account_token_from_authorization, check_rate_limit, create_account, find_account_by_email, find_account_by_id, issue_access_token, password_matches, revoke_access_token, DUMMY_HASH
from .account_history import account_history_available, append_account_exchange, read_account_history
from .deepseek import DeepSeekFailure, complete
from .demo_history import append_exchange, history_available, read_history
from .demo_sessions import create_demo_session, find_demo_session, utc_iso
from .demo_tokens import InvalidDemoToken, token_from_authorization
from .life_contracts import LifeItemDraft, LifeItemUpdate, LifeItemView, LifeItemsView, LifePlanCreate, LifePlanDecision, DemoLifePlanDecision, LifePlanEdit, LifePlanView, MorningReportView, JobSummaryView, JobEventView, JobCancelView, LifeSuggestionRequest, LifeSuggestionView, PermissionGrantView, PermissionRevoke, PermissionRevokeView
from .life_planner import suggest_life, study_prompt, suggest_study_life
from .life_store import LifeConflict, create_plan, decide_plan, edit_plan, get_plan, get_plan_by_key, list_items
from .permission_store import list_permissions, revoke_permission
from .demo_life_store import LifeConflict as DemoLifeConflict, create_plan as demo_create_plan, decide_plan as demo_decide_plan, edit_plan as demo_edit_plan, get_plan as demo_get_plan, get_plan_by_key as demo_get_plan_by_key, list_items as demo_list_items
from .life_overview import LifeItemConflict, morning_report, update_item
from .job_center import JobConflict, list_jobs, job_events, cancel_job
from .memory_contracts import MemoryCandidateCreate, MemoryCandidateEdit, MemoryCandidateView, MemoryDecision, MemoryRevokeView, MemoryDeleteView
from .memory_store import MemoryConflict, create_candidate, decide_candidate, edit_candidate, list_candidates, revoke_memory, delete_memory
from .pc_auth import PairFailure, consume_pair_code, create_pair_code, list_devices, revoke_device, worker_identity
from .pc_contracts import PairCodeView, PairConsume, WorkerTokenView, DeviceView, RevokeDeviceView, HeartbeatView
from .study_contracts import StudyJobCreate, StudyJobView, StudyOutcome, StudyClaimResponse
from .study_store import StudyConflict, create_study_job, get_study_job, list_study_jobs, claim_study_job, complete_study_job, retry_study_job
from .demo_quota import DemoQuotaExceeded, allow_demo_session, reserve_demo_call, finish_demo_call, reserve_model_call, finish_model_call


app = FastAPI(title="Jarvis API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    error = ErrorBody(code="INVALID_REQUEST", message="请求格式不正确或消息长度超出限制。", requestId=str(uuid4()), retryable=False)
    return JSONResponse(status_code=422, content=error.model_dump(exclude_none=True))


def failure_response(code: str, message: str, request_id: str, status_code: int, retryable: bool = False) -> JSONResponse:
    error = ErrorBody(code=code, message=message, requestId=request_id, retryable=retryable)
    return JSONResponse(status_code=status_code, content=error.model_dump(exclude_none=True))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/demo/session", response_model=DemoSessionResponse, status_code=201)
async def issue_demo_session(request: Request) -> DemoSessionResponse | JSONResponse:
    request_id = str(uuid4())
    try:
        allowed = await allow_demo_session(request.client.host if request.client else "unknown")
    except RedisError:
        return failure_response("DEMO_QUOTA_UNAVAILABLE", "游客入口暂时不可用。", request_id, 503, True)
    if not allowed:
        return failure_response("DEMO_SESSION_RATE_LIMITED", "游客会话创建过于频繁，请稍后再试。", request_id, 429, True)
    try:
        token, session = await asyncio.to_thread(create_demo_session)
    except (SQLAlchemyError, ValueError):
        return failure_response("SESSION_STORE_UNAVAILABLE", "游客会话暂时无法创建。", request_id, 503, True)
    return DemoSessionResponse(token=token, expiresAt=utc_iso(session.expires_at))


@app.get("/api/v1/demo/session", response_model=DemoSessionStatus)
def check_demo_session(authorization: str | None = Header(default=None)) -> DemoSessionStatus | JSONResponse:
    request_id = str(uuid4())
    try:
        token = token_from_authorization(authorization)
    except InvalidDemoToken:
        return failure_response("DEMO_SESSION_INVALID", "游客会话凭证无效。", request_id, 401)
    try:
        session = find_demo_session(token)
    except (SQLAlchemyError, ValueError):
        return failure_response("SESSION_STORE_UNAVAILABLE", "游客会话暂时无法校验。", request_id, 503, True)
    if session is None:
        return failure_response("DEMO_SESSION_EXPIRED", "游客会话不存在或已过期。", request_id, 401)
    return DemoSessionStatus(expiresAt=utc_iso(session.expires_at))


@app.post("/api/v1/chat", response_model=ChatResponse, responses={503: {"model": ErrorBody}, 502: {"model": ErrorBody}})
async def chat(body: ChatRequest, request: Request, authorization: str | None = Header(default=None)) -> ChatResponse | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        await history_available()
    except RedisError:
        return failure_response("HISTORY_STORE_UNAVAILABLE", "聊天记录暂时不可用。", request_id, 503, True)
    try:
        reservation = await reserve_demo_call(session.id, body.message)
    except DemoQuotaExceeded as exc:
        return failure_response(exc.code, str(exc), request_id, 429, True)
    except (RedisError, SQLAlchemyError, ValueError):
        return failure_response("DEMO_QUOTA_UNAVAILABLE", "游客额度服务暂时不可用。", request_id, 503, True)
    try:
        reply, model = await complete(body.message, getattr(request.app.state, "deepseek_transport", None))
    except DeepSeekFailure as exc:
        try:
            await finish_demo_call(session.id, reservation, False, model_charged=exc.code == "MODEL_BAD_RESPONSE")
        except (RedisError, SQLAlchemyError):
            return failure_response("DEMO_QUOTA_UNAVAILABLE", "模型失败且额度状态暂时无法恢复，请稍后重试。", request_id, 503, True)
        status = 503 if exc.retryable or exc.code == "MODEL_NOT_CONFIGURED" else 502
        return failure_response(exc.code, str(exc), request_id, status, exc.retryable)
    except BaseException:
        await finish_demo_call(session.id, reservation, False)
        raise
    try:
        await finish_demo_call(session.id, reservation, True)
    except RedisError:
        pass  # The active lease expires; the successful model call remains charged.
    try:
        await append_exchange(session, body.message, reply)
    except RedisError:
        return failure_response("HISTORY_STORE_UNAVAILABLE", "聊天记录暂时不可用。", request_id, 503, True)
    return ChatResponse(reply=reply, model=model, requestId=request_id)


async def validated_demo_session(authorization: str | None, request_id: str):
    try:
        token = token_from_authorization(authorization)
    except InvalidDemoToken:
        return None, failure_response("DEMO_SESSION_INVALID", "游客会话凭证无效。", request_id, 401)
    try:
        session = await asyncio.to_thread(find_demo_session, token)
    except (SQLAlchemyError, ValueError):
        return None, failure_response("SESSION_STORE_UNAVAILABLE", "游客会话暂时无法校验。", request_id, 503, True)
    if session is None:
        return None, failure_response("DEMO_SESSION_EXPIRED", "游客会话不存在或已过期。", request_id, 401)
    return session, None


@app.get("/api/v1/chat/history", response_model=ChatHistoryResponse)
async def chat_history(authorization: str | None = Header(default=None)) -> ChatHistoryResponse | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        messages = await read_history(session)
    except (RedisError, ValueError):
        return failure_response("HISTORY_STORE_UNAVAILABLE", "聊天记录暂时不可用。", request_id, 503, True)
    return ChatHistoryResponse(messages=messages)


@app.post("/api/v1/auth/register", response_model=AccountProfile, status_code=201)
async def register_account(body: AccountCredentials, request: Request) -> AccountProfile | JSONResponse:
    request_id = str(uuid4())
    try:
        allowed = await check_rate_limit("register", request.client.host if request.client else "unknown")
    except RedisError:
        return failure_response("AUTH_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    if not allowed:
        return failure_response("AUTH_RATE_LIMITED", "尝试过于频繁，请稍后再试。", request_id, 429, True)
    try:
        account = await asyncio.to_thread(create_account, str(body.email).lower(), body.password)
    except IntegrityError:
        return failure_response("ACCOUNT_EXISTS", "该邮箱已注册。", request_id, 409)
    except SQLAlchemyError:
        return failure_response("ACCOUNT_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    return AccountProfile(**account)


@app.post("/api/v1/auth/login", response_model=AccountTokenResponse)
async def login_account(body: AccountCredentials, request: Request) -> AccountTokenResponse | JSONResponse:
    request_id = str(uuid4())
    try:
        allowed = await check_rate_limit("login", request.client.host if request.client else "unknown")
    except RedisError:
        return failure_response("AUTH_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    if not allowed:
        return failure_response("AUTH_RATE_LIMITED", "尝试过于频繁，请稍后再试。", request_id, 429, True)
    try:
        account = await asyncio.to_thread(find_account_by_email, str(body.email).lower())
    except SQLAlchemyError:
        return failure_response("ACCOUNT_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    stored_hash = account["password_hash"] if account else DUMMY_HASH
    matches = await asyncio.to_thread(password_matches, stored_hash, body.password)
    if not account or not matches or account["status"] != "active":
        return failure_response("ACCOUNT_INVALID_CREDENTIALS", "邮箱或密码错误。", request_id, 401)
    try:
        token, expires_at = await issue_access_token(account["id"])
    except RedisError:
        return failure_response("AUTH_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    return AccountTokenResponse(token=token, expiresAt=expires_at)


@app.get("/api/v1/auth/me", response_model=AccountProfile)
async def current_account(authorization: str | None = Header(default=None)) -> AccountProfile | JSONResponse:
    request_id = str(uuid4())
    token = account_token_from_authorization(authorization)
    if token is None:
        return failure_response("ACCOUNT_SESSION_INVALID", "请先登录。", request_id, 401)
    try:
        account_id = await account_id_for_token(token)
    except RedisError:
        return failure_response("AUTH_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    if account_id is None:
        return failure_response("ACCOUNT_SESSION_EXPIRED", "登录已过期，请重新登录。", request_id, 401)
    try:
        account = await asyncio.to_thread(find_account_by_id, account_id)
    except SQLAlchemyError:
        return failure_response("ACCOUNT_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    if account is None or account["status"] != "active":
        return failure_response("ACCOUNT_SESSION_EXPIRED", "登录已过期，请重新登录。", request_id, 401)
    return AccountProfile(id=account["id"], email=account["email"])


@app.post("/api/v1/auth/logout", status_code=204)
async def logout_account(authorization: str | None = Header(default=None)) -> Response:
    request_id = str(uuid4())
    token = account_token_from_authorization(authorization)
    if token is None:
        return failure_response("ACCOUNT_SESSION_INVALID", "请先登录。", request_id, 401)
    try:
        if await account_id_for_token(token) is None:
            return failure_response("ACCOUNT_SESSION_EXPIRED", "登录已过期，请重新登录。", request_id, 401)
        await revoke_access_token(token)
    except RedisError:
        return failure_response("AUTH_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    return Response(status_code=204)


async def validated_account_session(authorization: str | None, request_id: str):
    token = account_token_from_authorization(authorization)
    if token is None:
        return None, failure_response("ACCOUNT_SESSION_INVALID", "请先登录。", request_id, 401)
    try:
        account_id = await account_id_for_token(token)
    except RedisError:
        return None, failure_response("AUTH_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    if account_id is None:
        return None, failure_response("ACCOUNT_SESSION_EXPIRED", "登录已过期，请重新登录。", request_id, 401)
    try:
        account = await asyncio.to_thread(find_account_by_id, account_id)
    except SQLAlchemyError:
        return None, failure_response("ACCOUNT_STORE_UNAVAILABLE", "账号服务暂时不可用。", request_id, 503, True)
    if account is None or account["status"] != "active":
        return None, failure_response("ACCOUNT_SESSION_EXPIRED", "登录已过期，请重新登录。", request_id, 401)
    return account_id, None


@app.post("/api/v1/account/chat", response_model=ChatResponse)
async def account_chat(body: ChatRequest, request: Request, authorization: str | None = Header(default=None)) -> ChatResponse | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        await account_history_available()
    except RedisError:
        return failure_response("HISTORY_STORE_UNAVAILABLE", "聊天记录暂时不可用。", request_id, 503, True)
    try:
        reservation = await reserve_model_call(body.message)
    except DemoQuotaExceeded as exc:
        return failure_response(exc.code, str(exc), request_id, 429, True)
    except (RedisError, ValueError):
        return failure_response("MODEL_BUDGET_UNAVAILABLE", "模型预算服务暂时不可用。", request_id, 503, True)
    try:
        reply, model = await complete(body.message, getattr(request.app.state, "deepseek_transport", None))
    except DeepSeekFailure as exc:
        try:
            await finish_model_call(reservation, exc.code == "MODEL_BAD_RESPONSE")
        except RedisError:
            return failure_response("MODEL_BUDGET_UNAVAILABLE", "模型失败且预算状态暂时无法恢复。", request_id, 503, True)
        status = 503 if exc.retryable or exc.code == "MODEL_NOT_CONFIGURED" else 502
        return failure_response(exc.code, str(exc), request_id, status, exc.retryable)
    except BaseException:
        await finish_model_call(reservation, False)
        raise
    try:
        await finish_model_call(reservation, True)
    except RedisError:
        pass  # The active lease expires; the successful model call remains charged.
    try:
        await append_account_exchange(account_id, body.message, reply)
    except RedisError:
        return failure_response("HISTORY_STORE_UNAVAILABLE", "聊天记录暂时不可用。", request_id, 503, True)
    return ChatResponse(reply=reply, model=model, requestId=request_id)


@app.get("/api/v1/account/chat/history", response_model=ChatHistoryResponse)
async def account_chat_history(authorization: str | None = Header(default=None)) -> ChatHistoryResponse | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        messages = await read_account_history(account_id)
    except (RedisError, ValueError):
        return failure_response("HISTORY_STORE_UNAVAILABLE", "聊天记录暂时不可用。", request_id, 503, True)
    return ChatHistoryResponse(messages=messages)


@app.post("/api/v1/{kind}/life/suggest", response_model=LifeSuggestionView)
async def life_suggestion(kind: str, body: LifeSuggestionRequest, request: Request,
                          authorization: str | None = Header(default=None)) -> LifeSuggestionView | JSONResponse:
    request_id = str(uuid4())
    if kind == "account":
        _, error = await validated_account_session(authorization, request_id)
        if error:
            return error
        session_id = None
    elif kind == "demo":
        session, error = await validated_demo_session(authorization, request_id)
        if error:
            return error
        session_id = session.id
    else:
        return failure_response("INVALID_IDENTITY", "不支持的身份类型。", request_id, 404)
    try:
        reservation = (await reserve_model_call(body.intent, overhead_bytes=4096, max_output_tokens=1200)
                       if session_id is None else
                       await reserve_demo_call(session_id, body.intent, overhead_bytes=4096, max_output_tokens=1200))
    except DemoQuotaExceeded as exc:
        return failure_response(exc.code, str(exc), request_id, 429, True)
    except (RedisError, SQLAlchemyError, ValueError):
        return failure_response("MODEL_BUDGET_UNAVAILABLE", "模型预算服务暂时不可用。", request_id, 503, True)
    try:
        suggestion = await suggest_life(body.intent, getattr(request.app.state, "deepseek_transport", None))
    except DeepSeekFailure as exc:
        try:
            charged = exc.code == "PLANNER_BAD_RESPONSE"
            if session_id is None:
                await finish_model_call(reservation, charged)
            else:
                await finish_demo_call(session_id, reservation, False, model_charged=charged)
        except (RedisError, SQLAlchemyError):
            return failure_response("MODEL_BUDGET_UNAVAILABLE", "智能拆解失败且预算状态暂时无法恢复。", request_id, 503, True)
        status = 503 if exc.retryable or exc.code == "MODEL_NOT_CONFIGURED" else 502
        return failure_response(exc.code, str(exc), request_id, status, exc.retryable)
    except BaseException:
        if session_id is None:
            await finish_model_call(reservation, False)
        else:
            await finish_demo_call(session_id, reservation, False)
        raise
    try:
        if session_id is None:
            await finish_model_call(reservation, True)
        else:
            await finish_demo_call(session_id, reservation, True)
    except RedisError:
        pass  # The active lease expires; the successful model call remains charged.
    return suggestion


@app.post("/api/v1/account/life/plans", status_code=201, response_model=LifePlanView)
async def account_life_plan(body: LifePlanCreate, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(create_plan, account_id, body)
    except LifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except IntegrityError:
        try:
            existing = await asyncio.to_thread(get_plan_by_key, account_id, body)
        except LifeConflict as exc:
            return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
        return existing if existing else failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)


@app.get("/api/v1/account/life/plans/{job_id}", response_model=LifePlanView)
async def account_life_plan_detail(job_id: int, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        plan = await asyncio.to_thread(get_plan, account_id, job_id)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return plan if plan else failure_response("PLAN_NOT_FOUND", "未找到该草案。", request_id, 404)


@app.put("/api/v1/account/life/plans/{job_id}", response_model=LifePlanView)
async def account_life_plan_edit(job_id: int, body: LifePlanEdit, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        plan = await asyncio.to_thread(edit_plan, account_id, job_id, body.items)
    except LifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return plan if plan else failure_response("PLAN_NOT_FOUND", "未找到该草案。", request_id, 404)


@app.post("/api/v1/account/life/plans/{job_id}/decision", response_model=LifePlanView)
async def account_life_plan_decision(job_id: int, body: LifePlanDecision, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        plan = await asyncio.to_thread(decide_plan, account_id, job_id, body.decision)
    except LifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return plan if plan else failure_response("PLAN_NOT_FOUND", "未找到该草案。", request_id, 404)


@app.get("/api/v1/account/life/items", response_model=LifeItemsView)
async def account_life_items(authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(list_items, account_id)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)


@app.get("/api/v1/account/permissions", response_model=list[PermissionGrantView])
async def account_permissions(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(list_permissions, account_id)
    except SQLAlchemyError:
        return failure_response("PERMISSION_STORE_UNAVAILABLE", "授权记录暂时不可用。", request_id, 503, True)


@app.post("/api/v1/account/permissions/revoke", response_model=PermissionRevokeView)
async def account_permission_revoke(body: PermissionRevoke, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return {"revoked": await asyncio.to_thread(revoke_permission, account_id, body.scope)}
    except SQLAlchemyError:
        return failure_response("PERMISSION_STORE_UNAVAILABLE", "授权记录暂时不可用。", request_id, 503, True)


@app.post("/api/v1/demo/life/plans", status_code=201, response_model=LifePlanView)
async def demo_life_plan(body: LifePlanCreate, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(demo_create_plan, session.id, body)
    except DemoLifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except IntegrityError:
        try:
            existing = await asyncio.to_thread(demo_get_plan_by_key, session.id, body)
        except DemoLifeConflict as exc:
            return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
        return existing if existing else failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)


@app.get("/api/v1/demo/life/plans/{job_id}", response_model=LifePlanView)
async def demo_life_plan_detail(job_id: int, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        plan = await asyncio.to_thread(demo_get_plan, session.id, job_id)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return plan if plan else failure_response("PLAN_NOT_FOUND", "未找到该草案。", request_id, 404)


@app.put("/api/v1/demo/life/plans/{job_id}", response_model=LifePlanView)
async def demo_life_plan_edit(job_id: int, body: LifePlanEdit, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        plan = await asyncio.to_thread(demo_edit_plan, session.id, job_id, body.items)
    except DemoLifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return plan if plan else failure_response("PLAN_NOT_FOUND", "未找到该草案。", request_id, 404)


@app.post("/api/v1/demo/life/plans/{job_id}/decision", response_model=LifePlanView)
async def demo_life_plan_decision(job_id: int, body: DemoLifePlanDecision, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        plan = await asyncio.to_thread(demo_decide_plan, session.id, job_id, body.decision)
    except DemoLifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return plan if plan else failure_response("PLAN_NOT_FOUND", "未找到该草案。", request_id, 404)


@app.get("/api/v1/demo/life/items", response_model=LifeItemsView)
async def demo_life_items(authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(demo_list_items, session.id)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)


@app.put("/api/v1/account/life/items/{kind}/{item_id}", response_model=LifeItemView)
async def account_life_item_update(kind: str, item_id: int, body: LifeItemUpdate, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        item = await asyncio.to_thread(update_item, "account", account_id, kind, item_id, body)
    except LifeItemConflict as exc:
        return failure_response("ITEM_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return item if item else failure_response("ITEM_NOT_FOUND", "未找到该事项。", request_id, 404)


@app.put("/api/v1/demo/life/items/{kind}/{item_id}", response_model=LifeItemView)
async def demo_life_item_update(kind: str, item_id: int, body: LifeItemUpdate, authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        item = await asyncio.to_thread(update_item, "demo", session.id, kind, item_id, body)
    except LifeItemConflict as exc:
        return failure_response("ITEM_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "生活任务暂时不可用。", request_id, 503, True)
    return item if item else failure_response("ITEM_NOT_FOUND", "未找到该事项。", request_id, 404)


@app.get("/api/v1/account/life/morning", response_model=MorningReportView)
async def account_morning(report_date: date = Query(alias="date"), authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(morning_report, "account", account_id, report_date)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "晨报暂时不可用。", request_id, 503, True)


@app.get("/api/v1/demo/life/morning", response_model=MorningReportView)
async def demo_morning(report_date: date = Query(alias="date"), authorization: str | None = Header(default=None)) -> dict | JSONResponse:
    request_id = str(uuid4())
    session, error = await validated_demo_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(morning_report, "demo", session.id, report_date)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "晨报暂时不可用。", request_id, 503, True)


async def _job_owner(kind: str, authorization: str | None, request_id: str):
    if kind == "account":
        return await validated_account_session(authorization, request_id)
    if kind == "demo":
        session, error = await validated_demo_session(authorization, request_id)
        return (session.id if session else None), error
    return None, failure_response("INVALID_OWNER", "不支持此身份类型。", request_id, 404)


@app.get("/api/v1/{kind}/life/jobs", response_model=list[JobSummaryView])
async def life_jobs(kind: str, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    owner_id, error = await _job_owner(kind, authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(list_jobs, kind, owner_id)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "任务状态暂时不可用。", request_id, 503, True)


@app.get("/api/v1/{kind}/life/jobs/{job_id}/events", response_model=list[JobEventView])
async def life_job_events(kind: str, job_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    owner_id, error = await _job_owner(kind, authorization, request_id)
    if error:
        return error
    try:
        events = await asyncio.to_thread(job_events, kind, owner_id, job_id)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "任务事件暂时不可用。", request_id, 503, True)
    return events if events is not None else failure_response("JOB_NOT_FOUND", "未找到该任务。", request_id, 404)


@app.post("/api/v1/{kind}/life/jobs/{job_id}/cancel", response_model=JobCancelView)
async def life_job_cancel(kind: str, job_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    owner_id, error = await _job_owner(kind, authorization, request_id)
    if error:
        return error
    try:
        changed = await asyncio.to_thread(cancel_job, kind, owner_id, job_id)
    except JobConflict as exc:
        return failure_response("JOB_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("LIFE_STORE_UNAVAILABLE", "取消任务暂时不可用。", request_id, 503, True)
    return {"cancelled": bool(changed)} if changed is not None else failure_response("JOB_NOT_FOUND", "未找到该任务。", request_id, 404)


@app.get("/api/v1/account/memory/candidates", response_model=list[MemoryCandidateView])
async def account_memory_candidates(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(list_candidates, account_id)
    except SQLAlchemyError:
        return failure_response("MEMORY_STORE_UNAVAILABLE", "记忆暂时不可用。", request_id, 503, True)


@app.post("/api/v1/account/memory/candidates", status_code=201, response_model=MemoryCandidateView)
async def account_memory_create(body: MemoryCandidateCreate, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(create_candidate, account_id, body.summary, body.evidenceRef, body.purpose, body.expiresAt)
    except MemoryConflict as exc:
        return failure_response("MEMORY_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("MEMORY_STORE_UNAVAILABLE", "记忆暂时不可用。", request_id, 503, True)


@app.put("/api/v1/account/memory/candidates/{candidate_id}", response_model=MemoryCandidateView)
async def account_memory_edit(candidate_id: int, body: MemoryCandidateEdit, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        result = await asyncio.to_thread(edit_candidate, account_id, candidate_id, body.summary, body.purpose, body.expiresAt)
    except MemoryConflict as exc:
        return failure_response("MEMORY_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("MEMORY_STORE_UNAVAILABLE", "记忆暂时不可用。", request_id, 503, True)
    return result if result else failure_response("MEMORY_NOT_FOUND", "未找到该记忆。", request_id, 404)


@app.post("/api/v1/account/memory/candidates/{candidate_id}/decision", response_model=MemoryCandidateView)
async def account_memory_decide(candidate_id: int, body: MemoryDecision, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        result = await asyncio.to_thread(decide_candidate, account_id, candidate_id, body.decision == "confirm")
    except MemoryConflict as exc:
        return failure_response("MEMORY_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("MEMORY_STORE_UNAVAILABLE", "记忆暂时不可用。", request_id, 503, True)
    return result if result else failure_response("MEMORY_NOT_FOUND", "未找到该记忆。", request_id, 404)


@app.post("/api/v1/account/memory/candidates/{candidate_id}/revoke", response_model=MemoryRevokeView)
async def account_memory_revoke(candidate_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        revoked = await asyncio.to_thread(revoke_memory, account_id, candidate_id)
    except SQLAlchemyError:
        return failure_response("MEMORY_STORE_UNAVAILABLE", "记忆暂时不可用。", request_id, 503, True)
    return {"revoked": bool(revoked)} if revoked is not None else failure_response("MEMORY_NOT_FOUND", "未找到该记忆。", request_id, 404)


@app.delete("/api/v1/account/memory/candidates/{candidate_id}", response_model=MemoryDeleteView)
async def account_memory_delete(candidate_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        deleted = await asyncio.to_thread(delete_memory, account_id, candidate_id)
    except SQLAlchemyError:
        return failure_response("MEMORY_STORE_UNAVAILABLE", "记忆暂时不可用。", request_id, 503, True)
    return {"deleted": True} if deleted else failure_response("MEMORY_NOT_FOUND", "未找到该记忆。", request_id, 404)


@app.post("/api/v1/account/pc/pair", response_model=PairCodeView)
async def account_pc_pair(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(create_pair_code, account_id)
    except SQLAlchemyError:
        return failure_response("PC_PAIR_UNAVAILABLE", "暂时无法创建配对码。", request_id, 503, True)


@app.post("/api/v1/pc/pair", response_model=WorkerTokenView)
async def pc_pair(body: PairConsume):
    request_id = str(uuid4())
    try:
        return await asyncio.to_thread(consume_pair_code, body.code)
    except PairFailure as exc:
        return failure_response("PC_PAIR_INVALID", str(exc), request_id, 401)
    except SQLAlchemyError:
        return failure_response("PC_PAIR_UNAVAILABLE", "暂时无法完成配对。", request_id, 503, True)


async def validated_worker(authorization: str | None, request_id: str, heartbeat: bool = False):
    if not authorization or not authorization.startswith("Bearer "):
        return None, failure_response("PC_TOKEN_INVALID", "PC 凭证缺失。", request_id, 401)
    try:
        identity = await asyncio.to_thread(worker_identity, authorization[7:].strip(), heartbeat)
    except SQLAlchemyError:
        return None, failure_response("PC_AUTH_UNAVAILABLE", "暂时无法校验 PC 凭证。", request_id, 503, True)
    if identity is None:
        return None, failure_response("PC_TOKEN_INVALID", "PC 凭证无效或已撤销。", request_id, 401)
    return identity, None


@app.post("/api/v1/pc/heartbeat", response_model=HeartbeatView)
async def pc_heartbeat(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    identity, error = await validated_worker(authorization, request_id, True)
    if error:
        return error
    return {"online": True, "deviceId": identity[1]}


@app.get("/api/v1/account/pc/devices", response_model=list[DeviceView])
async def account_pc_devices(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(list_devices, account_id)
    except SQLAlchemyError:
        return failure_response("PC_AUTH_UNAVAILABLE", "暂时无法读取设备。", request_id, 503, True)


@app.post("/api/v1/account/pc/devices/{device_id}/revoke", response_model=RevokeDeviceView)
async def account_pc_revoke(device_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        revoked = await asyncio.to_thread(revoke_device, account_id, device_id)
    except SQLAlchemyError:
        return failure_response("PC_AUTH_UNAVAILABLE", "暂时无法撤销设备。", request_id, 503, True)
    return {"revoked": bool(revoked)} if revoked is not None else failure_response("PC_DEVICE_NOT_FOUND", "未找到该设备。", request_id, 404)


@app.post("/api/v1/account/pc/study", status_code=201, response_model=StudyJobView)
async def account_study_create(body: StudyJobCreate, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(create_study_job, account_id, body.query, body.idempotencyKey)
    except StudyConflict as exc:
        return failure_response("STUDY_CONFLICT", str(exc), request_id, 409)
    except IntegrityError:
        try:
            return await asyncio.to_thread(create_study_job, account_id, body.query, body.idempotencyKey)
        except StudyConflict as exc:
            return failure_response("STUDY_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "学习任务暂时不可用。", request_id, 503, True)


@app.get("/api/v1/account/pc/study", response_model=list[StudyJobView])
async def account_study_list(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        return await asyncio.to_thread(list_study_jobs, account_id)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "学习任务暂时不可用。", request_id, 503, True)


@app.get("/api/v1/account/pc/study/{job_id}", response_model=StudyJobView)
async def account_study_detail(job_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        job = await asyncio.to_thread(get_study_job, account_id, job_id)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "学习任务暂时不可用。", request_id, 503, True)
    return job if job else failure_response("STUDY_NOT_FOUND", "未找到学习任务。", request_id, 404)


@app.post("/api/v1/account/pc/study/{job_id}/suggest", response_model=LifeSuggestionView)
async def account_study_suggest(job_id: int, request: Request, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        job = await asyncio.to_thread(get_study_job, account_id, job_id)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "学习任务暂时不可用。", request_id, 503, True)
    if not job:
        return failure_response("STUDY_NOT_FOUND", "未找到学习任务。", request_id, 404)
    excerpts = (job.get("result") or {}).get("excerpts") or []
    if job["status"] != "succeeded" or not excerpts:
        return failure_response("STUDY_CONFLICT", "请等待 PC 返回可引用的资料片段。", request_id, 409)
    try:
        reservation = await reserve_model_call(study_prompt(job["query"], excerpts),
                                               overhead_bytes=4096, max_output_tokens=1200)
    except DemoQuotaExceeded as exc:
        return failure_response(exc.code, str(exc), request_id, 429, True)
    except (RedisError, ValueError):
        return failure_response("MODEL_BUDGET_UNAVAILABLE", "模型预算服务暂时不可用。", request_id, 503, True)
    try:
        suggestion = await suggest_study_life(job["query"], excerpts,
                                              getattr(request.app.state, "deepseek_transport", None))
    except DeepSeekFailure as exc:
        try:
            await finish_model_call(reservation, exc.code == "PLANNER_BAD_RESPONSE")
        except RedisError:
            return failure_response("MODEL_BUDGET_UNAVAILABLE", "智能拆解失败且预算状态暂时无法恢复。", request_id, 503, True)
        status = 503 if exc.retryable or exc.code == "MODEL_NOT_CONFIGURED" else 502
        return failure_response(exc.code, str(exc), request_id, status, exc.retryable)
    except BaseException:
        await finish_model_call(reservation, False)
        raise
    try:
        await finish_model_call(reservation, True)
    except RedisError:
        pass  # The active lease expires; the successful model call remains charged.
    return suggestion


@app.post("/api/v1/account/pc/study/{job_id}/draft", response_model=LifePlanView)
async def account_study_draft(job_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        job = await asyncio.to_thread(get_study_job, account_id, job_id)
        if not job:
            return failure_response("STUDY_NOT_FOUND", "未找到学习任务。", request_id, 404)
        if job["status"] != "succeeded" or not job["result"] or not job["result"]["excerpts"]:
            return failure_response("STUDY_CONFLICT", "请等待 PC 返回可引用的资料片段。", request_id, 409)
        items = [LifeItemDraft(kind="task", title=f"复习 {job['query']}：阅读 {item['source']} 第 {item['page']} 页"[:255])
                 for item in job["result"]["excerpts"]]
        body = LifePlanCreate(intent=f"根据本地检索安排学习：{job['query']}"[:500],
                              idempotencyKey=f"study_{job_id}_draft", items=items)
        return await asyncio.to_thread(create_plan, account_id, body)
    except LifeConflict as exc:
        return failure_response("PLAN_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "暂时无法生成学习草案。", request_id, 503, True)


@app.post("/api/v1/account/pc/study/{job_id}/retry", response_model=StudyJobView)
async def account_study_retry(job_id: int, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    account_id, error = await validated_account_session(authorization, request_id)
    if error:
        return error
    try:
        job = await asyncio.to_thread(retry_study_job, account_id, job_id)
    except StudyConflict as exc:
        return failure_response("STUDY_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "学习任务暂时不可用。", request_id, 503, True)
    return job if job else failure_response("STUDY_NOT_FOUND", "未找到学习任务。", request_id, 404)


@app.post("/api/v1/pc/study/claim", response_model=StudyClaimResponse)
async def pc_study_claim(authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    identity, error = await validated_worker(authorization, request_id, True)
    if error:
        return error
    try:
        job = await asyncio.to_thread(claim_study_job, *identity)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "暂时无法领取任务。", request_id, 503, True)
    return {"job": job}


@app.post("/api/v1/pc/study/{job_id}/complete", response_model=StudyJobView)
async def pc_study_complete(job_id: int, body: StudyOutcome, authorization: str | None = Header(default=None)):
    request_id = str(uuid4())
    identity, error = await validated_worker(authorization, request_id, True)
    if error:
        return error
    try:
        job = await asyncio.to_thread(complete_study_job, *identity, job_id, body.model_dump())
    except StudyConflict as exc:
        return failure_response("STUDY_CONFLICT", str(exc), request_id, 409)
    except SQLAlchemyError:
        return failure_response("STUDY_STORE_UNAVAILABLE", "暂时无法提交结果。", request_id, 503, True)
    return job if job else failure_response("STUDY_NOT_FOUND", "未找到学习任务。", request_id, 404)
