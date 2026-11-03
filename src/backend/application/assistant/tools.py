"""The tools of the Care Assistant: targeted lookups in the record, bound to the user and the patient of the turn.

make_tools(ctx, actor, patient) gives a ToolBox for one "ask" turn. Each tool is a closure over the actor
(from the X-Triad-User header) and the patient (from the chat session). So no tool has a parameter for a
patient, a user or an id. The parameters are words and enum values only, and the model cannot select a patient.

- Each tool is one targeted query of the repositories: a WHERE clause on the patient and on the category,
  the status, the visit or the words; an ORDER BY; LIMIT 12. No tool reads the full chart.
- A patient gets only the patient-visible items (the rule of query Q12, in SQL).
- The turn checks the access once before the tools (post_turn). The tools write no audit record.
- The tools call the repositories in the process. They do not make HTTP calls to the server.

No id goes to the model. Each item of a result gets a reference (E1, E2, ...) that is valid for this turn
only. The ToolBox keeps the map from the reference to the assertion. For each item, the model sees only
the reference, the category, the display, the statement, the verification, the author, the date and the
subtype details. It never sees an Id, the patient name, the date of birth or an identifier.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from domain.access import Actor
from domain.enums import ENTRY_CATEGORIES
from domain.rules import plan_visit
from domain.views import AssertionView, PatientView, VisitView

from application.context import AppContext
from application.paging import PageRequest
from application.ports import ToolCall, ToolDefinition

MAX_ITEMS = 12
MAX_VISITS = 5
PLAN_ORDER = ("Diagnosis", "LabOrder", "LabReport", "Prescription", "Procedure")
# LOINC codes of vital signs (the FHIR vital-signs profile and the codes of the record form).
VITAL_SIGNS = ("8867-4", "85354-9", "8480-6", "8462-4", "2708-6", "59408-5", "8310-5", "9279-1", "29463-7",
               "8302-2", "39156-5", "72514-3")
CLASS_LABEL = {"EMER": "emergency", "AMB": "ambulatory", "IMP": "inpatient", "HH": "home health", "VR": "virtual"}
ROLES = ("Nurse", "Doctor")

# The subtype details that the model can see. The members of a care team are not in the list: a member
# that is not in the Staff table shows as an identifier value.
MODEL_DETAILS = {
    "Diagnosis": ("clinicalStatus", "severity", "onsetDate", "abatementDate"),
    "Procedure": ("performedDate", "outcome"),
    "Allergy": ("substance", "type", "allergyCategory", "criticality", "clinicalStatus"),
    "Observation": ("value", "unit"),
    "LabOrder": ("testName", "priority", "specimen"),
    "LabReport": ("issuedDate", "conclusion"),
    "Prescription": ("medication", "dosage", "frequency", "status"),
    "CareTeam": ("name", "status"),
}


class ToolError(ValueError):
    """A tool call that is not correct. The text goes back to the model, and no query runs."""


@dataclass
class ToolResult:
    """The server-side result of one tool call. Only `content` (JSON text, with no ids) goes to the model."""
    items: list[AssertionView] = field(default_factory=list)      # the items that the turn can cite
    visit: Optional[VisitView] = None                              # get_plan and get_recommendations
    visits: list[VisitView] = field(default_factory=list)          # get_visits
    total: Optional[int] = None                                    # the number of matches on all pages
    name: str = ""
    arguments: dict = field(default_factory=dict)
    for_patient: bool = False                                      # the user is the patient
    error: Optional[str] = None
    content: str = ""


@dataclass
class Tool:
    definition: ToolDefinition
    run: Callable[..., ToolResult]


# ----- the JSON Schema of the parameters -----

def parameters(required: tuple[str, ...] = (), **properties: dict) -> dict:
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return schema


def text_param(description: str) -> dict:
    return {"type": "string", "description": description}


def enum_param(values: tuple[str, ...], description: str) -> dict:
    return {"type": "string", "enum": list(values), "description": description}


def parse_arguments(raw: object) -> dict:
    """The arguments of a call as a dict. A null value is the same as a missing value."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            raise ToolError("The arguments are not correct JSON. Give a JSON object.") from None
    if not isinstance(raw, dict):
        raise ToolError("The arguments must be a JSON object.")
    return {key: value for key, value in raw.items() if value is not None}


def check_arguments(definition: ToolDefinition, arguments: dict) -> None:
    """Check the arguments against the schema of the tool (the names, the types and the enum values)."""
    properties = definition.parameters.get("properties", {})
    allowed = ", ".join(properties) or "no parameter"
    for key in arguments:
        if key not in properties:
            raise ToolError(f"The tool {definition.name} has no parameter {key}. The tools know the patient and "
                            f"the user of this chat. Use only: {allowed}.")
    for key in definition.parameters.get("required", ()):
        if key not in arguments:
            raise ToolError(f"The tool {definition.name} needs the parameter {key}.")
    for key, value in arguments.items():
        spec = properties[key]
        if spec.get("type") == "string" and not isinstance(value, str):
            raise ToolError(f"The parameter {key} must be a string.")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"The parameter {key} must be one of: {', '.join(spec['enum'])}.")


def words_of(term: Optional[str]) -> list[str]:
    """The words of a search term that have 3 letters or more (the rule of the allergy question)."""
    return [w for w in (term or "").lower().split() if len(w) >= 3]


def clean(value: Optional[str]) -> Optional[str]:
    return (value or "").strip() or None


# ----- what the model sees -----

class NameFilter:
    """Replaces the name of the patient in a text with "the patient" (for example "Elena Marsh care team")."""

    def __init__(self, name: str):
        parts = sorted({name, *(p for p in name.split() if len(p) >= 3)}, key=len, reverse=True)
        self.pattern = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in parts) + r")\b", re.I)

    def __call__(self, value):
        return self.pattern.sub("the patient", value) if isinstance(value, str) else value


def visit_for_model(visit: VisitView, hide: NameFilter) -> dict:
    return {"type": f"{CLASS_LABEL.get(visit.visit_class, visit.visit_class)} visit",
            "start": visit.start_date[:10], "end": visit.end_date[:10] if visit.end_date else None,
            "open": visit.is_open, "reason": hide(visit.reason), "department": visit.department}


class ToolBox:
    """The tools of one turn, and the map from each reference (E1, E2, ...) to its assertion."""

    def __init__(self, actor: Actor, patient: PatientView, tools: list[Tool]):
        self.for_patient = actor.is_patient
        self.tools = {tool.definition.name: tool for tool in tools}
        self.hide = NameFilter(patient.name)
        self.refs: dict[str, AssertionView] = {}
        self._ref_of: dict[int, str] = {}

    @property
    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self.tools.values()]

    def run(self, call: ToolCall) -> ToolResult:
        """Check the call, run the bound tool and make the content for the model. An error runs no query."""
        tool = self.tools.get(call.name)
        try:
            if tool is None:
                raise ToolError(f"There is no tool {call.name}. Use one of: {', '.join(self.tools)}.")
            arguments = parse_arguments(call.arguments)
            check_arguments(tool.definition, arguments)
            result = tool.run(**arguments)
        except ToolError as error:
            result = ToolResult(error=str(error))
            arguments = {}
        result.name, result.arguments, result.for_patient = call.name, arguments, self.for_patient
        result.content = json.dumps(self.for_model(result), ensure_ascii=False)
        return result

    def ref(self, assertion: AssertionView) -> str:
        """The reference of an assertion in this turn. The same assertion keeps the same reference."""
        if assertion.id not in self._ref_of:
            ref = f"E{len(self.refs) + 1}"
            self._ref_of[assertion.id] = ref
            self.refs[ref] = assertion
        return self._ref_of[assertion.id]

    def item_for_model(self, a: AssertionView, show_state: bool) -> dict:
        item = {"ref": self.ref(a), "category": a.category, "display": self.hide(a.display),
                "statement": self.hide(a.statement), "verification": a.verification, "author": a.author.label,
                "date": a.asserted_at[:10]}
        if a.author.staff_id is not None:          # the name of a patient author never goes to the model
            item["authorName"], item["authorRole"] = a.author.name, a.author.role
        details = {key: self.hide(a.details[key]) for key in MODEL_DETAILS.get(a.category, ())
                   if a.details.get(key) not in (None, "")}
        if details:
            item["details"] = details
        if show_state:
            item["current"] = a.is_current
        return item

    def for_model(self, result: ToolResult) -> dict:
        if result.error:
            return {"error": result.error}
        out: dict = {}
        if result.name in ("get_plan", "get_recommendations"):
            out["visit"] = visit_for_model(result.visit, self.hide) if result.visit else None
        if result.name == "get_visits":
            out["visits"] = [visit_for_model(v, self.hide) for v in result.visits]
            out["note"] = "A visit has no reference. Do not cite a visit."
        else:
            show_state = result.name == "get_recommendations"
            out["items"] = [self.item_for_model(a, show_state) for a in result.items]
        if result.total is not None:
            out["total"] = result.total
        return out


# ----- the tools -----

def make_tools(ctx: AppContext, actor: Actor, patient: PatientView) -> ToolBox:
    """The tools of one turn, bound to the actor and the patient. The model cannot change these two values."""
    patient_id, visible = patient.id, actor.is_patient

    def get_allergies(substance: Optional[str] = None) -> ToolResult:
        term = clean(substance)
        words = words_of(term)
        if term and not words:                    # no word of 3 letters or more matches no item
            return ToolResult()
        return ToolResult(items=ctx.records.allergies(patient_id, words=words, visible_only=visible,
                                                      limit=MAX_ITEMS))

    def get_medications(status: str = "current") -> ToolResult:
        return ToolResult(items=ctx.records.prescriptions(patient_id, current_status=status == "current",
                                                          visible_only=visible, limit=MAX_ITEMS))

    def get_diagnoses(status: str = "current") -> ToolResult:
        return ToolResult(items=ctx.records.diagnoses(patient_id, active_only=status == "current",
                                                      visible_only=visible, limit=MAX_ITEMS))

    def the_plan_visit() -> Optional[VisitView]:
        visit_id = plan_visit(ctx.visits.visit_rows(patient_id))
        return ctx.visits.get(visit_id) if visit_id is not None else None

    def get_plan() -> ToolResult:
        visit = the_plan_visit()
        if visit is None:
            return ToolResult()
        return ToolResult(visit=visit, items=ctx.records.visit_items(patient_id, visit.id, PLAN_ORDER,
                                                                     visible_only=visible, limit=MAX_ITEMS))

    def get_lab_results(test: Optional[str] = None) -> ToolResult:
        term = clean(test)
        words = words_of(term)
        if term and not words:
            return ToolResult()
        return ToolResult(items=ctx.records.lab_items(patient_id, words=words, visible_only=visible,
                                                      limit=MAX_ITEMS))

    def get_vital_signs() -> ToolResult:
        return ToolResult(items=ctx.records.latest_observations(patient_id, VITAL_SIGNS, visible_only=visible,
                                                                limit=MAX_ITEMS))

    def get_visits() -> ToolResult:
        page = ctx.visits.for_patient_page(patient_id, PageRequest(limit=MAX_VISITS))
        return ToolResult(visits=page.items, total=page.total)

    def get_recommendations(role: Optional[str] = None) -> ToolResult:
        visit = the_plan_visit()
        if visit is None:
            return ToolResult()
        return ToolResult(visit=visit, items=ctx.records.recommendations(
            patient_id, visit.id, author_role=role, visible_only=visible, limit=MAX_ITEMS))

    def search_record(text: str, category: Optional[str] = None) -> ToolResult:
        if not clean(text):
            raise ToolError("Give a word to search for.")
        page = ctx.records.items_page(patient_id, current_only=True, category=category, text=clean(text),
                                      visible_only=visible, page=PageRequest(limit=MAX_ITEMS))
        return ToolResult(items=page.items, total=page.total)

    status = enum_param(("current", "all"), "current (the default) or all.")
    tools = [
        Tool(ToolDefinition(
            "get_allergies",
            "Get the allergy items of the patient of this chat, newest first (at most 12). Each item gives the "
            "verification: Confirmed, Refuted (ruled out) or Unconfirmed, and who said it. Give substance to get "
            "only the items that name that substance.",
            parameters(substance=text_param("A substance or an allergen, for example penicillin or peanut."))),
            get_allergies),
        Tool(ToolDefinition(
            "get_medications",
            "Get the prescriptions of the patient, newest first (at most 12). status current (the default): the "
            "active and the proposed prescriptions that nobody refuted. status all: also the stopped and the "
            "completed prescriptions.",
            parameters(status=status)), get_medications),
        Tool(ToolDefinition(
            "get_diagnoses",
            "Get the diagnoses of the patient, newest first (at most 12). status current (the default): the "
            "active diagnoses that nobody refuted. status all: also the resolved and the refuted diagnoses.",
            parameters(status=status)), get_diagnoses),
        Tool(ToolDefinition(
            "get_plan",
            "Get the plan of the patient: the open visit (or else the latest visit that is not a virtual visit) "
            "and its diagnoses, lab orders, lab results, prescriptions and procedures (at most 12).",
            parameters()), get_plan),
        Tool(ToolDefinition(
            "get_lab_results",
            "Get the lab orders and the lab results of the patient, newest first (at most 12). Give test to get "
            "only the items that name that test.",
            parameters(test=text_param("A test name, for example troponin or glucose."))), get_lab_results),
        Tool(ToolDefinition(
            "get_vital_signs",
            "Get the latest value of each vital sign of the patient: heart rate, blood pressure, oxygen "
            "saturation, body temperature, respiratory rate, body weight, body height, BMI and pain score.",
            parameters()), get_vital_signs),
        Tool(ToolDefinition(
            "get_visits",
            "Get the latest 5 visits of the patient: the type, the dates, the reason and the department. "
            "A visit has no reference, so do not cite a visit.",
            parameters()), get_visits),
        Tool(ToolDefinition(
            "get_recommendations",
            "Get the recommendations of the plan visit (the open visit, or else the latest visit that is not a "
            "virtual visit), oldest first (at most 12). current false: a later item revised the recommendation.",
            parameters(role=enum_param(ROLES, "Nurse or Doctor: only the recommendations of that role.")),
        ), get_recommendations),
        Tool(ToolDefinition(
            "search_record",
            "Search the current items of the record of the patient for words, in the order of the chart "
            "(at most 12). The search looks in the display, the statement and the author name.",
            parameters(("text",), text=text_param("The words to search for, for example metformin."),
                       category=enum_param(ENTRY_CATEGORIES, "Search only the items of this category."))),
            search_record),
    ]
    return ToolBox(actor, patient, tools)
