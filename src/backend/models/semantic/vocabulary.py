"""The TRIAD namespaces, the class paths of the individuals, and the map from each DDL column to its ontology term.

This module uses only the Python standard library. It imports no RDF library, so all layers can import it.
`build_ontology.py` uses it for the coverage check. The R2RML mapping and the count check (plan 3.1, 3.3)
can use it too. `ontology.md` shows the same map as tables; a test checks that the two agree.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Namespaces, ontology IRIs and graphs (ontology.md section 1)
# ---------------------------------------------------------------------------

REPO = "https://github.com/MohamedKhalidmk/TRIAD"
ONTOLOGY_IRI = f"{REPO}/ontology/triad"
ONTOLOGY_VERSION = "5.0.0"
VERSION_IRI = f"{ONTOLOGY_IRI}/{ONTOLOGY_VERSION}"
TRIAD = f"{ONTOLOGY_IRI}#"          # the terms (classes and properties)
KG = f"{REPO}/kg/"                   # the individuals: KG + "<class path>/<Id>"

GRAPH_TBOX = f"{REPO}/graph/tbox"         # the ontology
GRAPH_ABOX = f"{REPO}/graph/abox"         # the data
GRAPH_SCRATCH = f"{REPO}/graph/scratch"   # the scratch graph of the scripts and the planted checks
GRAPH_META = f"{REPO}/graph/meta"         # the id counters and the build marker

PREFIXES = {
    "triad": TRIAD,
    "kg": KG,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "fhir": "http://hl7.org/fhir/",
}

# ---------------------------------------------------------------------------
# Tables, classes and subjects
# ---------------------------------------------------------------------------

# The class of the rows of each table. StaffLanguage has no class: each row is one triple on its staff member.
TABLE_CLASS = {
    "Department": "Department", "Location": "Location", "Staff": "Staff", "WorksIn": "WorksIn",
    "Doctor": "Doctor", "Nurse": "Nurse", "MOA": "MOA",
    "Patient": "Patient", "PatientIdentifier": "PatientIdentifier", "Visit": "Visit", "VisitLocation": "VisitLocation",
    "ClinicalEntry": "ClinicalEntry", "Diagnosis": "Diagnosis", "Procedure": "Procedure", "Allergy": "Allergy",
    "Observation": "Observation", "LabOrder": "LabOrder", "LabReport": "LabReport", "Medication": "Medication",
    "Prescription": "Prescription", "CareTeam": "CareTeam", "CareTeamMember": "CareTeamMember",
    "Message": "Message", "Assertion": "Assertion",
    "ChatSession": "ChatSession", "ChatTurn": "ChatTurn", "Citation": "Citation", "AuditEvent": "AuditEvent",
}

# The subject IRI of the triples of each table: KG + "<path>/<value of the column>".
# A subtype row is the same individual as its parent row, so it uses the parent path and the parent Id.
SUBJECT = {
    "Department": ("department", "Id"),
    "Location": ("location", "Id"),
    "Staff": ("staff", "Id"),
    "StaffLanguage": ("staff", "StaffId"),
    "WorksIn": ("works-in", "Id"),
    "Doctor": ("staff", "StaffId"),
    "Nurse": ("staff", "StaffId"),
    "MOA": ("staff", "StaffId"),
    "Patient": ("patient", "Id"),
    "PatientIdentifier": ("patient-identifier", "Id"),
    "Visit": ("visit", "Id"),
    "VisitLocation": ("visit-location", "Id"),
    "ClinicalEntry": ("clinical-entry", "Id"),
    "Diagnosis": ("clinical-entry", "ClinicalEntryId"),
    "Procedure": ("clinical-entry", "ClinicalEntryId"),
    "Allergy": ("clinical-entry", "ClinicalEntryId"),
    "Observation": ("clinical-entry", "ClinicalEntryId"),
    "LabOrder": ("clinical-entry", "ClinicalEntryId"),
    "LabReport": ("clinical-entry", "ClinicalEntryId"),
    "Medication": ("medication", "Id"),
    "Prescription": ("clinical-entry", "ClinicalEntryId"),
    "CareTeam": ("clinical-entry", "ClinicalEntryId"),
    "CareTeamMember": ("care-team-member", "Id"),
    "Message": ("message", "Id"),
    "Assertion": ("assertion", "Id"),
    "ChatSession": ("chat-session", "Id"),
    "ChatTurn": ("chat-turn", "Id"),
    "Citation": ("citation", "Id"),
    "AuditEvent": ("audit-event", "Id"),
}

# The 17 class paths of the individuals (plan 1.1).
CLASS_PATHS = {TABLE_CLASS[t]: path for t, (path, col) in SUBJECT.items() if col == "Id"}

# The subtype tables: (the column that holds the parent Id, the parent table).
SUBTYPE_TABLES = {
    "Doctor": ("StaffId", "Staff"), "Nurse": ("StaffId", "Staff"), "MOA": ("StaffId", "Staff"),
    "Diagnosis": ("ClinicalEntryId", "ClinicalEntry"), "Procedure": ("ClinicalEntryId", "ClinicalEntry"),
    "Allergy": ("ClinicalEntryId", "ClinicalEntry"), "Observation": ("ClinicalEntryId", "ClinicalEntry"),
    "LabOrder": ("ClinicalEntryId", "ClinicalEntry"), "LabReport": ("ClinicalEntryId", "ClinicalEntry"),
    "Prescription": ("ClinicalEntryId", "ClinicalEntry"), "CareTeam": ("ClinicalEntryId", "ClinicalEntry"),
}

# ---------------------------------------------------------------------------
# Columns that give a property
# ---------------------------------------------------------------------------

ATTRIBUTE = "attribute"     # a datatype property: <row> triad:p "value"
FK = "fk"                   # an object property in the stored direction: <row> triad:p <target>
FK_REVERSE = "fk-reverse"   # an object property in the reverse direction: <target> triad:p <row>

_IDENT = {"IdentifierSystem": "identifierSystem", "IdentifierValue": "identifierValue"}
_ADDR = {"Street": "street", "City": "city", "Region": "region", "PostalCode": "postalCode", "Country": "country"}


def _attrs(table: str, columns: dict[str, str]) -> dict[tuple[str, str], tuple[str, str]]:
    return {(table, column): (term, ATTRIBUTE) for column, term in columns.items()}


COLUMNS: dict[tuple[str, str], tuple[str, str]] = {
    **_attrs("Department", {**_IDENT, "Name": "name", "Type": "departmentType", "PhoneNumber": "phoneNumber",
                            "Email": "email", **_ADDR}),
    **_attrs("Location", {**_IDENT, "Name": "name", "Type": "locationType", "PhysicalType": "physicalType",
                          "PhoneNumber": "phoneNumber", **_ADDR}),
    **_attrs("Staff", {**_IDENT, "Name": "name", "Sex": "staffSex", "Email": "email", "PhoneNumber": "phoneNumber",
                       "Active": "active"}),
    **_attrs("StaffLanguage", {"Language": "language"}),
    **_attrs("WorksIn", {"RoleCode": "roleCode", "Specialty": "specialty", "StartDate": "roleStartDate",
                         "EndDate": "roleEndDate"}),
    ("WorksIn", "StaffId"): ("ofStaff", FK),
    ("WorksIn", "DepartmentId"): ("atDepartment", FK),
    **_attrs("Doctor", {"LicenseNumber": "licenseNumber", "Qualification": "qualification"}),
    **_attrs("Nurse", {"LicenseNumber": "licenseNumber", "Designation": "designation"}),
    **_attrs("MOA", {"CertificationNumber": "certificationNumber", "Desk": "desk", "PhoneExtension": "phoneExtension"}),
    **_attrs("Patient", {"Name": "name", "DateOfBirth": "dateOfBirth", "Sex": "patientSex",
                         "PhoneNumber": "phoneNumber", **_ADDR}),
    **_attrs("PatientIdentifier", {"System": "identifierSystem", "Value": "identifierValue"}),
    ("PatientIdentifier", "PatientId"): ("identifier", FK_REVERSE),
    **_attrs("Visit", {**_IDENT, "Class": "visitClass", "Type": "visitType", "Reason": "reason",
                       "StartDate": "startDate", "EndDate": "endDate"}),
    ("Visit", "PatientId"): ("hasVisit", FK_REVERSE),
    **_attrs("VisitLocation", {"StartDate": "startDate", "EndDate": "endDate"}),
    ("VisitLocation", "VisitId"): ("ofVisit", FK),
    ("VisitLocation", "LocationId"): ("atLocation", FK),
    **_attrs("ClinicalEntry", {**_IDENT, "Code": "code", "CodeSystem": "codeSystem", "Display": "display",
                               "Text": "text", "RecordedAt": "recordedAt"}),
    ("ClinicalEntry", "VisitId"): ("during", FK),
    **_attrs("Diagnosis", {"OnsetDate": "onsetDate", "AbatementDate": "abatementDate",
                           "ClinicalStatus": "clinicalStatus", "Severity": "severity"}),
    **_attrs("Procedure", {"PerformedDate": "performedDate", "Outcome": "procedureOutcome"}),
    **_attrs("Allergy", {"Substance": "substance", "Type": "allergyType", "AllergyCategory": "allergyCategory",
                         "Criticality": "criticality", "ClinicalStatus": "clinicalStatus"}),
    **_attrs("Observation", {"Value": "value", "Unit": "unit"}),
    **_attrs("LabOrder", {"TestName": "testName", "Priority": "priority", "Specimen": "specimen"}),
    **_attrs("LabReport", {"IssuedDate": "issuedDate", "Conclusion": "conclusion"}),
    **_attrs("Medication", {"Code": "code", "CodeSystem": "codeSystem", "Name": "name", "Form": "form",
                            "Manufacturer": "manufacturer"}),
    **_attrs("Prescription", {"Dosage": "dosage", "Frequency": "frequency", "Status": "prescriptionStatus"}),
    ("Prescription", "MedicationId"): ("prescribes", FK),
    **_attrs("CareTeam", {"Name": "name", "Status": "careTeamStatus"}),
    **_attrs("CareTeamMember", {"MemberSystem": "memberSystem", "MemberValue": "memberValue", "Role": "memberRole"}),
    ("CareTeamMember", "CareTeamId"): ("member", FK_REVERSE),
    **_attrs("Message", {**_IDENT, "Channel": "channel", "Origin": "origin", "SentAt": "sentAt", "Text": "text"}),
    ("Message", "StaffId"): ("issues", FK_REVERSE),
    **_attrs("Assertion", {"Seq": "seq", "AssertedAt": "assertedAt", "Intent": "intent", "Source": "source",
                           "Verification": "verification", "Statement": "statement"}),
    ("Assertion", "MessageId"): ("contains", FK_REVERSE),
    ("Assertion", "ClinicalEntryId"): ("about", FK),
    ("Assertion", "SupersedesId"): ("supersedes", FK),
    **_attrs("ChatSession", {**_IDENT, "UserRole": "userRole", "UserSystem": "userSystem", "UserValue": "userValue",
                             "SubjectName": "subjectName", "SubjectDateOfBirth": "subjectDateOfBirth",
                             "StartedAt": "startedAt", "Mode": "mode", "Model": "model"}),
    **_attrs("ChatTurn", {"Seq": "seq", "ClientTurnId": "clientTurnId", "Speaker": "speaker", "Text": "text",
                          "CreatedAt": "createdAt"}),
    ("ChatTurn", "ChatSessionId"): ("includes", FK_REVERSE),
    **_attrs("Citation", {"Rank": "rank"}),
    ("Citation", "ChatTurnId"): ("byTurn", FK),
    ("Citation", "AssertionId"): ("citedAssertion", FK),
    **_attrs("AuditEvent", {**_IDENT, "At": "at", "Action": "action", "Outcome": "auditOutcome",
                            "ActorRole": "actorRole", "ActorSystem": "actorSystem", "ActorValue": "actorValue",
                            "SubjectName": "subjectName", "SubjectDateOfBirth": "subjectDateOfBirth",
                            "Path": "path"}),
    ("AuditEvent", "ChatTurnId"): ("inTurn", FK),
}

# A foreign key whose target row is not the subject of its own IRI: the R2RML mapping must join (plan 3.1).
# CareTeamMember.CareTeamId holds CareTeam.Id, but the care-team individual is clinical-entry/<CareTeam.ClinicalEntryId>.
FK_JOINS = {("CareTeamMember", "CareTeamId"): ("CareTeam", "Id", "ClinicalEntryId")}

# ---------------------------------------------------------------------------
# Columns that give no property (the count check of plan 3.3 leaves them out)
# ---------------------------------------------------------------------------

_ID = "The Id is the last part of the IRI of the row."
_SUBTYPE_ID = "The subtype row has no IRI of its own: it is the same individual as its parent row."
_SUBTYPE_FK = "The parent Id: it is the subject of the subtype triples (the same individual)."
_DISCRIMINATOR = "The discriminator: rdf:type holds it."

NO_PROPERTY: dict[tuple[str, str], str] = {
    **{(t, "Id"): _ID for t, (path, col) in SUBJECT.items() if col == "Id"},
    **{(t, "Id"): _SUBTYPE_ID for t in SUBTYPE_TABLES},
    ("StaffLanguage", "Id"): "A StaffLanguage row has no IRI: it becomes one triad:language triple.",
    ("StaffLanguage", "StaffId"): "The subject of the triad:language triple.",
    ("Staff", "Role"): _DISCRIMINATOR,
    ("ClinicalEntry", "Category"): _DISCRIMINATOR,
    **{(t, "Role" if parent == "Staff" else "Category"): "A copy of the discriminator (for the composite FK): "
       "rdf:type holds it." for t, (fk, parent) in SUBTYPE_TABLES.items()},
    **{(t, fk): _SUBTYPE_FK for t, (fk, parent) in SUBTYPE_TABLES.items()},
}

# ---------------------------------------------------------------------------
# Object properties that have no triples in the store
# ---------------------------------------------------------------------------

# A named inverse -> its stored property. The keys and the property chains use them.
NAMED_INVERSES = {"inMessage": "contains", "inSession": "includes", "issuedBy": "issues",
                  "visitOf": "hasVisit", "memberOf": "member"}

# Derived properties (OWL 2 property chains or a transitive super-property). A reasoner infers them.
DERIVED = {
    "assertedBy": ("inMessage", "issuedBy"),
    "ofPatient": ("about", "during", "visitOf"),
    "supersedesTransitively": ("supersedes",),
}


def stored_object_properties() -> set[str]:
    """The object properties that have triples in the store: one per foreign-key column."""
    return {term for term, kind in COLUMNS.values() if kind in (FK, FK_REVERSE)}


def attribute_properties() -> set[str]:
    return {term for term, kind in COLUMNS.values() if kind == ATTRIBUTE}
