"""Shared fixtures for The Arc test suite."""
import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture()
def db_path(tmp_path):
    """Isolated SQLite DB per test."""
    path = str(tmp_path / "arc_test.db")
    with patch("api.db.DB_PATH", path):
        from api.db import init_db
        init_db()
        yield path


@pytest.fixture()
def mock_gemini():
    """Mocked google-genai client that returns configurable text."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "mocked AI response"
    mock_client.models.generate_content.return_value = mock_response
    with patch("api.ai._client", return_value=mock_client):
        yield mock_client


@pytest.fixture()
def settings():
    return {
        "gemini_api_key": "test-key-123",
        "llm_model": "gemini-2.5-flash",
        "org_name": "Aldar Properties",
        "brand_voice": "confident, premium",
        "max_tokens": "2048",
        "temperature": "0.4",
    }
