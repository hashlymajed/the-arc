"""Tests for FastAPI routes — httpx TestClient + mocked DB/AI."""
import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture()
def client(db_path):
    """TestClient with isolated DB and no AI calls needed for most tests."""
    with patch("api.db.DB_PATH", db_path):
        from app import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── GET /api/draft/{id} ───────────────────────────────────────────────────────

def test_should_return_404_for_missing_draft(client):
    resp = client.get("/api/draft/99999")
    assert resp.status_code == 404


def test_should_return_draft_by_id(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "Test Draft", "channel": "LinkedIn", "audience": "Media", "tone": "Confident", "brief": "test", "vault_context": "", "content": "body"})
    resp = client.get(f"/api/draft/{draft_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test Draft"


# ── POST /api/draft/save ──────────────────────────────────────────────────────

def test_should_create_new_draft_and_return_id(client):
    resp = client.post("/api/draft/save", json={
        "title": "New Press Release",
        "channel": "Press Release",
        "brief": "Q2 announcement",
        "content": "",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["id"], int)


def test_should_update_existing_draft(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "Old Title", "channel": "LinkedIn", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    resp = client.post("/api/draft/save", json={"id": draft_id, "title": "New Title"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── POST /api/draft/submit ────────────────────────────────────────────────────

def test_should_submit_draft_and_set_status_to_review(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, get_draft
        draft_id = create_draft({"title": "To Review", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    resp = client.post("/api/draft/submit", json={"id": draft_id})
    assert resp.status_code == 200
    with patch("api.db.DB_PATH", db_path):
        from api.db import get_draft
        draft = get_draft(draft_id)
    assert draft["status"] == "review"


def test_should_return_error_when_submit_has_no_id(client):
    resp = client.post("/api/draft/submit", json={})
    assert resp.status_code == 400


# ── POST /api/draft/status ────────────────────────────────────────────────────

def test_should_update_draft_status_to_approved(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "Approve Me", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    resp = client.post("/api/draft/status", json={"id": draft_id, "status": "approved"})
    assert resp.status_code == 200
    with patch("api.db.DB_PATH", db_path):
        from api.db import get_draft
        assert get_draft(draft_id)["status"] == "approved"


# ── GET /api/stats ────────────────────────────────────────────────────────────

def test_should_return_stats_with_correct_counts(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, update_draft
        id1 = create_draft({"title": "D1", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        id2 = create_draft({"title": "D2", "channel": "LinkedIn", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        update_draft(id2, {"status": "review"})
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["drafts"] == 1
    assert data["pending"] == 1


# ── GET /api/settings ─────────────────────────────────────────────────────────

def test_should_return_empty_settings_dict(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ── POST /api/settings ────────────────────────────────────────────────────────

def test_should_save_and_return_ok(client):
    resp = client.post("/api/settings", json={"org_name": "Aldar", "llm_model": "gemini-2.5-flash"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── POST /api/draft/generate (mocked AI) ─────────────────────────────────────

def test_should_return_generated_content_from_ai(client, db_path, mock_gemini, settings):
    mock_gemini.models.generate_content.return_value.text = "Generated press release body."
    with patch("api.db.DB_PATH", db_path):
        from api.db import save_settings
        save_settings(settings)
    with patch("api.vault.search", return_value=[]):
        resp = client.post("/api/draft/generate", json={
            "channel": "Press Release",
            "brief": "Announce new tower",
            "audience": "Media",
            "tone": "Confident",
        })
    assert resp.status_code == 200
    assert "Generated press release body." in resp.json()["content"]


def test_should_return_500_when_ai_raises(client, db_path, settings):
    with patch("api.db.DB_PATH", db_path):
        from api.db import save_settings
        save_settings(settings)
    with patch("api.ai.generate", side_effect=Exception("AI failure")):
        with patch("api.vault.search", return_value=[]):
            resp = client.post("/api/draft/generate", json={"channel": "Press Release", "brief": "test"})
    assert resp.status_code == 500
    assert "error" in resp.json()


# ── Author & Activity ─────────────────────────────────────────────────────────

def test_should_store_author_when_creating_draft(client):
    resp = client.post("/api/draft/save", json={"title": "By Sara", "channel": "LinkedIn", "author": "sara@aldar.com"})
    assert resp.status_code == 200
    draft_id = resp.json()["id"]
    draft = client.get(f"/api/draft/{draft_id}").json()
    assert draft["author"] == "sara@aldar.com"


def test_should_log_created_activity_on_save(client):
    resp = client.post("/api/draft/save", json={"title": "New Draft", "channel": "Press Release", "author": "sara@aldar.com"})
    draft_id = resp.json()["id"]
    activity = client.get(f"/api/draft/{draft_id}/activity").json()
    assert any(a["action"] == "created" and a["author"] == "sara@aldar.com" for a in activity)


def test_should_log_edited_activity_on_update(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    client.post("/api/draft/save", json={"id": draft_id, "title": "Updated", "author": "khalid@aldar.com"})
    activity = client.get(f"/api/draft/{draft_id}/activity").json()
    assert any(a["action"] == "edited" and a["author"] == "khalid@aldar.com" for a in activity)


def test_should_log_submitted_for_review_activity(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    client.post("/api/draft/submit", json={"id": draft_id, "author": "sara@aldar.com"})
    activity = client.get(f"/api/draft/{draft_id}/activity").json()
    assert any(a["action"] == "submitted_for_review" for a in activity)


def test_should_log_status_change_activity(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    client.post("/api/draft/status", json={"id": draft_id, "status": "approved", "author": "khalid@aldar.com", "review_notes": "LGTM"})
    activity = client.get(f"/api/draft/{draft_id}/activity").json()
    assert any(a["action"] == "approved" and a["notes"] == "LGTM" for a in activity)


def test_should_return_404_for_activity_on_missing_draft(client):
    resp = client.get("/api/draft/99999/activity")
    assert resp.status_code == 404


def test_should_return_empty_activity_for_draft_with_no_events(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
    resp = client.get(f"/api/draft/{draft_id}/activity")
    assert resp.status_code == 200
    assert resp.json() == []


# ── GET /api/tags ─────────────────────────────────────────────────────────────

def test_should_return_empty_tag_list(client):
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert resp.json() == []


def test_should_list_created_tags(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_tag
        create_tag("Press")
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert any(t["name"] == "Press" for t in resp.json())


# ── POST /api/tags ────────────────────────────────────────────────────────────

def test_should_create_tag_via_route(client):
    resp = client.post("/api/tags", json={"name": "Campaign", "color": "#10B981"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["id"], int)


def test_should_return_400_when_tag_name_missing(client):
    resp = client.post("/api/tags", json={"color": "#000"})
    assert resp.status_code == 400


# ── DELETE /api/tags/{id} ─────────────────────────────────────────────────────

def test_should_delete_tag_via_route(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_tag
        tag_id = create_tag("DeleteMe")
    resp = client.delete(f"/api/tags/{tag_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── GET /api/draft/{id}/tags ──────────────────────────────────────────────────

def test_should_return_404_for_tags_on_missing_draft(client):
    resp = client.get("/api/draft/99999/tags")
    assert resp.status_code == 404


def test_should_return_tags_for_draft(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag, add_draft_tag
        draft_id = create_draft({"title": "D", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Region")
        add_draft_tag(draft_id, tag_id)
    resp = client.get(f"/api/draft/{draft_id}/tags")
    assert resp.status_code == 200
    assert any(t["name"] == "Region" for t in resp.json())


# ── POST /api/draft/{id}/tags/{tag_id} ───────────────────────────────────────

def test_should_add_tag_to_draft(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag
        draft_id = create_draft({"title": "D", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Linked")
    resp = client.post(f"/api/draft/{draft_id}/tags/{tag_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_should_return_404_when_adding_tag_to_missing_draft(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_tag
        tag_id = create_tag("Orphan")
    resp = client.post(f"/api/draft/99999/tags/{tag_id}")
    assert resp.status_code == 404


# ── DELETE /api/draft/{id}/tags/{tag_id} ─────────────────────────────────────

def test_should_remove_tag_from_draft(client, db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag, add_draft_tag
        draft_id = create_draft({"title": "D", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Unlink")
        add_draft_tag(draft_id, tag_id)
    resp = client.delete(f"/api/draft/{draft_id}/tags/{tag_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
