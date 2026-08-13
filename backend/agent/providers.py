"""
backend/agent/providers.py
----------------------------
Provider-agnostic LLM abstraction (Stage 5, roadmap §4.1/§4.2).

Decision (2026-07-26, reaffirmed 2026-07-28): the agent layer is built
against a provider-agnostic interface. Gemini is the default (cheap, and the
team has a working API key); Anthropic and OpenAI are first-class swappable
adapters. Grok reuses the OpenAI adapter class via its OpenAI-compatible
endpoint -- `docker-compose.yml` already wired `GROK_API_KEY` through before
this stage existed, so it is a real fourth option, not a hypothetical one.

Tool schemas are authored ONCE as plain JSON Schema (see `tools.py`) and each
adapter down-converts to its native tool-calling format:
  - Gemini:    `types.FunctionDeclaration` + `types.Schema` (restricted
               subset -- no `additionalProperties`; verified live against a
               real API key, 2026-07-28).
  - Anthropic: `{name, description, input_schema}` -- JSON Schema directly.
  - OpenAI:    `{type: "function", function: {name, description, parameters}}`
               -- JSON Schema directly.
Gemini's subset is the most restrictive, so authoring to Gemini's
constraints keeps all three adapters trivial -- this is why `tools.py`'s
schemas never use `additionalProperties` or unsupported JSON Schema keywords.

Result-matching differs by provider: Gemini's function-response matching is
NAME-based (no per-call ID in the wire format), while Anthropic/OpenAI match
on a per-call `id`/`tool_use_id`. `ToolCall` carries both `id` (unique,
generated locally) and `name` (the function name) so every adapter has
whichever it needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol
import json
import logging
import os

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # plain JSON Schema, authored to Gemini's restricted subset
    fn: Callable[..., dict]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # role="tool": the call this result answers
    tool_name: Optional[str] = None  # role="tool": the function name (Gemini needs this)
    tool_result: Optional[dict] = None  # role="tool": the JSON-safe result payload


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ProviderResponse:
    text: Optional[str]
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: TokenUsage


class LLMProvider(Protocol):
    name: str

    def invoke(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str,
        temperature: float = 0.1,
    ) -> ProviderResponse: ...


# ---------------------------------------------------------------------------
# JSON Schema -> Gemini types.Schema (recursive, restricted subset)
# ---------------------------------------------------------------------------

_GEMINI_TYPE_MAP = {
    "object": "OBJECT",
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
}


def _json_schema_to_gemini_schema(schema: dict):
    from google.genai import types

    json_type = schema.get("type", "object")
    kwargs: dict[str, Any] = {"type": types.Type[_GEMINI_TYPE_MAP.get(json_type, "OBJECT")]}
    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "enum" in schema:
        kwargs["enum"] = schema["enum"]
    if json_type == "object":
        properties = schema.get("properties", {})
        kwargs["properties"] = {
            name: _json_schema_to_gemini_schema(prop) for name, prop in properties.items()
        }
        if "required" in schema:
            kwargs["required"] = schema["required"]
    if json_type == "array" and "items" in schema:
        kwargs["items"] = _json_schema_to_gemini_schema(schema["items"])
    return types.Schema(**kwargs)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        from google import genai

        resolved_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError(
                "GeminiProvider requires an API key: pass api_key= or set GOOGLE_API_KEY."
            )
        self._client = genai.Client(api_key=resolved_key)
        self._model = model

    def invoke(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str,
        temperature: float = 0.1,
    ) -> ProviderResponse:
        from google.genai import types

        gemini_tools = None
        if tools:
            gemini_tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=_json_schema_to_gemini_schema(t.parameters),
                )
                for t in tools
            ])]

        contents: list = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(
                    role="user", parts=[types.Part.from_text(text=m.content or "")],
                ))
            elif m.role == "assistant":
                parts = []
                if m.content:
                    parts.append(types.Part.from_text(text=m.content))
                for tc in m.tool_calls:
                    parts.append(types.Part.from_function_call(name=tc.name, args=tc.arguments))
                contents.append(types.Content(role="model", parts=parts))
            elif m.role == "tool":
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(
                        name=m.tool_name or "", response=m.tool_result or {},
                    ),
                ]))

        config = types.GenerateContentConfig(
            tools=gemini_tools, temperature=temperature, system_instruction=system,
        )
        response = self._client.models.generate_content(
            model=self._model, contents=contents, config=config,
        )

        tool_calls = [
            ToolCall(id=f"{fc.name}_{i}", name=fc.name, arguments=dict(fc.args or {}))
            for i, fc in enumerate(response.function_calls or [])
        ]

        finish_reason = "unknown"
        if response.candidates:
            finish_reason = str(response.candidates[0].finish_reason)

        usage = TokenUsage()
        if response.usage_metadata:
            usage = TokenUsage(
                input_tokens=response.usage_metadata.prompt_token_count or 0,
                output_tokens=response.usage_metadata.candidates_token_count or 0,
            )

        return ProviderResponse(
            text=response.text or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-opus-5"):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._model = model

    def invoke(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str,
        temperature: float = 0.1,
    ) -> ProviderResponse:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]

        anthropic_messages: list[dict] = []
        for m in messages:
            if m.role == "user":
                anthropic_messages.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant":
                content: list[dict] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append({
                        "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments,
                    })
                anthropic_messages.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": json.dumps(m.tool_result),
                    }],
                })

        # Claude Opus 5 (the current default model) rejects `temperature` --
        # sampling parameters were removed on 4.7+/Opus 5 (returns 400). Do
        # not pass it here; steer behavior via the system prompt instead.
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            tools=anthropic_tools,
            messages=anthropic_messages,
        )

        tool_calls = [
            ToolCall(id=block.id, name=block.name, arguments=block.input)
            for block in response.content
            if block.type == "tool_use"
        ]
        text_parts = [block.text for block in response.content if block.type == "text"]

        return ProviderResponse(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=response.stop_reason or "unknown",
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
        )


class OpenAIProvider:
    """
    Also serves as the Grok adapter: Grok's API is OpenAI-compatible, so
    pointing `base_url` at `https://api.x.ai/v1` with a Grok key is all that
    differs. `docker-compose.yml` already wires `GROK_API_KEY` through --
    this predates Stage 5 and reflects the project's actual original
    scaffold (see providers.py module docstring).
    """

    name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
    ):
        import openai

        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)
        self._model = model

    def invoke(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str,
        temperature: float = 0.1,
    ) -> ProviderResponse:
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name, "description": t.description, "parameters": t.parameters,
                },
            }
            for t in tools
        ]

        openai_messages: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                openai_messages.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ]
                openai_messages.append(msg)
            elif m.role == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "content": json.dumps(m.tool_result),
                })

        response = self._client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            tools=openai_tools or None,
            temperature=temperature,
        )

        choice = response.choices[0]
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments))
            for tc in (choice.message.tool_calls or [])
        ]

        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )

        return ProviderResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage,
        )


def build_provider(agent_settings) -> LLMProvider:
    """Construct the configured provider from `settings.agent` (backend/config.py)."""
    provider = agent_settings.provider
    if provider == "gemini":
        return GeminiProvider(model=agent_settings.models.gemini)
    if provider == "anthropic":
        return AnthropicProvider(model=agent_settings.models.anthropic)
    if provider == "openai":
        return OpenAIProvider(model=agent_settings.models.openai)
    if provider == "grok":
        return OpenAIProvider(
            api_key=os.environ.get("GROK_API_KEY"),
            model=agent_settings.models.grok,
            base_url="https://api.x.ai/v1",
        )
    raise ValueError(f"Unknown agent provider: {provider!r} (expected gemini/anthropic/openai/grok).")
