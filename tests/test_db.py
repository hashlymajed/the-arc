"""Tests for api/db.py — TDD London School, in-memory SQLite."""
import pytest
from unittest.mock import patch


# ── Drafts ────────────────────────────────────────────────────────────────────

def test_should_create_draft_and_return_integer_id(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft
        draft_id = create_draft({
            "title": "Q1 Launch",
            "channel": "Press Release",
            "audience": "Media",
            "tone": "Premium",
            "brief": "Announce Q1 results",
            "vault_context": "",
            "content": "",
        })
    assert isinstance(draft_id, int)
    assert draft_id > 0


def test_should_retrieve_draft_by_id(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, get_draft
        draft_id = create_draft({
            "title": "Sustainability Report",
            "channel": "LinkedIn",
            "audience": "Investors",
            "tone": "Confident",
            "brief": "Annual ESG update",
            "vault_context": "",
            "content": "Draft body here",
        })
        draft = get_draft(draft_id)

    assert draft["title"] == "Sustainability Report"
    assert draft["channel"] == "LinkedIn"
    assert draft["status"] == "draft"


def test_should_return_none_for_missing_draft(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import get_draft
        result = get_draft(99999)
    assert result is None


def test_should_list_drafts_ordered_by_updated_at(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, list_drafts
        create_draft({"title": "First", "channel": "LinkedIn", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        create_draft({"title": "Second", "channel": "LinkedIn", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        drafts = list_drafts()

    assert len(drafts) == 2
    assert drafts[0]["title"] == "Second"  # most recent first


def test_should_filter_drafts_by_status(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, update_draft, list_drafts
        id1 = create_draft({"title": "Draft One", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        id2 = create_draft({"title": "Draft Two", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        update_draft(id2, {"status": "review"})
        drafts = list_drafts(status="draft")

    assert len(drafts) == 1
    assert drafts[0]["id"] == id1


def test_should_update_only_allowed_fields(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, update_draft, get_draft
        draft_id = create_draft({"title": "Original", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        update_draft(draft_id, {"title": "Updated Title", "status": "review", "injected_field": "malicious"})
        draft = get_draft(draft_id)

    assert draft["title"] == "Updated Title"
    assert draft["status"] == "review"
    assert "injected_field" not in draft


def test_should_update_draft_ignores_empty_field_dict(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, update_draft, get_draft
        draft_id = create_draft({"title": "Safe", "channel": "LinkedIn", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        update_draft(draft_id, {"injected_field": "bad"})  # no allowed fields
        draft = get_draft(draft_id)

    assert draft["title"] == "Safe"


def test_should_group_drafts_by_status(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, update_draft, drafts_by_status
        id1 = create_draft({"title": "A", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        id2 = create_draft({"title": "B", "channel": "LinkedIn", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        update_draft(id2, {"status": "review"})
        buckets = drafts_by_status()

    assert any(d["id"] == id1 for d in buckets["draft"])
    assert any(d["id"] == id2 for d in buckets["review"])


# ── Settings ──────────────────────────────────────────────────────────────────

def test_should_save_and_retrieve_settings(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import save_settings, get_settings
        save_settings({"gemini_api_key": "abc123", "org_name": "Aldar"})
        result = get_settings()

    assert result["gemini_api_key"] == "abc123"
    assert result["org_name"] == "Aldar"


def test_should_overwrite_existing_setting_on_save(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import save_settings, get_settings
        save_settings({"llm_model": "gemini-2.0"})
        save_settings({"llm_model": "gemini-2.5-flash"})
        result = get_settings()

    assert result["llm_model"] == "gemini-2.5-flash"


def test_should_return_empty_dict_when_no_settings(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import get_settings
        result = get_settings()

    assert result == {}


# ── Author & Activity ─────────────────────────────────────────────────────────

def test_should_store_author_on_draft_create(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, get_draft
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": "", "author": "sara@aldar.com"})
        draft = get_draft(draft_id)
    assert draft["author"] == "sara@aldar.com"


def test_should_allow_null_author(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, get_draft
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        draft = get_draft(draft_id)
    assert draft["author"] is None


def test_should_log_activity_and_retrieve_it(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, log_activity, get_draft_activity
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        log_activity(draft_id, "sara@aldar.com", "created")
        log_activity(draft_id, "khalid@aldar.com", "submitted_for_review")
        activity = get_draft_activity(draft_id)
    assert len(activity) == 2
    assert activity[0]["action"] == "created"
    assert activity[0]["author"] == "sara@aldar.com"
    assert activity[1]["action"] == "submitted_for_review"


def test_should_return_empty_activity_for_new_draft(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, get_draft_activity
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        activity = get_draft_activity(draft_id)
    assert activity == []


def test_should_cascade_delete_activity_when_draft_deleted(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, log_activity, get_conn
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        log_activity(draft_id, "system", "created")
        conn = get_conn()
        conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        conn.commit()
        rows = conn.execute("SELECT * FROM draft_activity WHERE draft_id = ?", (draft_id,)).fetchall()
        conn.close()
    assert rows == []


def test_should_store_notes_in_activity(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, log_activity, get_draft_activity
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        log_activity(draft_id, "khalid@aldar.com", "approved", "Looks good, approved for publishing")
        activity = get_draft_activity(draft_id)
    assert activity[0]["notes"] == "Looks good, approved for publishing"


# ── Tags ──────────────────────────────────────────────────────────────────────

def test_should_create_tag_and_return_id(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_tag
        tag_id = create_tag("Press", "#3B82F6")
    assert isinstance(tag_id, int)
    assert tag_id > 0


def test_should_list_tags_ordered_by_name(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_tag, list_tags
        create_tag("Zebra")
        create_tag("Alpha")
        tags = list_tags()
    assert tags[0]["name"] == "Alpha"
    assert tags[1]["name"] == "Zebra"


def test_should_delete_tag(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_tag, delete_tag, list_tags
        tag_id = create_tag("Temp")
        delete_tag(tag_id)
        tags = list_tags()
    assert not any(t["id"] == tag_id for t in tags)


def test_should_add_and_get_draft_tags(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag, add_draft_tag, get_draft_tags
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Campaign")
        add_draft_tag(draft_id, tag_id)
        tags = get_draft_tags(draft_id)
    assert len(tags) == 1
    assert tags[0]["name"] == "Campaign"


def test_should_remove_draft_tag(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag, add_draft_tag, remove_draft_tag, get_draft_tags
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("ToRemove")
        add_draft_tag(draft_id, tag_id)
        remove_draft_tag(draft_id, tag_id)
        tags = get_draft_tags(draft_id)
    assert tags == []


def test_should_add_draft_tag_is_idempotent(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag, add_draft_tag, get_draft_tags
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Repeat")
        add_draft_tag(draft_id, tag_id)
        add_draft_tag(draft_id, tag_id)  # second call should not raise or duplicate
        tags = get_draft_tags(draft_id)
    assert len(tags) == 1


def test_should_cascade_delete_draft_tags_when_draft_deleted(db_path):
    with patch("api.db.DB_PATH", db_path):
        import sqlite3
        from api.db import create_draft, create_tag, add_draft_tag, get_conn
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Cascade")
        add_draft_tag(draft_id, tag_id)
        conn = get_conn()
        conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        conn.commit()
        rows = conn.execute("SELECT * FROM draft_tags WHERE draft_id = ?", (draft_id,)).fetchall()
        conn.close()
    assert rows == []


def test_should_cascade_delete_draft_tags_when_tag_deleted(db_path):
    with patch("api.db.DB_PATH", db_path):
        from api.db import create_draft, create_tag, add_draft_tag, delete_tag, get_conn
        draft_id = create_draft({"title": "T", "channel": "Press Release", "audience": "", "tone": "", "brief": "", "vault_context": "", "content": ""})
        tag_id = create_tag("Vanish")
        add_draft_tag(draft_id, tag_id)
        delete_tag(tag_id)
        conn = get_conn()
        rows = conn.execute("SELECT * FROM draft_tags WHERE tag_id = ?", (tag_id,)).fetchall()
        conn.close()
    assert rows == []
