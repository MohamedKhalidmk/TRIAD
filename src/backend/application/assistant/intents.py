"""Sort a chat turn into "ask" or "tell", and find the intent of a question. Pure rules; no I/O."""
from __future__ import annotations

import re
from typing import Optional

QUESTION_WORDS = ("what", "which", "who", "whom", "whose", "when", "where", "why", "how", "is", "are", "was",
                  "were", "does", "do", "did", "any", "can", "could", "has", "have", "should", "will", "list",
                  "show", "give", "find", "summarize", "summarise")

# The order is important: the first intent that matches wins.
INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recommendations", ("recommend", "suggest", "advise")),
    ("allergy", ("allerg",)),
    ("plan", ("plan", "next step", "treatment", "what happens")),
    ("medications", ("medication", "medicine", "drug", "taking", "prescri", "meds", "pill")),
    ("labs", ("lab", "test", "troponin", "result", "blood work")),
    ("vitals", ("vital", "blood pressure", "heart rate", "pulse", "oxygen", "saturation", "temperature",
                "observation", "respiratory")),
    ("diagnoses", ("diagnos", "condition", "problem", "assessment", "disease")),
    ("visits", ("visit", "history", "admission", "admitted", "encounter", "been seen")),
)


def kind_of(text: str) -> str:
    """'ask' for a question or a request, 'tell' for a statement of fact."""
    words = re.findall(r"[a-z']+", text.lower())
    if words and words[0] == "please":
        words = words[1:]
    if text.strip().endswith("?") or (words and words[0] in QUESTION_WORDS) or words[:2] == ["tell", "me"]:
        return "ask"
    return "tell"


def intent_of(text: str) -> str:
    lower = text.lower()
    for intent, keywords in INTENT_KEYWORDS:
        if any(k in lower for k in keywords):
            return intent
    return "unknown"


def asks_about_nurse(text: str) -> bool:
    return "nurse" in text.lower()


def allergy_term(text: str) -> Optional[str]:
    """The substance in "allergic to X" or "X allergy", if the question names one."""
    lower = text.lower()
    match = re.search(r"allerg(?:ic|y|ies)\s+to\s+([a-z][a-z -]*?)\s*(?:\?|\.|,|$)", lower)
    if not match:
        match = re.search(r"\b([a-z]{4,})\s+allerg", lower)
        if match and match.group(1) in ("have", "any", "known", "the", "with", "about", "drug", "food", "there"):
            match = None
    if not match:
        return None
    term = match.group(1).strip()
    return term or None
