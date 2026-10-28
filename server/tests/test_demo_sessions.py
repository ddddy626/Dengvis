"""Integration checks against the dedicated local MySQL database."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.demo_sessions import session_engine
from app.demo_tokens import token_digest
from app.main import app


def test_two_sessions_are_independent_and_expire():
    tokens: list[str] = []
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/demo/session")
            second = client.post("/api/v1/demo/session")
            assert first.status_code == second.status_code == 201
            first_data, second_data = first.json(), second.json()
            tokens.extend((first_data["token"], second_data["token"]))
            assert first_data["token"] != second_data["token"]
            assert first_data["mode"] == second_data["mode"] == "demo"

            expiry = datetime.fromisoformat(first_data["expiresAt"].replace("Z", "+00:00"))
            remaining = expiry - datetime.now(timezone.utc)
            assert timedelta(hours=23, minutes=59) < remaining <= timedelta(hours=24)

            for data in (first_data, second_data):
                status = client.get(
                    "/api/v1/demo/session",
                    headers={"Authorization": f"Bearer {data['token']}"},
                )
                assert status.status_code == 200
                assert status.json() == {"expiresAt": data["expiresAt"], "mode": "demo"}

            with session_engine().begin() as connection:
                rows = connection.execute(
                    text("SELECT session_token_hash FROM demo_sessions WHERE session_token_hash IN (:first, :second)"),
                    {"first": token_digest(tokens[0]), "second": token_digest(tokens[1])},
                ).scalars().all()
                assert set(rows) == {token_digest(token) for token in tokens}
                connection.execute(
                    text("UPDATE demo_sessions SET expires_at = UTC_TIMESTAMP(3) - INTERVAL 1 SECOND WHERE session_token_hash = :digest"),
                    {"digest": token_digest(tokens[0])},
                )

            expired = client.get("/api/v1/demo/session", headers={"Authorization": f"Bearer {tokens[0]}"})
            active = client.get("/api/v1/demo/session", headers={"Authorization": f"Bearer {tokens[1]}"})
            assert expired.status_code == 401
            assert expired.json()["code"] == "DEMO_SESSION_EXPIRED"
            assert active.status_code == 200
    finally:
        if tokens:
            with session_engine().begin() as connection:
                connection.execute(
                    text("DELETE FROM demo_sessions WHERE session_token_hash IN (:first, :second)"),
                    {"first": token_digest(tokens[0]), "second": token_digest(tokens[-1])},
                )


def test_missing_and_forged_token_are_rejected():
    with TestClient(app) as client:
        missing = client.get("/api/v1/demo/session")
        forged = client.get("/api/v1/demo/session", headers={"Authorization": "Bearer " + "a" * 43})
    assert missing.status_code == forged.status_code == 401
    assert missing.json()["code"] == "DEMO_SESSION_INVALID"
    assert forged.json()["code"] == "DEMO_SESSION_EXPIRED"
