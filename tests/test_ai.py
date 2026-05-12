"""Tests for api/ai.py — mocked Gemini client."""
import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock


# ── _parse_json ───────────────────────────────────────────────────────────────

def test_should_parse_plain_json_object():
    from api.ai import _parse_json
    result = _parse_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_should_parse_json_wrapped_in_markdown_code_fence():
    from api.ai import _parse_json
    raw = "```json\n{\"themes\": []}\n```"
    result = _parse_json(raw)
    assert result == {"themes": []}


def test_should_parse_json_array():
    from api.ai import _parse_json
    result = _parse_json('[{"name": "A"}, {"name": "B"}]')
    assert len(result) == 2


def test_should_raise_when_no_json_in_response():
    from api.ai import _parse_json
    with pytest.raises(ValueError, match="No JSON"):
        _parse_json("This is just plain text with no JSON.")


# ── _get_key ──────────────────────────────────────────────────────────────────

def test_should_raise_when_api_key_missing():
    from api.ai import _get_key
    with pytest.raises(ValueError, match="No Gemini API key"):
        _get_key({})


def test_should_return_key_from_settings():
    from api.ai import _get_key
    assert _get_key({"gemini_api_key": "my-key"}) == "my-key"


def test_should_fall_back_to_env_var(monkeypatch):
    from api.ai import _get_key
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    assert _get_key({}) == "env-key"


# ── _draft_prompt ─────────────────────────────────────────────────────────────

def test_should_include_channel_guidance_in_draft_prompt():
    from api.ai import _draft_prompt
    prompt = _draft_prompt({"channel": "Press Release", "brief": "Q1 results"}, {})
    assert "AP style" in prompt
    assert "Q1 results" in prompt


def test_should_include_vault_context_when_provided():
    from api.ai import _draft_prompt
    prompt = _draft_prompt({"channel": "LinkedIn", "brief": "test"}, {}, vault_context="Important vault info")
    assert "Important vault info" in prompt


def test_should_truncate_vault_context_at_3000_chars():
    from api.ai import _draft_prompt
    long_ctx = "x" * 5000
    prompt = _draft_prompt({"channel": "LinkedIn", "brief": ""}, {}, vault_context=long_ctx)
    assert "x" * 3001 not in prompt


def test_should_use_org_name_from_settings():
    from api.ai import _draft_prompt
    prompt = _draft_prompt({"channel": "Press Release", "brief": ""}, {"org_name": "TestCorp"})
    assert "TestCorp" in prompt


# ── generate ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_return_content_dict_from_generate(mock_gemini, settings):
    mock_gemini.models.generate_content.return_value.text = "  Generated press release.  "
    from api.ai import generate
    result = await generate({"channel": "Press Release", "brief": "test"}, settings)
    assert result == {"content": "Generated press release."}


@pytest.mark.asyncio
async def test_should_call_gemini_once_per_generate(mock_gemini, settings):
    from api.ai import generate
    await generate({"channel": "LinkedIn", "brief": "test"}, settings)
    assert mock_gemini.models.generate_content.call_count == 1


@pytest.mark.asyncio
async def test_should_raise_when_no_key_in_generate():
    from api.ai import generate
    with pytest.raises(ValueError, match="No Gemini API key"):
        await generate({"channel": "Press Release", "brief": ""}, {})


# ── refine ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_return_refined_content(mock_gemini, settings):
    mock_gemini.models.generate_content.return_value.text = "Shorter version."
    from api.ai import refine
    result = await refine("Long original content.", "shorten", "Press Release", settings)
    assert result == {"content": "Shorter version."}


@pytest.mark.asyncio
async def test_should_include_shorten_instruction_in_refine_prompt(mock_gemini, settings):
    from api.ai import refine
    await refine("Some content.", "shorten", "LinkedIn", settings)
    call_args = mock_gemini.models.generate_content.call_args
    prompt = call_args.kwargs.get("contents") or call_args.args[1]
    assert "Shorten" in prompt or "shorten" in str(call_args)


@pytest.mark.asyncio
async def test_should_handle_unknown_refine_action(mock_gemini, settings):
    from api.ai import refine
    result = await refine("content", "unknown_action", "Press Release", settings)
    assert "content" in result


# ── translate ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_return_translated_content(mock_gemini, settings):
    mock_gemini.models.generate_content.return_value.text = "المحتوى المترجم"
    from api.ai import translate
    result = await translate("Original English content.", "Arabic (MSA)", "Premium", settings)
    assert result == {"content": "المحتوى المترجم"}


# ── test_connection ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_return_ok_true_on_successful_connection(mock_gemini):
    mock_gemini.models.generate_content.return_value.text = "OK"
    from api.ai import test_connection
    result = await test_connection("valid-key")
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_should_return_ok_false_on_connection_failure():
    with patch("api.ai._client", side_effect=Exception("Invalid API key")):
        from api.ai import test_connection
        result = await test_connection("bad-key")
    assert result["ok"] is False
    assert "error" in result
