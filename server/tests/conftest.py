"""Prevent test runs from reaching the paid model endpoint."""

import pytest


@pytest.fixture(autouse=True)
def isolate_model_endpoint(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://127.0.0.1:9")
