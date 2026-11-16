"""The unit of work of the knowledge graph (plan 5.3) and the guard framework (plan 5.4), on a copy of the scenario
graph (Oxigraph; Virtuoso with TRIAD_TEST_STORES=virtuoso).

A Recorder client between the unit of work and the store records each update request, and it can force a failure
of the n-th update (the forced-failure test of plan 5.3).
"""
from __future__ import annotations

import threading
import time

import pytest

from domain.errors import Conflict, Invalid

from infrastructure.clock import DemoClock
from infrastructure.sparql import guards, ids
from infrastructure.sparql.client import SparqlStoreError
from infrastructure.sparql.terms import iri
from infrastructure.sparql.unit_of_work import KgSession, NestedWriteError, SparqlUnitOfWork
from tests.fixtures.stores import DEMO_NOW

pytestmark = pytest.mark.stores("oxigraph", "virtuoso")

MEDICATION = {"code": "T-1", "codeSystem": "urn:test", "name": "Test medication"}


class Recorder:
    """A SPARQL client that records the updates and can fail the n-th update (before it reaches the store)."""

    def __init__(self, client, fail_on: int = 0):
        self.client = client
        self.fail_on = fail_on
        self.updates: list[str] = []
        self.reads = 0

    @property
    def store(self):
        return self.client.store

    @property
    def key(self):
        return self.client.key

    def select(self, template, bindings=None, *, raw=False):
        self.reads += 1
        return self.client.select(template, bindings, raw=raw)

    def ask(self, template, bindings=None):
        self.reads += 1
        return self.client.ask(template, bindings)

    def update(self, template, bindings=None):
        self.updates.append(template)
        if self.fail_on and len(self.updates) == self.fail_on:
            raise SparqlStoreError("A forced failure of the test.")
        self.client.update(template, bindings)


def unit(store, fail_on: int = 0):
    import main
    recorder = Recorder(main.kg_client(store.settings), fail_on)
    session = KgSession(recorder)
    return session, SparqlUnitOfWork(session, DemoClock(DEMO_NOW)), recorder


def phone_and_city(store) -> tuple:
    row = store.probe.row("patient", 1)
    return row["phoneNumber"], row["city"]


# ----- the write lock -----

def test_a_write_inside_a_write_fails_at_once(store):
    session, uow, _ = unit(store)
    with uow.write():
        with pytest.raises(NestedWriteError):
            with uow.write():
                pass
        other = SparqlUnitOfWork(KgSession(session.client), DemoClock(DEMO_NOW))   # the same store, a new session
        with pytest.raises(NestedWriteError):
            with other.write():
                pass
    with uow.write():          # the lock is free again
        pass


def test_a_write_of_another_thread_waits_for_the_lock(store):
    session, uow, _ = unit(store)
    entered = threading.Event()

    def other_write():
        _, other, _ = unit(store)
        with other.write():
            entered.set()

    with uow.write():
        worker = threading.Thread(target=other_write)
        worker.start()
        time.sleep(0.2)
        assert not entered.is_set()
    worker.join(5)
    assert entered.is_set()


# ----- appends, changes and the times -----

def test_an_append_is_one_insert_data(store):
    session, uow, recorder = unit(store)
    with uow.write() as now:
        buf = session.write_buffer()
        medication = buf.create("medication", MEDICATION)
        visit = buf.create("visit", {"identifierSystem": "urn:test", "identifierValue": "V-1", "visitClass": "AMB",
                                     "startDate": now, "reason": 'A "quoted" reason'})
        buf.add(iri("patient", 1), {"hasVisit": iri("visit", visit)})
        assert buf.find("medication", code="T-1") == [medication]
    assert len(recorder.updates) == 1 and recorder.updates[0].startswith("INSERT DATA")
    assert {k: store.probe.row("medication", medication)[k] for k in MEDICATION} == MEDICATION
    row = store.probe.row("visit", visit)
    assert row["hasVisit"] == 1 and row["reason"] == 'A "quoted" reason' and row["startDate"] == now
    assert uow.now() == now == "2026-10-30T09:01:00-04:00"   # the latest time of the store is the new visit
    counters = ids.read_counters(session.client)
    assert counters["medication"] == medication and counters["visit"] == visit


def test_a_change_is_one_delete_insert_for_each_property(store):
    session, uow, recorder = unit(store)
    with uow.write():
        session.write_buffer().replace(iri("patient", 1), "phoneNumber", "+1-555-0100")
        session.write_buffer().replace(iri("patient", 1), "city", None)
    assert len(recorder.updates) == 2 and all(u.startswith("WITH $abox") for u in recorder.updates)
    assert phone_and_city(store) == ("+1-555-0100", None)
    with uow.write():                                       # a subject that does not exist gets no triple
        session.write_buffer().replace(iri("patient", 999), "phoneNumber", "1")
    assert store.probe.row("patient", 999) is None
    assert not session.client.ask("ASK FROM $abox WHERE { $s ?p ?o }", {"s": iri("patient", 999)})


def test_an_error_in_the_block_writes_nothing(store):
    session, uow, recorder = unit(store)
    with pytest.raises(RuntimeError):
        with uow.write():
            session.write_buffer().create("medication", MEDICATION)
            raise RuntimeError("stop")
    assert recorder.updates == [] and store.probe.count("medication", code="T-1") == 0


def test_a_wrong_value_is_invalid_as_a_failed_check(store):
    session, uow, recorder = unit(store)
    with pytest.raises(Invalid) as error:
        with uow.write():
            session.write_buffer().create("visit", {"startDate": "not a time"})
    assert error.value.message == "The input is not correct." and "xsd:dateTime" in error.value.fields["database"]
    with pytest.raises(RuntimeError):
        session.write_buffer()                              # no write: the buffer is gone
    assert recorder.updates == []
    with pytest.raises(ValueError, match="stored property"):              # an error of the code, not of the input
        with uow.write():
            session.write_buffer().create("medication", {"phone": "1"})   # not a property of the ontology


def test_writes_need_a_unit_of_work(store):
    session, _, _ = unit(store)
    with pytest.raises(RuntimeError, match="ctx.uow.write"):
        session.write_buffer()


# ----- the compensation (plan 5.3: a failure in the second operation) -----

def test_a_failure_in_the_second_operation_undoes_the_first(store):
    before = phone_and_city(store)
    session, uow, recorder = unit(store, fail_on=2)
    with pytest.raises(SparqlStoreError, match="forced"):
        with uow.write():
            buf = session.write_buffer()
            buf.replace(iri("patient", 1), "phoneNumber", "+1-555-0199")
            buf.replace(iri("patient", 1), "city", "Victoria")
            buf.create("medication", MEDICATION)
    assert phone_and_city(store) == before                  # the first change is undone
    assert store.probe.count("medication", code="T-1") == 0     # the INSERT DATA was never sent
    assert len(recorder.updates) == 3 and recorder.updates[0] == recorder.updates[2]   # the inverse of the first


def test_a_failure_of_the_insert_undoes_the_changes_and_the_deletes(store):
    before = store.probe.row("location", 19)
    assert before is not None and store.probe.count("visit-location", atLocation=19) == 0
    session, uow, recorder = unit(store, fail_on=3)
    with pytest.raises(SparqlStoreError):
        with uow.write():
            buf = session.write_buffer()
            buf.replace(iri("patient", 1), "phoneNumber", "+1-555-0199")
            buf.delete_subject("location", 19)
            buf.create("medication", MEDICATION)
    assert store.probe.row("location", 19) == before and store.probe.row("patient", 1)["phoneNumber"] != "+1-555-0199"


class RefusedRecorder(Recorder):
    """The n-th update goes to a graph that the user triad cannot write, so the STORE refuses it (not the test)."""

    def update(self, template, bindings=None):
        self.updates.append(template)
        if len(self.updates) == self.fail_on:
            template = template.replace("$abox", "<urn:triad:test:no-write>")
        self.client.update(template, bindings)


@pytest.mark.stores("virtuoso")
def test_virtuoso_refuses_the_second_operation_and_the_inverse_undoes_the_first(store):
    """Virtuoso has no transaction over two requests (plan 5.3): the first replace stays when the second one fails.
    The commit sends the inverse of the first one. The refusal is the real answer of Virtuoso (HTTP 500)."""
    import main
    before = store.probe.row("patient", 1)
    recorder = RefusedRecorder(main.kg_client(store.settings), fail_on=2)
    session = KgSession(recorder)
    uow = SparqlUnitOfWork(session, DemoClock(DEMO_NOW))
    with pytest.raises(SparqlStoreError) as refused:
        with uow.write():
            buf = session.write_buffer()
            buf.replace(iri("patient", 1), "phoneNumber", '+1-555-0199 "quoted" \\ é')
            buf.replace(iri("patient", 1), "city", "Victoria")
            buf.create("medication", MEDICATION)
    assert refused.value.status == 500                          # the store refused the write to the graph
    assert len(recorder.updates) == 3                           # replace, refused replace, the inverse of the first
    assert store.probe.row("patient", 1) == before              # the first change is undone
    assert store.probe.count("medication", code="T-1") == 0


# ----- the ids -----

def test_an_id_is_never_used_again(store):
    session, uow, _ = unit(store)
    with uow.write():
        first = session.write_buffer().create("medication", MEDICATION)
    with uow.write():
        session.write_buffer().delete_subject("medication", first)
    assert store.probe.row("medication", first) is None
    with uow.write():
        second = session.write_buffer().create("medication", MEDICATION)
    assert second == first + 1


def test_a_counter_behind_the_data_gives_conflict_and_is_seeded_again(store):
    session, uow, _ = unit(store)
    stored = store.probe.count("medication")
    session.client.update("WITH $meta DELETE { $c ?p ?o } WHERE { $c ?p ?o }", {"c": ids.counter_iri("medication")})
    session.client.update("INSERT DATA { GRAPH $meta { $c triad:issued 0 } }", {"c": ids.counter_iri("medication")})
    with pytest.raises(Conflict, match="counters"):
        with uow.write():
            assert session.write_buffer().create("medication", MEDICATION) == 1    # medication/1 exists
    assert store.probe.count("medication") == stored
    with uow.write():
        new = session.write_buffer().create("medication", MEDICATION)
    assert new == stored + 1


def test_next_identifier_reads_the_buffer(store):
    session, uow, recorder = unit(store)
    values = []
    with pytest.raises(RuntimeError, match="no commit"):
        with uow.write():
            buf = session.write_buffer()
            for _ in range(3):   # use case 3: three vitals in one message
                value = ids.next_identifier(session, "clinical-entry", "urn:test:entry", "ENTRY-", 4)
                values.append(value)
                buf.create("clinical-entry", {"identifierSystem": "urn:test:entry", "identifierValue": value})
            assert ids.unique_identifier(session, "clinical-entry", "urn:test:entry", "ENTRY-0001") == "ENTRY-0001-2"
            raise RuntimeError("no commit")   # the entries have no visit: do not keep them
    assert values == ["ENTRY-0001", "ENTRY-0002", "ENTRY-0003"] and recorder.updates == []
    stored = store.probe.rows("clinical-entry")[0]           # a stored value counts too
    system, value = stored["identifierSystem"], stored["identifierValue"]
    with uow.write():
        assert ids.unique_identifier(session, "clinical-entry", system, value) == f"{value}-2"


# ----- the guards of agent A -----

def test_the_delete_allow_list_refuses_the_append_only_kinds(store):
    session, uow, recorder = unit(store)
    cases = [("assertion", "Assertion is append-only. Add a new assertion that supersedes it."),
             ("audit-event", "AuditEvent is append-only.")]
    for kind, text in cases:
        with pytest.raises(Invalid) as error:
            with uow.write():
                session.write_buffer().delete_subject(kind, 1)
        assert error.value.message == text
    with pytest.raises(Invalid, match="append-only"):
        with uow.write():
            session.write_buffer().replace(iri("assertion", 1), "statement", "x")
    with pytest.raises(ValueError, match="allow-list"):
        with uow.write():
            session.write_buffer().delete_subject("visit", 1)
    assert recorder.updates == [] and store.probe.count("assertion") == 10


def test_a_delete_of_a_row_in_use_is_a_foreign_key_conflict(store):
    session, uow, _ = unit(store)
    for kind, id_ in (("patient", 1), ("location", store.probe.rows("visit-location")[0]["atLocation"]),
                      ("department", 1), ("staff", 1)):
        with pytest.raises(Conflict, match="in use"):
            with uow.write():
                session.write_buffer().delete_subject(kind, id_)
    assert store.probe.row("patient", 1) is not None


def test_a_patient_and_its_identifiers_go_in_one_write(store):
    session, uow, recorder = unit(store)
    with uow.write():
        buf = session.write_buffer()
        patient = buf.create("patient", {"name": "Test Person", "dateOfBirth": "1990-01-02", "patientSex": "other"})
        identifier = buf.create("patient-identifier", {"identifierSystem": "urn:test", "identifierValue": "T-9"})
        buf.add(iri("patient", patient), {"identifier": iri("patient-identifier", identifier)})
    assert store.probe.row("patient-identifier", identifier)["identifier"] == patient
    with pytest.raises(Conflict):                               # the identifier still points to the patient
        with uow.write():
            session.write_buffer().delete_subject("patient", patient)
    with uow.write():
        session.write_buffer().delete_subject("patient-identifier", identifier)
        session.write_buffer().delete_subject("patient", patient)
    assert store.probe.row("patient", patient) is None and store.probe.row("patient-identifier", identifier) is None


def test_a_new_link_to_a_row_that_does_not_exist_is_a_conflict(store):
    session, uow, _ = unit(store)
    with pytest.raises(Conflict, match="does not exist"):
        with uow.write():
            session.write_buffer().add(iri("patient", 1), {"hasVisit": iri("visit", 9999)})
    with pytest.raises(Conflict):
        with uow.write():
            session.write_buffer().add(iri("patient", 9999), {"phoneNumber": "1"})


def test_the_patient_key_cannot_change(store):
    session, uow, _ = unit(store)
    with pytest.raises(Invalid, match="cannot change"):
        with uow.write():
            session.write_buffer().replace(iri("patient", 1), "name", "Another Name")
    with uow.write():                                           # the same value is not a change (as in SQLite)
        session.write_buffer().replace(iri("patient", 1), "dateOfBirth", "1971-05-14")
    assert store.probe.row("patient", 1)["name"] == "Elena Marsh"


# ----- the guard framework -----

def test_the_guards_of_each_agent_are_registered():
    found = {g.name: g for g in guards.registered()}
    assert [g.owner for g in guards.registered()][:3] == ["A", "A", "A"]
    assert {g.owner for g in found.values()} == {"A", "B", "C", "D"}
    assert found["assertion.one-head-per-entry"].module == "infrastructure.sparql.guards_records"
    assert found["citation.check"].module == "infrastructure.sparql.guards_chat"
    assert found["key.medication"].module == "infrastructure.sparql.guards_directory"
    with pytest.raises(ValueError, match="kinds"):
        guards.register("x", kinds=("nothing",), owner="A")


def test_a_registered_guard_runs_on_its_kinds_and_its_error_stops_the_write(store, monkeypatch):
    monkeypatch.setattr(guards, "_REGISTRY", dict(guards._REGISTRY))
    seen = []

    @guards.register("test.medication-name", kinds=("medication",), owner="test")
    def no_test_names(change, facts):
        seen.append([s.get("name") for s in change.created("medication")])
        rows = facts.select("SELECT ?n FROM $abox WHERE { ?m a triad:Medication ; triad:name ?n }")
        if any(s.get("name") == "Forbidden" for s in change.created("medication")):
            raise guards.unique_conflict("Medication", ("Name",))
        assert rows

    session, uow, recorder = unit(store)
    with uow.write():
        session.write_buffer().replace(iri("patient", 1), "phoneNumber", "1")    # not its kind: it does not run
    assert seen == []
    with pytest.raises(Conflict) as error:
        with uow.write():
            session.write_buffer().create("medication", {**MEDICATION, "name": "Forbidden"})
    assert error.value.fields == {"key": "Medication.Name"} and seen == [["Forbidden"]]
    assert store.probe.count("medication", name="Forbidden") == 0
