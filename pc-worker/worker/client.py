"""Outbound-only PC Worker HTTP client."""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class WorkerApiError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def checked_server(value: str) -> str:
    address = value.strip().rstrip("/")
    parsed = urlsplit(address)
    try:
        valid_origin = (parsed.hostname and parsed.port != 0 and parsed.username is None and parsed.password is None
                        and not parsed.path and not parsed.query and not parsed.fragment
                        and not any(char.isspace() for char in address))
    except ValueError:
        valid_origin = False
    if parsed.scheme == "https" and valid_origin:
        return address
    if parsed.scheme == "http" and valid_origin and parsed.hostname in ("localhost", "127.0.0.1"):
        return address
    raise WorkerApiError("PC Worker 仅连接 HTTPS 服务；本机调试可使用 localhost。")


def request(server: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    address = checked_server(server)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    operation = Request(address + path, data=payload, headers=headers, method="POST" if body is not None else "GET")
    try:
        with build_opener(_NoRedirect()).open(operation, timeout=40) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            message = json.load(exc).get("message", "服务拒绝请求。")
        except (ValueError, AttributeError):
            message = "服务拒绝请求。"
        raise WorkerApiError(f"{message} (HTTP {exc.code})") from exc
    except URLError as exc:
        raise WorkerApiError("无法连接服务端，请检查网络和地址。") from exc


def save_token(path: Path, token: str) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise WorkerApiError("令牌文件已存在；请先在客户端撤销旧设备并指定新文件。")
    with path.open("x", encoding="utf-8") as target:
        target.write(token)
    path.chmod(0o600)


def read_token(path: Path) -> str:
    token = path.expanduser().read_text(encoding="utf-8").strip()
    if not token:
        raise WorkerApiError("令牌文件为空。")
    return token
