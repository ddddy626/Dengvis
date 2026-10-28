import os

import httpx
from dotenv import load_dotenv


load_dotenv()


class DeepSeekFailure(Exception):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


async def complete(message: str, transport: httpx.AsyncBaseTransport | None = None) -> tuple[str, str]:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise DeepSeekFailure("MODEL_NOT_CONFIGURED", "服务端尚未配置 DeepSeek API Key。", False)

    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是 Jarvis 的早期文字助手。准确、克制地回答。你尚不能执行日程、文件或外部应用操作，不得声称已执行。"},
            {"role": "user", "content": message},
        ],
        "stream": False,
        "max_tokens": 800,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise DeepSeekFailure("MODEL_TIMEOUT", "模型响应超时，请稍后重试。", True) from exc
    except httpx.RequestError as exc:
        raise DeepSeekFailure("MODEL_UNAVAILABLE", "暂时无法连接模型服务。", True) from exc

    if response.status_code != 200:
        if response.status_code in (429, 500, 503):
            raise DeepSeekFailure("MODEL_BUSY", "模型服务暂时繁忙，请稍后重试。", True)
        if response.status_code in (401, 402, 403):
            raise DeepSeekFailure("MODEL_CREDENTIALS", "模型服务配置或额度不可用。", False)
        raise DeepSeekFailure("MODEL_ERROR", "模型服务返回错误。", False)

    try:
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty content")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise DeepSeekFailure("MODEL_BAD_RESPONSE", "模型返回了无法读取的结果。", True) from exc
    return content, model
