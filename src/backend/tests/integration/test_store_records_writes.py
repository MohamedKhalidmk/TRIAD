"""The writes of the record port and the assertion guards on each store (plan 5.3, 5.4, 5.6).

Each test makes the same write on the store and on a SQLite copy of the same data (the reference). Both start with
the same rows and the same id counters, so the new ids are the same. The test then compares the new rows (the
probe), the views and the chart. A guard test makes a write that breaks a rule on both stores, and expects the same
exception class, message and fields, and no new row.

The writes use the write function of the use case (application.records.write) and the port methods. The API tests
at the end need the other ports on the knowledge graph (agents C and D): they skip while a port is a stub.
"""
from __future__ import annotations

import ast
import inspect
import shutil
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest

from domain.access import Actor
from domain.errors import DomainError
from domain.rules import parse_time

from application import records
from application.paging import PageRequest
from application.ports import NewEntryRow
from application.records import NewAssertionCmd, NewEntryCmd, PreparedAssertion
from infrastructure.sparql import terms
from tests.conftest import all_items, as_user, make_client
from tests.fixtures.stores import SqliteProbe, base_settings
from tests.integration.test_store_records import same

EMPLOYEE = "https://triad.example/fhir/sid/employee"
LOINC, RXNORM = "http://loinc.org", "http://www.nlm.nih.gov/research/umls/rxnorm"
OKAFOR, PARK, ELENA_KEY = "Doctor:E1005", "Nurse:E1004", "Patient:MRN-000001"
ELENA = SimpleNamespace(id=1)
VISIT = 3                                    # ENC-ELENA-2026-10-02 (the planted recommendations are in it)
WRITTEN_KINDS = ("message", "clinical-entry", "assertion", "medication", "care-team-member", "visit", "patient")
TIME_TERMS = {name for name, datatype in terms.DATATYPES.items() if datatype == "dateTime"}


def doctor() -> Actor:
    return Actor(role="Doctor", key=OKAFOR, name="Amara Okafor", system=EMPLOYEE, value="E1005", staff_id=5)


def patient_actor() -> Actor:
    return Actor(role="Patient", key=ELENA_KEY, name="Elena Marsh", system="https://triad.example/fhir/sid/mrn",
                 value="MRN-000001", patient_id=1)


@dataclass
class Pair:
    """The store and the SQLite reference (a copy of the same data, so a write on one does not touch the other)."""
    store: Any
    kg: Any                      # the AppContext of the store
    ref: Any                     # the AppContext of the reference
    ref_probe: SqliteProbe
    ref_path: Any

    def each(self):
        return (("store", self.kg), ("reference", self.ref))

    def counts(self, name: str) -> dict[str, int]:
        """The number of rows of each written kind (one COUNT for each kind, also on the full data)."""
        import sqlite3
        from infrastructure.sparql.ids import KIND_TABLE
        if name == "store" and self.store.is_kg:
            import main
            client = main.kg_client(self.store.settings)
            return {kind: int(client.select("SELECT (COUNT(?x) AS ?n) FROM $abox WHERE { ?x a $class }",
                                            {"class": terms.class_term(terms.CLASS_OF_KIND[kind])})[0]["n"])
                    for kind in WRITTEN_KINDS}
        path = self.store.db_path if name == "store" else self.ref_path
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {kind: conn.execute(f'SELECT COUNT(*) FROM "{KIND_TABLE[kind]}"').fetchone()[0]
                    for kind in WRITTEN_KINDS}
        finally:
            conn.close()


def open_pair(store, tmp_path) -> Pair:
    import main
    copy = tmp_path / "reference.db"
    shutil.copy(store.db_path, copy)
    return Pair(store, store.open_ctx(), main.context_factory(base_settings(copy))(), SqliteProbe(copy), copy)


@pytest.fixture
def pair(planted_store, tmp_path):
    found = open_pair(planted_store, tmp_path)
    yield found
    found.kg.close()
    found.ref.close()


def stored(probe, kind: str) -> list[dict]:
    """The rows of a kind with each time as an instant."""
    return [{k: parse_time(v) if k in TIME_TERMS and isinstance(v, str) else v for k, v in row.items()}
            for row in probe.rows(kind)]


def assert_same_rows(pair: Pair) -> None:
    for kind in WRITTEN_KINDS:
        assert stored(pair.store.probe, kind) == stored(pair.ref_probe, kind), kind


# ----- the write of a record (the use case write function on each store) -----

def entry(category: str, code: str, display: str, system: str = LOINC, **details) -> NewEntryCmd:
    return NewEntryCmd(category=category, code=code, code_system=system, display=display, details=details)


def prepared(cmds: list[NewAssertionCmd]) -> list[PreparedAssertion]:
    """The checked assertions of the use case (new objects for each store: the write changes them)."""
    out = []
    for cmd in cmds:
        if cmd.new_entry is not None:
            row, medication, dates = records.new_entry_row(cmd.new_entry, cmd.statement)
            out.append(PreparedAssertion(cmd, None, row, medication, dates))
        else:
            out.append(PreparedAssertion(cmd, cmd.entry_id, None, None, ()))
    return out


def write_record(ctx, actor: Actor, make: Callable[[], list[NewAssertionCmd]], visit_id: Optional[int] = VISIT,
                 channel: str = "InPerson") -> tuple[str, int, list[int]]:
    with ctx.uow.write() as now:
        message_id, ids = records.write(ctx, actor, ELENA, prepared(make()), visit_id, False, channel,
                                        "A note of the test.", "Human", now)
    return now, message_id, ids


def write_both(pair: Pair, actor: Actor, make: Callable[[], list[NewAssertionCmd]], rows: bool = True,
               **kwargs) -> list[int]:
    now, message, ids = write_record(pair.kg, actor, make, **kwargs)
    ref_now, ref_message, ref_ids = write_record(pair.ref, actor, make, **kwargs)
    assert parse_time(now) == parse_time(ref_now) and (message, ids) == (ref_message, ref_ids)
    found, expected = pair.kg.records.assertions_by_id(ids), pair.ref.records.assertions_by_id(ids)
    assert sorted(found) == sorted(ids) and same(found) == same(expected)
    if rows:
        assert_same_rows(pair)
    page = PageRequest(200, 0)
    assert same(pair.kg.records.items_page(1, current_only=False, page=page)) == \
           same(pair.ref.records.items_page(1, current_only=False, page=page))
    return ids


def vitals() -> list[NewAssertionCmd]:
    return [NewAssertionCmd("Report", "Confirmed", f"{name} {value}.",
                            new_entry=entry("Observation", code, name, value=value, unit=unit))
            for code, name, value, unit in (("8867-4", "Heart rate", "80", "/min"),
                                            ("8480-6", "Systolic blood pressure", "128", "mm[Hg]"),
                                            ("8310-5", "Body temperature", "37.1", "Cel"))]


def test_three_new_entries_of_one_message_get_three_identifiers(pair):
    """Use case 3: three vitals in one message. next_identifier reads the write buffer (plan 5.3)."""
    ids = write_both(pair, doctor(), vitals)
    entries = [pair.kg.records.assertion(i).entry_id for i in ids]
    values = [pair.store.probe.row("clinical-entry", e)["identifierValue"] for e in entries]
    assert len(set(values)) == 3 and values == sorted(values)
    assert same(pair.kg.records.latest_observations(1, ("8867-4", "8480-6", "8310-5"), visible_only=True, limit=12)) \
        == same(pair.ref.records.latest_observations(1, ("8867-4", "8480-6", "8310-5"), visible_only=True, limit=12))
    write_both(pair, doctor(), vitals)                      # the next message continues the numbers
    assert pair.store.probe.count("message", identifierSystem="https://triad.example/fhir/sid/message") == \
           pair.ref_probe.count("message", identifierSystem="https://triad.example/fhir/sid/message")


def test_the_counts_of_a_chart_page_are_not_used_after_a_write(pair):
    """The KG repository gives the category counts of the last chart page to the next category_counts call with
    the same filters. A write between the two (in this context or in another one) makes it count again."""
    kg = pair.kg.records
    kg.items_page(1, page=PageRequest(5, 0))
    before = kg.category_counts(1)
    assert before == pair.ref.records.category_counts(1)
    kg.items_page(1, page=PageRequest(5, 0))
    write_both(pair, doctor(), vitals)                                   # the same context writes
    assert kg.category_counts(1)["Observation"] == before["Observation"] + 3
    kg.items_page(1, page=PageRequest(5, 0))
    other = pair.store.open_ctx()
    try:
        write_record(other, doctor(), vitals)                            # another context writes
    finally:
        other.close()
    assert kg.category_counts(1)["Observation"] == before["Observation"] + 6


def test_two_prescriptions_with_a_new_medication_use_one_medication(pair):
    """medication_for reads the write buffer: the second prescription finds the new medication."""
    before = pair.store.probe.count("medication")

    def make():
        return [NewAssertionCmd("Decision", "Confirmed", f"Start the test drug ({dose}).",
                                new_entry=entry("Prescription", "TEST-RX-1", "Test drug 10 MG", RXNORM, dosage=dose,
                                                frequency="daily", medicationName="Test drug"))
                for dose in ("10 mg", "20 mg")]
    write_both(pair, doctor(), make)
    assert pair.store.probe.count("medication") == before + 1
    assert pair.store.probe.count("medication", code="TEST-RX-1", name="Test drug") == 1

    def again():                                          # a stored medication: no new row
        return [NewAssertionCmd("Decision", "Confirmed", "Start amlodipine.",
                                new_entry=entry("Prescription", "197361", "Amlodipine 5 MG Oral Tablet", RXNORM))]
    write_both(pair, doctor(), again)
    assert pair.store.probe.count("medication") == before + 1


def test_a_new_entry_of_each_category(pair):
    """The subtype values of each category. The record form sends a date-only onset date (YYYY-MM-DD)."""
    def make():
        return [
            NewAssertionCmd("Decision", "Provisional", "Asthma, mild.",
                            new_entry=entry("Diagnosis", "195967001", "Asthma", "http://snomed.info/sct",
                                            onsetDate="2026-09-01", severity="mild")),
            NewAssertionCmd("Report", "Confirmed", "Spirometry done.",
                            new_entry=entry("Procedure", "127783003", "Spirometry", "http://snomed.info/sct",
                                            performedDate="2026-10-02T10:30:00-04:00", outcome="normal")),
            NewAssertionCmd("Report", "Unconfirmed", "Rash after latex gloves.",
                            new_entry=entry("Allergy", "111088007", "Latex allergy", "http://snomed.info/sct",
                                            substance="Latex", criticality="low", type="allergy")),
            NewAssertionCmd("Recommendation", "Unconfirmed", "Order a lipid panel.",
                            new_entry=entry("LabOrder", "24331-1", "Lipid panel", priority="urgent",
                                            specimen="Serum")),
            NewAssertionCmd("Report", "Confirmed", "The lipid panel is normal.",
                            new_entry=entry("LabReport", "24331-1", "Lipid panel", conclusion="Normal values.")),
            NewAssertionCmd("Report", "Confirmed", "Weight 70 kg.",
                            new_entry=entry("Observation", "29463-7", "Body weight", value="70", unit="kg")),
        ]
    ids = write_both(pair, doctor(), make)
    views = pair.kg.records.assertions_by_id(ids)
    assert [views[i].category for i in ids] == ["Diagnosis", "Procedure", "Allergy", "LabOrder", "LabReport",
                                                "Observation"]
    assert views[ids[0]].details["onsetDate"] == "2026-09-01"            # the text of SQLite
    assert views[ids[4]].details["issuedDate"] is not None               # the time of the write


def test_a_new_assertion_on_an_entry_and_a_new_version_of_an_entry(pair):
    """The entry and version rule: a claim about the same fact (the same entry, it supersedes the head), and a
    claim with new content (a new entry that supersedes the current assertion of another entry)."""
    allergy, diagnosis = pair.kg.records.entry(1), pair.kg.records.entry(3)
    assert allergy == pair.ref.records.entry(1) and diagnosis == pair.ref.records.entry(3)

    def make():
        return [NewAssertionCmd("Decision", "Refuted", "Not allergic. Tested again.", entry_id=1,
                                supersedes_id=allergy.head_id),
                NewAssertionCmd("Decision", "Confirmed", "Hypertension, stage 2.", supersedes_id=diagnosis.head_id,
                                new_entry=entry("Diagnosis", "38341003", "Hypertension stage 2",
                                                "http://snomed.info/sct", clinicalStatus="active"))]
    ids = write_both(pair, doctor(), make)
    for entry_id in (1, 3, pair.kg.records.assertion(ids[1]).entry_id):
        assert pair.kg.records.entry(entry_id) == pair.ref.records.entry(entry_id)
    for start in (allergy.head_id, ids[0], 1):
        assert same(pair.kg.records.chain(start)) == same(pair.ref.records.chain(start))
        assert same(pair.kg.records.chain_head(start)) == same(pair.ref.records.chain_head(start))
    assert pair.kg.records.chain_head(1).id == ids[0]


def test_a_patient_report_has_no_issuer(pair):
    def make():
        return [NewAssertionCmd("Report", "Unconfirmed", "I feel dizzy in the morning.",
                                new_entry=entry("Observation", "8661-1", "Chief complaint",
                                                value="Dizzy in the morning."))]
    ids = write_both(pair, patient_actor(), make, channel="App")
    view = pair.kg.records.assertion(ids[0])
    assert view.author.role == "Patient" and view.author.staff_id is None and view.patient_visible
    assert pair.store.probe.row("message", view.message_id)["issues"] is None


def set_care_team(ctx, members: list[tuple[str, str, Optional[str]]], name: Optional[str] = "The new team"):
    """The writes of visits.set_care_team: a CareTeam entry with its members, one message, one assertion."""
    previous = ctx.records.care_team_versions(VISIT)
    head = previous[0] if previous else None
    with ctx.uow.write() as now:
        entry_ident = (ctx.identity.entry, ctx.records.next_identifier("ClinicalEntry", ctx.identity.entry,
                                                                       "ENTRY-", 6))
        entry_id = ctx.records.add_entry(entry_ident, NewEntryRow(
            visit_id=VISIT, category="CareTeam", code="care-team", code_system=ctx.identity.local_codes,
            display=name or "Care team", text=None, recorded_at=now, details={"Name": name, "Status": "active"},
            members=members))
        message_ident = (ctx.identity.message, ctx.records.next_identifier("Message", ctx.identity.message,
                                                                           "MSG-", 6))
        message_id = ctx.records.add_message(message_ident, 5, "InPerson", "Staff", now, "Care team change.")
        return ctx.records.add_assertion(message_id, 1, entry_id, head.assertion_id if head else None, now,
                                         "Report", "Human", "Confirmed", "Care team change.")


def test_a_new_care_team_supersedes_the_current_care_team(pair):
    members = [(EMPLOYEE, "E1006", "attender"), (EMPLOYEE, "E1004", None), (EMPLOYEE, "E1002", "nurse")]
    assert same(pair.kg.records.care_team_versions(VISIT)) == same(pair.ref.records.care_team_versions(VISIT))
    for _ in range(2):                                     # a chain of three versions
        assert set_care_team(pair.kg, members) == set_care_team(pair.ref, members)
        versions = pair.kg.records.care_team_versions(VISIT)
        assert same(versions) == same(pair.ref.records.care_team_versions(VISIT))
    assert_same_rows(pair)
    assert len(versions) >= 3 and versions[0].is_current and not versions[1].is_current
    assert [m.value for m in versions[0].members] == ["E1006", "E1004", "E1002"]         # by member id
    head = pair.kg.records.assertion(versions[0].assertion_id)
    assert head.details["members"] == pair.ref.records.assertion(versions[0].assertion_id).details["members"]


# ----- one INSERT DATA, and a failure leaves no half record -----

class Recorder:
    """A SPARQL client that records the updates and can fail the n-th update (before it reaches the store)."""

    def __init__(self, client, fail_on: int = 0):
        self.client, self.fail_on, self.updates = client, fail_on, []

    def __getattr__(self, name):
        return getattr(self.client, name)

    def update(self, template, bindings=None):
        self.updates.append(template)
        if self.fail_on and len(self.updates) == self.fail_on:
            from infrastructure.sparql.client import SparqlStoreError
            raise SparqlStoreError("A forced failure of the test.")
        self.client.update(template, bindings)


@pytest.mark.stores("oxigraph", "virtuoso")
def test_a_record_is_one_insert_data_and_a_failure_leaves_no_half_record(pair):
    from infrastructure.sparql.client import SparqlStoreError
    session = pair.kg.records.session
    recorder = session.client = Recorder(session.client, fail_on=1)
    before = pair.counts("store")
    with pytest.raises(SparqlStoreError, match="forced"):
        write_record(pair.kg, doctor(), vitals)
    assert pair.counts("store") == before                        # no message, entry or assertion
    assert len(recorder.updates) == 1 and recorder.updates[0].startswith("INSERT DATA")
    recorder.fail_on = 0
    ids = write_both(pair, doctor(), vitals)                     # the next write gets the same ids as SQLite
    assert len(recorder.updates) == 2 and recorder.updates[1].startswith("INSERT DATA") and len(ids) == 3


# ----- the guards: the same error on both stores -----

def outcome(pair: Pair, write: Callable[[Any, str], None]) -> list[tuple]:
    """Run a write on each store. Return (class, message, fields) of each error, and check that nothing changed."""
    found = []
    for name, ctx in pair.each():
        before = pair.counts(name)
        try:
            with ctx.uow.write() as now:
                write(ctx, now)
            found.append(None)
        except DomainError as error:
            found.append((type(error).__name__, error.message, error.fields))
        assert pair.counts(name) == before or found[-1] is None, name
    return found


def is_sqlite(ctx) -> bool:
    return hasattr(ctx.records, "conn")


def new_message(ctx, now: str, staff_id: Optional[int] = 5) -> int:
    value = ctx.records.next_identifier("Message", ctx.identity.message, "MSG-", 6)
    return ctx.records.add_message((ctx.identity.message, value), staff_id, "InPerson", "Staff", now, "A test.")


def new_entry_in(ctx, now: str, visit_id: int = VISIT, category: str = "Observation") -> int:
    value = ctx.records.next_identifier("ClinicalEntry", ctx.identity.entry, "ENTRY-", 6)
    details = {"Value": "1"} if category == "Observation" else {"ClinicalStatus": "active"}
    return ctx.records.add_entry((ctx.identity.entry, value), NewEntryRow(
        visit_id=visit_id, category=category, code="test", code_system="urn:test", display="A test entry", text=None,
        recorded_at=now, details=details))


def assertion(ctx, message: int, seq: int, entry_id: int, supersedes: Optional[int], at: str) -> int:
    return ctx.records.add_assertion(message, seq, entry_id, supersedes, at, "Decision", "Human", "Confirmed",
                                     "A test assertion.")


def other_patient_visit(ctx, now: str) -> int:
    """A second patient with a visit, in the open write (SQL on SQLite, the write buffer on the KG)."""
    if is_sqlite(ctx):
        conn = ctx.records.conn
        patient = conn.execute("INSERT INTO Patient (Name, DateOfBirth, Sex) "
                               "VALUES ('Test Person', '1990-01-02', 'other')").lastrowid
        return conn.execute("INSERT INTO Visit (IdentifierSystem, IdentifierValue, PatientId, Class, StartDate) "
                            "VALUES ('urn:test', 'V-TEST-1', ?, 'AMB', ?)", (patient, now)).lastrowid
    from infrastructure.sparql.terms import iri
    buf = ctx.records.session.write_buffer()
    patient = buf.create("patient", {"name": "Test Person", "dateOfBirth": "1990-01-02", "patientSex": "other"})
    visit = buf.create("visit", {"identifierSystem": "urn:test", "identifierValue": "V-TEST-1",
                                 "visitClass": "AMB", "startDate": now})
    buf.add(iri("patient", patient), {"hasVisit": iri("visit", visit)})
    return visit


def explicit_assertion(ctx, message: int, entry_id: int, assertion_id: int, supersedes: int, at: str,
                       seq: int = 1) -> None:
    """An assertion with a given id (the port has no id argument): SQL on SQLite, the write buffer on the KG."""
    if is_sqlite(ctx):
        ctx.records.conn.execute(
            "INSERT INTO Assertion (Id, MessageId, Seq, ClinicalEntryId, SupersedesId, AssertedAt, Intent, Source, "
            "Verification, Statement) VALUES (?, ?, ?, ?, ?, ?, 'Decision', 'Human', 'Confirmed', 'x')",
            (assertion_id, message, seq, entry_id, supersedes, at))
        return
    from infrastructure.sparql.terms import iri
    buf = ctx.records.session.write_buffer()
    buf.create("assertion", {"seq": seq, "about": iri("clinical-entry", entry_id), "assertedAt": at,
                             "supersedes": iri("assertion", supersedes), "intent": "Decision", "source": "Human",
                             "verification": "Confirmed", "statement": "x"}, id=assertion_id)
    buf.add(iri("message", message), {"contains": iri("assertion", assertion_id)})


def next_assertion_id(pair: Pair) -> int:
    return max(r["id"] for r in pair.store.probe.rows("assertion")) + 1


def head_of(pair: Pair, entry_id: int) -> int:
    return pair.ref.records.entry(entry_id).head_id


TRIGGER = "Invalid"
ONE_HEAD = (TRIGGER, "The entry has a current assertion. The new assertion must supersede it.", None)
NEWER = (TRIGGER, "The superseded assertion is newer than the new assertion.", None)
OTHER_PATIENT = (TRIGGER, "The superseded assertion is about another patient.", None)
ONE_PATIENT = (TRIGGER, "All assertions of a message must be about one patient.", None)
NOT_STAFF = (TRIGGER, "The care-team member is not a staff member.", None)
NOT_ITSELF = ("Invalid", "The input is not correct.",
              {"database": "CHECK constraint failed: SupersedesId IS NULL OR SupersedesId <> Id"})
FOREIGN_KEY = ("Conflict", "The row is in use, or it points to a row that does not exist.", None)


def test_a_new_assertion_must_supersede_the_head_of_its_entry(pair):
    head = head_of(pair, 1)
    assert outcome(pair, lambda ctx, now: assertion(ctx, new_message(ctx, now), 1, 1, None, now)) == [ONE_HEAD] * 2
    older = pair.ref.records.chain(head)[1].id
    assert outcome(pair, lambda ctx, now: assertion(ctx, new_message(ctx, now), 1, 1, older, now)) == \
           [ONE_HEAD] * 2                                  # SQLite runs this trigger before the supersede check

    def two_heads(ctx, now):                              # the second one sees the first one (the new head)
        message = new_message(ctx, now)
        assertion(ctx, message, 1, 1, head, now)
        assertion(ctx, message, 2, 1, head, now)
    assert outcome(pair, two_heads) == [ONE_HEAD] * 2

    def a_chain_in_one_write(ctx, now):                    # correct: each one supersedes the head before it
        message = new_message(ctx, now)
        first = assertion(ctx, message, 1, 1, head, now)
        assertion(ctx, message, 2, 1, first, now)
    assert outcome(pair, a_chain_in_one_write) == [None, None]
    assert_same_rows(pair)


def test_the_superseded_assertion_is_not_newer_and_is_about_the_same_patient(pair):
    head = head_of(pair, 1)
    assert outcome(pair, lambda ctx, now: assertion(ctx, new_message(ctx, now), 1, 1, head,
                                                    "2001-01-01T00:00:00Z")) == [NEWER] * 2
    # The same instant in another offset is not newer (julianday and the instant, not the text).
    at = pair.ref.records.assertion(head).asserted_at
    same_instant = parse_time(at).astimezone(parse_time("2026-01-01T00:00:00+05:30").tzinfo).isoformat()
    assert outcome(pair, lambda ctx, now: assertion(ctx, new_message(ctx, now), 1, 1, head, same_instant)) == \
           [None, None]

    def other_patient(ctx, now):
        visit = other_patient_visit(ctx, now)
        assertion(ctx, new_message(ctx, now), 1, new_entry_in(ctx, now, visit), head_of(pair, 3), now)
    assert outcome(pair, other_patient) == [OTHER_PATIENT] * 2
    assert_same_rows(pair)


def test_all_assertions_of_a_message_are_about_one_patient(pair):
    def two_patients(ctx, now):
        message = new_message(ctx, now)
        assertion(ctx, message, 1, new_entry_in(ctx, now), None, now)
        assertion(ctx, message, 2, new_entry_in(ctx, now, other_patient_visit(ctx, now)), None, now)
    assert outcome(pair, two_patients) == [ONE_PATIENT] * 2

    def stored_message(ctx, now):                           # a new assertion in a stored message of Elena
        assertion(ctx, 1, 9, new_entry_in(ctx, now, other_patient_visit(ctx, now)), None, now)
    assert outcome(pair, stored_message) == [ONE_PATIENT] * 2


def test_an_assertion_cannot_supersede_itself_or_a_later_one(pair):
    number = next_assertion_id(pair)

    def itself(ctx, now):
        explicit_assertion(ctx, new_message(ctx, now), new_entry_in(ctx, now), number, number, now)
    assert outcome(pair, itself) == [NOT_ITSELF] * 2

    def cycle(ctx, now):                                    # a cycle of two: SQLite fails on the FOREIGN KEY
        message, entry_id = new_message(ctx, now), new_entry_in(ctx, now)
        explicit_assertion(ctx, message, entry_id, number, number + 1, now)
        explicit_assertion(ctx, message, entry_id, number + 1, number, now, seq=2)
    assert outcome(pair, cycle) == [FOREIGN_KEY] * 2


def test_a_care_team_member_is_a_staff_member(pair):
    for members in ([("urn:test", "E1005", None)], [(EMPLOYEE, "E9999", None)],
                    [(EMPLOYEE, "E1005", None), (EMPLOYEE, "nobody", "nurse")]):
        assert outcome(pair, lambda ctx, now: new_care_team(ctx, now, members)) == [NOT_STAFF] * 2, members
    assert outcome(pair, lambda ctx, now: new_care_team(ctx, now, [(EMPLOYEE, "E1005", None)])) == [None, None]
    assert_same_rows(pair)


def new_care_team(ctx, now, members):
    value = ctx.records.next_identifier("ClinicalEntry", ctx.identity.entry, "ENTRY-", 6)
    ctx.records.add_entry((ctx.identity.entry, value), NewEntryRow(
        visit_id=VISIT, category="CareTeam", code="care-team", code_system="urn:test", display="Team", text=None,
        recorded_at=now, details={"Name": "Team", "Status": "proposed"}, members=members))


def is_stub(function) -> bool:
    body = ast.parse(inspect.getsource(function).lstrip()).body[0].body
    return len(body) == 1 and isinstance(body[0], ast.Expr)


def test_one_new_assertion_for_each_old_one(pair):
    """UK_Assertion_SupersedesId. Two new entries whose assertions supersede the same old assertion: SQLite gives
    UNIQUE (409). The key guard of agent D (key.assertion) holds it on the KG. On one entry, the one-head trigger
    comes first (422) on both stores."""
    from infrastructure.sparql import guards_directory
    head = head_of(pair, 1)

    def two_entries(ctx, now):
        message = new_message(ctx, now)
        assertion(ctx, message, 1, new_entry_in(ctx, now, category="Diagnosis"), head, now)
        assertion(ctx, message, 2, new_entry_in(ctx, now, category="Diagnosis"), head, now)
    if pair.store.is_kg and is_stub(guards_directory.assertion_keys):
        pytest.skip("Agent D writes the key guard key.assertion (guards_directory.py).")
    assert outcome(pair, two_entries) == [("Conflict", "A row with the same key exists already.",
                                           {"key": "Assertion.SupersedesId"})] * 2


# ----- the full data (slow): each write query and guard query once, and the time of a record write -----

@pytest.fixture
def full_pair(full_store, tmp_path):
    found = open_pair(full_store, tmp_path)
    yield found
    found.kg.close()
    found.ref.close()


def test_the_writes_and_the_guards_on_the_full_data(full_pair):
    import time
    pair = full_pair
    first = pair.ref.records.entry(3).head_id

    def make():                         # the reference is not written yet when the store writes: the same head
        head = pair.ref.records.chain_head(first).id
        return [*vitals(),
                NewAssertionCmd("Decision", "Confirmed", "Start amlodipine.",
                                new_entry=entry("Prescription", "197361", "Amlodipine 5 MG Oral Tablet", RXNORM)),
                NewAssertionCmd("Decision", "Confirmed", "Hypertension, stage 2.", supersedes_id=head,
                                new_entry=entry("Diagnosis", "38341003", "Hypertension stage 2",
                                                "http://snomed.info/sct"))]
    write_record(pair.kg, doctor(), make)                                 # the first write reads the counters
    write_record(pair.ref, doctor(), make)
    start = time.perf_counter()
    write_both(pair, doctor(), make, rows=False)
    seconds = time.perf_counter() - start
    assert seconds < pair.store.time_limit(1.0), f"two record writes and their reads took {seconds:.3f} s"
    members = [(EMPLOYEE, "E1006", "attender"), (EMPLOYEE, "E1004", None)]
    assert set_care_team(pair.kg, members) == set_care_team(pair.ref, members)
    assert same(pair.kg.records.care_team_versions(VISIT)) == same(pair.ref.records.care_team_versions(VISIT))
    head = pair.ref.records.entry(1).head_id
    assert outcome(pair, lambda ctx, now: assertion(ctx, new_message(ctx, now), 1, 1, None, now)) == [ONE_HEAD] * 2
    assert outcome(pair, lambda ctx, now: assertion(ctx, new_message(ctx, now), 1, 1, head,
                                                    "2001-01-01T00:00:00Z")) == [NEWER] * 2
    assert outcome(pair, lambda ctx, now: new_care_team(ctx, now, [(EMPLOYEE, "E9999", None)])) == [NOT_STAFF] * 2


# ----- through the API (needs the ports of agents C and D on the KG) -----

def needs_the_other_ports(store) -> None:
    if not store.is_kg:
        return
    ctx = store.open_ctx()
    try:
        for check in (lambda: ctx.patients.get(1), lambda: ctx.visits.get(VISIT), lambda: ctx.audit.denied_count(
                ("Elena Marsh", "1971-05-14")), lambda: ctx.directory.staff_by_identifier(EMPLOYEE, "E1005")):
            try:
                check()
            except NotImplementedError as error:
                pytest.skip(f"The KG port of {error} is a stub.")
    finally:
        ctx.close()


@pytest.fixture
def api_pair(planted_store, tmp_path):
    needs_the_other_ports(planted_store)
    copy = tmp_path / "reference.db"
    shutil.copy(planted_store.db_path, copy)
    return planted_store.client(), make_client(copy)


def post(client, user: str, assertions: list[dict], **extra):
    return client.post("/api/messages", headers=as_user(user),
                       json={"patientId": 1, "text": "A note.", "assertions": assertions, **extra})


def strip_times(value):
    """A response body with each time as an instant (D11) and with no ids of audit rows."""
    if isinstance(value, dict):
        return {k: (parse_time(v) if isinstance(v, str) and k in ("assertedAt", "onsetDate", "performedDate",
                                                                 "issuedDate", "abatementDate") and v else
                    strip_times(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_times(v) for v in value]
    return value


def test_the_record_endpoints_give_the_same_responses(api_pair):
    api, reference = api_pair
    cases = [
        (OKAFOR, [{"newEntry": {"category": "Observation", "code": "8867-4", "codeSystem": LOINC,
                                "display": "Heart rate", "details": {"value": "72", "unit": "/min"}},
                   "intent": "Report", "verification": "Confirmed", "statement": "Heart rate 72."}] * 3, {}),
        (OKAFOR, [{"newEntry": {"category": "Diagnosis", "code": "195967001", "codeSystem": "http://snomed.info/sct",
                                "display": "Asthma", "details": {"onsetDate": "2026-09-01"}},
                   "intent": "Decision", "verification": "Confirmed", "statement": "Asthma."}], {"visitId": VISIT}),
        (OKAFOR, [{"entryId": 1, "supersedesId": 2, "intent": "Decision", "verification": "Refuted",
                   "statement": "Not allergic."}], {}),                      # 409: not the head
        (PARK, [{"entryId": 1, "supersedesId": 19, "intent": "Report", "verification": "Unconfirmed",
                 "statement": "Maybe."}], {}),                               # 403 (the audit log)
        (ELENA_KEY, [{"newEntry": {"category": "Observation", "code": "8661-1", "codeSystem": LOINC,
                                   "display": "Chief complaint", "details": {"value": "Dizzy."}},
                      "intent": "Report", "verification": "Unconfirmed", "statement": "I feel dizzy."}], {}),
        (OKAFOR, [{"intent": "Decision", "verification": "Refuted", "statement": "x"}], {}),          # 422
    ]
    for user, assertions, extra in cases:
        found, expected = post(api, user, assertions, **extra), post(reference, user, assertions, **extra)
        assert found.status_code == expected.status_code, (user, found.text, expected.text)
        assert strip_times(found.json()) == strip_times(expected.json()), user
    for user in (OKAFOR, ELENA_KEY):
        for params in ({}, {"history": "true"}, {"category": "Observation"}, {"q": "heart"},
                       {"from": "2026-10-02", "to": "2026-10-30"}):
            found = all_items(api, "/api/patients/1/chart", user, **params)
            assert strip_times(found) == strip_times(all_items(reference, "/api/patients/1/chart", user, **params))
            body = api.get("/api/patients/1/chart", headers=as_user(user), params=params).json()
            assert body["counts"] == reference.get("/api/patients/1/chart", headers=as_user(user),
                                                   params=params).json()["counts"]
    for assertion_id in (1, 3, 19):
        for user in (OKAFOR, ELENA_KEY):
            found = api.get(f"/api/assertions/{assertion_id}/chain", headers=as_user(user))
            expected = reference.get(f"/api/assertions/{assertion_id}/chain", headers=as_user(user))
            assert found.status_code == expected.status_code
            assert strip_times(found.json()) == strip_times(expected.json())


def test_the_care_team_endpoints_give_the_same_responses(api_pair):
    api, reference = api_pair
    body = {"members": [{"system": EMPLOYEE, "value": "E1005"}, {"system": EMPLOYEE, "value": "E1004"}]}
    for client in (api, reference):
        assert client.get(f"/api/visits/{VISIT}/care-team", headers=as_user(OKAFOR)).status_code == 200
    found = api.put(f"/api/visits/{VISIT}/care-team", headers=as_user("MOA:E1001"), json=body)
    expected = reference.put(f"/api/visits/{VISIT}/care-team", headers=as_user("MOA:E1001"), json=body)
    assert found.status_code == expected.status_code == 200, found.text
    assert strip_times(found.json()) == strip_times(expected.json())
    wrong = {"members": [{"system": EMPLOYEE, "value": "E9999"}]}
    found = api.put(f"/api/visits/{VISIT}/care-team", headers=as_user("MOA:E1001"), json=wrong)
    expected = reference.put(f"/api/visits/{VISIT}/care-team", headers=as_user("MOA:E1001"), json=wrong)
    assert (found.status_code, found.json()) == (expected.status_code, expected.json())

