"""Opaque guest credentials; persist only the token digest."""

import hashlib
import re
import secrets


TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")


class InvalidDemoToken(ValueError):
    """The caller did not supply a usable guest bearer token."""


def issue_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, token_digest(token)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def token_from_authorization(authorization: str | None) -> str:
    if not authorization:
        raise InvalidDemoToken("缺少游客会话凭证。")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not TOKEN_PATTERN.fullmatch(token):
        raise InvalidDemoToken("游客会话凭证无效。")
    return token
