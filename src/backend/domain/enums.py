"""Value sets of the TRIAD model. The database CHECK constraints use the same values."""
from __future__ import annotations

STAFF_ROLES = ("Doctor", "Nurse", "MOA")
USER_ROLES = ("Patient",) + STAFF_ROLES

ENTRY_CATEGORIES = (
    "Diagnosis", "Procedure", "Allergy", "Observation",
    "LabOrder", "LabReport", "Prescription", "CareTeam",
)

INTENTS = ("Report", "Recommendation", "Decision")
SOURCES = ("Human", "Agent")
VERIFICATIONS = ("Unconfirmed", "Provisional", "Differential", "Confirmed", "Refuted", "EnteredInError")

CHANNELS = ("InPerson", "Phone", "Video", "Email", "Fax", "Transfer", "Chat", "App")
ORIGINS = ("Patient", "Staff", "OtherClinic", "PharmaNet", "Lab", "Agent")

VISIT_CLASSES = ("AMB", "EMER", "IMP", "HH", "VR")
CHAT_MODES = ("rules", "fake", "llm")
AUDIT_ACTIONS = ("read", "create", "update", "delete", "ask", "tell")
AUDIT_OUTCOMES = ("Allowed", "Denied")
