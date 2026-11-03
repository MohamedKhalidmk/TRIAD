"""The LiteLLM language model (TRIAD_LLM=llm). This module is the only place that imports litellm.

Install it with `uv pip install -r requirements-llm.txt`. The provider key comes from the usual
environment variable (for example GEMINI_API_KEY), which src/backend/.env can set. Only LiteLLM reads it.

Two calls:
- word_answer: one call words the answer. The prompt gives only the cited statements and the rule draft.
- extract_facts: one call extracts the facts of a "tell" turn as JSON. The code checks the JSON.

Each failure raises an error. The application then uses the fake model for that turn.
check_ready runs once at the start. If litellm or the key is missing, the app uses the fake mode.
Notes for all models: do not send temperature or a thinking setting (some models reject them, for
example Claude Opus 5.5), and do not force a tool call. The prompt asks for JSON, and the code checks it.
"""
from __future__ import annotations

import json
import re
from typing import Optional, Sequence

from application.ports import ExtractedFact
from domain.views import AssertionView

ALLOWED_CATEGORIES = ("Observation", "Allergy", "Diagnosis", "Procedure")
TIMEOUT_SECONDS = 60
MAX_TOKENS = 8000

WORD_PROMPT = (
    "You are the TRIAD Care Assistant in a hospital prototype with synthetic data. "
    "Rewrite the draft answer for a {audience}. Use only the facts in the list. Do not add a fact, a number, "
    "a date or advice that is not in the list. Keep each fact that the draft gives. Use short, clear sentences. "
    "Reply with the answer text only."
)
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
    return None


class LiteLlmLanguageModel:
    name = "llm"

    def __init__(self, model: str):
        self.model = model

    def _complete(self, system: str, user: str) -> str:
        try:
            import litellm  # imported here only, so the tests and the fake mode do not need it
        except ImportError as error:
            raise LlmError("litellm is not installed. Run: uv pip install -r requirements-llm.txt") from error
        response = litellm.completion(
            model=self.model, max_tokens=MAX_TOKENS, timeout=TIMEOUT_SECONDS,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text or getattr(choice, "finish_reason", None) in ("content_filter", "refusal", "length"):
            raise LlmError("The model gave no usable answer.")
        return text

    def word_answer(self, question: str, draft: str, facts: Sequence[AssertionView], audience: str) -> str:
        listed = "\n".join(
            f"- [{a.id}] {a.category} {a.display}: {a.statement} ({a.verification}; {a.author.label}; "
            f"{a.asserted_at[:10]})" for a in facts)
        user = f"Question: {question}\n\nFacts:\n{listed}\n\nDraft answer:\n{draft}"
        return self._complete(WORD_PROMPT.format(audience=audience), user)

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
