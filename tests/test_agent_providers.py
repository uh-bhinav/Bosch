"""
tests/test_agent_providers.py
--------------------------------
Tests for backend/agent/providers.py -- the provider-agnostic LLM
abstraction (Stage 5, roadmap §4.1/§4.2).

No live API calls here (see tests/test_dfm_agent.py's real end-to-end test
for that, gated on GOOGLE_API_KEY being set). These verify the pure logic:
the JSON-Schema -> Gemini types.Schema converter, and provider dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.agent.providers import ToolCall, ToolSpec, build_provider

HAS_GENAI = True
try:
    from google import genai  # noqa: F401
except ImportError:
    HAS_GENAI = False

skip_no_genai = pytest.mark.skipif(not HAS_GENAI, reason="google-genai not installed")


@dataclass
class _FakeAgentSettings:
    provider: str
    models: "_FakeModels"


@dataclass
class _FakeModels:
    gemini: str = "gemini-2.5-flash"
    anthropic: str = "claude-opus-5"
    openai: str = "gpt-4o-mini"
    grok: str = "grok-2-latest"


# ---------------------------------------------------------------------------
# JSON Schema -> Gemini types.Schema converter
# ---------------------------------------------------------------------------


@skip_no_genai
def test_json_schema_to_gemini_schema_converts_simple_object():
    from backend.agent.providers import _json_schema_to_gemini_schema
    from google.genai import types

    schema = {
        "type": "object",
        "properties": {"filename": {"type": "string", "description": "a file"}},
        "required": ["filename"],
    }
    result = _json_schema_to_gemini_schema(schema)
    assert result.type == types.Type.OBJECT
    assert "filename" in result.properties
    assert result.properties["filename"].type == types.Type.STRING
    assert result.required == ["filename"]


@skip_no_genai
def test_json_schema_to_gemini_schema_converts_array_of_numbers():
    from backend.agent.providers import _json_schema_to_gemini_schema
    from google.genai import types

    schema = {
        "type": "object",
        "properties": {
            "pull_direction": {
                "type": "array",
                "description": "unit vector",
                "items": {"type": "number"},
            },
        },
    }
    result = _json_schema_to_gemini_schema(schema)
    direction_schema = result.properties["pull_direction"]
    assert direction_schema.type == types.Type.ARRAY
    assert direction_schema.items.type == types.Type.NUMBER
    assert direction_schema.description == "unit vector"


@skip_no_genai
def test_json_schema_to_gemini_schema_never_needs_additional_properties():
    """
    Gemini's schema subset doesn't support additionalProperties (see
    providers.py module docstring) -- every real tool schema in
    backend/agent/tools.py must convert cleanly without it ever being
    referenced. This is a smoke test that the converter doesn't choke on
    (or require) that key.
    """
    from backend.agent.tools import TOOL_SPECS
    from backend.agent.providers import _json_schema_to_gemini_schema

    for spec in TOOL_SPECS:
        assert "additionalProperties" not in spec.parameters
        _json_schema_to_gemini_schema(spec.parameters)  # must not raise


# ---------------------------------------------------------------------------
# build_provider dispatch
# ---------------------------------------------------------------------------


def test_build_provider_rejects_unknown_provider_name():
    settings = _FakeAgentSettings(provider="not-a-real-provider", models=_FakeModels())
    with pytest.raises(ValueError, match="Unknown agent provider"):
        build_provider(settings)


@skip_no_genai
def test_build_provider_gemini_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    settings = _FakeAgentSettings(provider="gemini", models=_FakeModels())
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        build_provider(settings)


def test_build_provider_openai_and_grok_share_the_adapter_class():
    from backend.agent.providers import OpenAIProvider

    openai_settings = _FakeAgentSettings(provider="openai", models=_FakeModels())
    grok_settings = _FakeAgentSettings(provider="grok", models=_FakeModels())
    openai_provider = build_provider(openai_settings)
    grok_provider = build_provider(grok_settings)
    assert isinstance(openai_provider, OpenAIProvider)
    assert isinstance(grok_provider, OpenAIProvider)
    assert openai_provider.name == "openai"
    # Grok reuses the OpenAI adapter class, but "name" is a class attribute
    # (not instance-configurable) -- both report "openai". The real
    # distinction lives in base_url/model, verified separately below.
    assert grok_provider.name == "openai"


def test_build_provider_grok_uses_the_x_ai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "fake-grok-key")
    settings = _FakeAgentSettings(provider="grok", models=_FakeModels(grok="grok-2-latest"))
    provider = build_provider(settings)
    assert provider._model == "grok-2-latest"
    assert str(provider._client.base_url).rstrip("/") == "https://api.x.ai/v1"


# ---------------------------------------------------------------------------
# ToolCall / ToolSpec plain dataclasses -- structural sanity
# ---------------------------------------------------------------------------


def test_tool_call_carries_both_id_and_name():
    # Gemini matches function responses by name; Anthropic/OpenAI by a
    # unique call id -- ToolCall must carry both (see providers.py docstring).
    call = ToolCall(id="analyze_draft_0", name="analyze_draft", arguments={"filename": "Part1.stp"})
    assert call.id == "analyze_draft_0"
    assert call.name == "analyze_draft"


def test_tool_spec_requires_a_json_schema_shaped_parameters_dict():
    spec = ToolSpec(
        name="dummy",
        description="a dummy tool",
        parameters={"type": "object", "properties": {}, "required": []},
        fn=lambda: {"status": "ok"},
    )
    assert spec.parameters["type"] == "object"
    assert spec.fn() == {"status": "ok"}
