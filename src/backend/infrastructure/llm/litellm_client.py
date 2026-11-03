"""The LiteLLM language model (TRIAD_LLM=llm). This module is the only place that imports litellm.

Install it with `uv pip install -r requirements-llm.txt`. The provider key comes from the usual
environment variable (for example GEMINI_API_KEY), which src/backend/.env can set. Only LiteLLM reads it.

Two kinds of calls:
- next_step: one step of the loop of an "ask" turn (application/assistant/agent.py). The call gives the
  messages and the tool definitions (tools=[{"type": "function", ...}], tool_choice="auto"). The model
  gives tool calls (message.tool_calls) or the final text (message.content). Each tool result goes back
  as one message with the role "tool". The messages hold references such as E1, never a record id.
- extract_facts: one call extracts the facts of a "tell" turn as JSON. The code checks the JSON.

Each failure raises an error. The application then uses the fake model for that turn.
check_ready runs once at the start. If litellm or the key is missing, or the model cannot call tools,
the app uses the fake mode.
Notes for all models: do not send temperature or a thinking setting (some models reject them, for
example Claude Opus 5.5). The model selects the tools (tool_choice="auto"). The code does not force a tool call.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Sequence

from application.ports import ChatMessage, ExtractedFact, FinalText, ToolCall, ToolCalls, ToolDefinition

ALLOWED_CATEGORIES = ("Observation", "Allergy", "Diagnosis", "Procedure")
TIMEOUT_SECONDS = 60
MAX_TOKENS = 8000
NO_ANSWER = ("content_filter", "refusal", "length")     # a finish reason with no usable text

EXTRACT_PROMPT = (
    "You extract clinical facts from one chat message in a hospital prototype with synthetic data. "
    "Reply with JSON only, in this form: "
    '{"facts": [{"category": "Observation|Allergy|Diagnosis|Procedure", "code": "...", "codeSystem": "...", '
    '"display": "...", "statement": "...", "value": "...", "unit": "...", "substance": "..."}]}. '
    "Use LOINC (http://loinc.org) or SNOMED CT (http://snomed.info/sct) codes only when you are sure. "
    "Else use the code system https://triad.example/fhir/CodeSystem/local with a short code, for example "
    "family-history. A family history is an Observation. If the message states no fact, reply {\"facts\": []}."
)


class LlmError(RuntimeError):
    pass


def check_ready(model: str) -> Optional[str]:
    """Why the llm mode cannot run with `model`, or None if it can. The text never holds a key value."""
    try:
        import litellm
    except ImportError:
        return "litellm is not installed. Run: uv pip install --python .venv/bin/python -r requirements-llm.txt."
    try:
        found = litellm.validate_environment(model=model)
    except Exception:  # noqa: BLE001 - LiteLLM does not know the model; the first call shows the error
        return None
    if not found.get("keys_in_environment"):
        names = ", ".join(found.get("missing_keys") or []) or "the key of the provider"
        return f"no API key for {model} is set (LiteLLM looks for {names}). Put the key in src/backend/.env."
    try:
        calls_tools = litellm.supports_function_calling(model)
    except Exception:  # noqa: BLE001 - the check is not sure, so it does not stop the llm mode
        return None
    if calls_tools is False:
        return (f"LiteLLM says that {model} cannot call tools (function calling). The Care Assistant needs "
                "tool calls. Set TRIAD_LLM_MODEL to a model that can call tools.")
    return None


def load_litellm():
    try:
        import litellm  # imported here only, so the tests and the fake mode do not need it
    except ImportError as error:
        raise LlmError("litellm is not installed. Run: uv pip install -r requirements-llm.txt") from error
    return litellm


def field_of(value: Any, name: str, default: Any = None) -> Any:
    """A field of a LiteLLM object or of a dict."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def tool_for_litellm(tool: ToolDefinition) -> dict:
    return {"type": "function",
            "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}


def message_for_litellm(message: ChatMessage) -> dict:
    """The message in the OpenAI form of LiteLLM. The server-side result of a tool message stays out."""
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "name": message.name,
                "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        calls = []
        for call in message.tool_calls:
            item = {"id": call.call_id, "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments}}
            item.update(call.provider_data)          # for example the thought signature of a Gemini model
            calls.append(item)
        return {"role": "assistant", "content": message.content or None, "tool_calls": calls}
    return {"role": message.role, "content": message.content}


def call_of(raw: Any) -> ToolCall:
    """One tool call of the response of LiteLLM."""
    function = field_of(raw, "function")
    arguments = field_of(function, "arguments") or "{}"
    extra = field_of(raw, "provider_specific_fields")
    return ToolCall(call_id=str(field_of(raw, "id") or ""), name=str(field_of(function, "name") or ""),
                    arguments=arguments if isinstance(arguments, str) else json.dumps(arguments),
                    provider_data={"provider_specific_fields": extra} if extra else {})


class LiteLlmLanguageModel:
    name = "llm"

    def __init__(self, model: str):
        self.model = model

    def _complete(self, system: str, user: str) -> str:
        response = load_litellm().completion(
            model=self.model, max_tokens=MAX_TOKENS, timeout=TIMEOUT_SECONDS,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text or getattr(choice, "finish_reason", None) in NO_ANSWER:
            raise LlmError("The model gave no usable answer.")
        return text

    def next_step(self, messages: Sequence[ChatMessage], tools: Sequence[ToolDefinition]) -> ToolCalls | FinalText:
        response = load_litellm().completion(
            model=self.model, max_tokens=MAX_TOKENS, timeout=TIMEOUT_SECONDS,
            messages=[message_for_litellm(m) for m in messages], tools=[tool_for_litellm(t) for t in tools],
            tool_choice="auto")
        choice = response.choices[0]
        message = choice.message
        raw_calls = list(field_of(message, "tool_calls") or [])
        text = (field_of(message, "content") or "").strip()
        if raw_calls:
            return ToolCalls(calls=[call_of(c) for c in raw_calls], text=text)
        if not text or field_of(choice, "finish_reason") in NO_ANSWER:
            raise LlmError("The model gave no usable answer.")
        return FinalText(text)

    def extract_facts(self, text: str, speaker_role: str) -> list[ExtractedFact]:
        raw = self._complete(EXTRACT_PROMPT, f"Speaker role: {speaker_role}\nMessage: {text}")
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise LlmError("The model did not give JSON.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as error:
            raise LlmError("The model gave JSON that is not correct.") from error
        items = data.get("facts") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise LlmError("The JSON has no list of facts.")
        facts = []
        for item in items:
            if not isinstance(item, dict) or item.get("category") not in ALLOWED_CATEGORIES:
                continue
            code, system, display = (str(item.get(k) or "").strip() for k in ("code", "codeSystem", "display"))
            if not (code and system and display):
                continue
            details = {k: item.get(k) for k in ("value", "unit", "substance") if item.get(k) not in (None, "")}
            facts.append(ExtractedFact(category=item["category"], code=code, code_system=system, display=display,
                                       statement=str(item.get("statement") or text).strip(), details=details))
        return facts
