# Dengvis / Jarvis 本地开发版

产品依据为 [`docs/Jarvis_产品需求文档_V2.docx`](docs/Jarvis_产品需求文档_V2.docx)。M0/M1 已完成本地验收；M2/M3 的主要数据流程已实现，M4/M5 仍有设备、正式资产和公网验收缺口。本轮不制作或修改 3D 模型。

## 目录

- `server/`：FastAPI、DeepSeek 服务端请求、游客与正式账号身份、隔离历史和测试。
- `web/`：React 游客入口，包含对话、生活任务、任务记录、语音回退和已有核心 GLB 展示。
- `shared/contracts/`：由 Pydantic 模型导出的 JSON Schema。
- `android/`：Kotlin/Compose 账号端，包含聊天、生活任务、记忆、学习、语音输入与 HUD；部分新增页面已在模拟器验收，真机仍待验收。
- `pc-worker/`：出站连接的本地 PDF 检索进程；中文语义检索、扫描页 OCR、配对、领取与结果回传已完成本地联调。
- `Jarvis_Codex_交付包/`：原始设计文档与唯一视觉母版。

`infra/` 包含 MySQL 初始 SQL、Alembic 迁移、只读结构核对与 HTTPS/ECS 审阅模板；正式部署尚未进行。

## 本地启动（PowerShell）

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
Copy-Item .env.example .env
# 在 .env 中填写 DEEPSEEK_API_KEY；不要提交该文件
Set-Location web
& 'C:\Program Files\nodejs\npm.cmd' install --cache ..\.npm-cache
Set-Location ..
.\scripts\start-local.ps1
```

访问 `http://127.0.0.1:5173/`。后端健康检查在 `http://127.0.0.1:8000/health`。结束运行：`.\scripts\stop-local.ps1`。如 Node 不在上述默认路径，可直接在 `web/` 使用本机 `npm install` 和 `npm run dev`，后端在 `server/` 使用 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。

## 验证

```powershell
Set-Location server
..\.venv\Scripts\python.exe -m pytest tests -q
..\.venv\Scripts\python.exe -m scripts.export_contracts
Set-Location ..\web
& 'C:\Program Files\nodejs\npm.cmd' run build
```

2026-10-19 当前正式项目目录的后端 35 项测试、PC Worker 16 项测试、Web 构建与 Android 调试版离线构建通过；新增验证没有真实 DeepSeek 调用。Android API 35 模拟器完成生活事项审批/修改/完成、晨报、记忆审批/撤销/删除、PC 配对、本地 PDF 学习草案批准、设备撤销与令牌失效；Web 游客使用真实本地 API 完成草案批准、事项完成、晨报、刷新后恢复草案与拒绝。测试账号及游客会话的关联数据均已清理。游客默认 10 次，账号和游客共用模型并发、每日 token 和保守费用预留上限；公网配置、真实账单核对、Android 真机与 3D 验收仍未完成。

## 敏感信息

`.env`、真实用户数据、模型 Key 不提交。Web 不保存 Key，浏览器发出的消息由后端转发给 DeepSeek；当前请仅使用非敏感测试内容。
