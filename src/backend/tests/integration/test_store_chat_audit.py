"""The audit log and the chat on each store (the AuditRepository and ChatRepository ports, the citation and audit
guards; plan 5.3 to 5.6).

Each test runs on SQLite and on the knowledge graph (Oxigraph; Virtuoso with TRIAD_TEST_STORES). The reads are
compared with `store.reference()`, the writes with the `twin` (tests/integration/kg_compare.py).

The chat needs the record repository of agent B, which is a stub in this worktree:
- the port tests use the sessions, the turns and the citations of the scenario data (the cited assertions exist);
- the "ask" turn through the API uses the fixture `record_reads`: each stub READ of the records reads the SQLite
  copy of the store (an "ask" writes no record). After the merge, the fixture changes nothing;
- the tests marked "needs the record repository" (a "tell" turn and the full chat) need the record writes.
  Remove the skip marker after the merge.
"""
from __future__ import annotations

import time

import pytest

from application.paging import PageRequest
from application.ports import NewEntryRow
from domain.access import Actor
from domain.errors import Conflict, Forbidden, Invalid
from tests.conftest import all_items, as_user, make_client
from tests.fixtures.stores import DEMO_NOW, SqliteProbe
from tests.integration.kg_compare import (BRENNAN, ELENA, EMPLOYEE, MOA, OKAFOR, PARK, SUBJECT, Recorder, both,
                                          directory_reads, instants, record_reads, response, twin)  # noqa: F401

AUDIT_PATH = "/api/patients/{patient}/audit"
LOCAL = "https://triad.example/fhir/CodeSystem/local"
DOCTOR = Actor(role="Doctor", key="Doctor:E1005", name="Amara Okafor", system=EMPLOYEE, value="E1005", staff_id=5)
OTHER_DOCTOR = Actor(role="Doctor", key="Doctor:E1006", name="Lucas Brennan", system=EMPLOYEE, value="E1006",
                     staff_id=6)
STRANGER = Actor(role="Nurse", key="Nurse:E9999", name="Nobody", system=EMPLOYEE, value="E9999")
OTHER_SUBJECT = ("Other Person", "1990-01-01")
CHAT = "https://triad.example/fhir/sid/chat-session"


@pytest.fixture
def reference(store):
    return make_client(store.db_path)


def contexts(store, twin):
    return (("store", store.open_ctx()), ("twin", twin.ctx()))


def each_context(store) -> list:
    """The store and its SQLite reference for a write that commits (for the sqlite store they are one database)."""
    return [store.open_ctx()] + ([store.reference()] if store.is_kg else [])


# ----- the audit log -----

@pytest.mark.parametrize("user", [OKAFOR, ELENA, PARK, MOA, BRENNAN])
def test_the_audit_log_of_a_patient(store, twin, user):
    """The read is the first record of the page (a write), so each read goes to the store and to the twin."""
    url = "/api/patients/1/audit"
    status, page = both(store, twin, "get", url, user)
    assert status == (403 if user in (PARK, MOA) else 200)
    for offset in (0, 1, 3, 5, 9):
        assert both(store, twin, "get", url, user, params={"limit": 2, "offset": offset})[0] == status
    status, page = both(store, twin, "get", url, user, params={"limit": 100})
    if status == 200:
        assert page["items"][0]["action"] == "read" and page["items"][0]["actorKey"] == user
        assert page["denied"] == 1 and page["total"] == 4 + 7
        names = {item["actorKey"]: item["actorName"] for item in page["items"]}
        assert names["Patient:MRN-000001"] == "Elena Marsh" and names["Nurse:E1004"] == "Jun Park"
    reference = SqliteProbe(twin.path)
    assert instants(store.probe.rows("audit-event")) == instants(reference.rows("audit-event"))


def test_the_audit_port_reads(store):
    ctx, ref = store.open_ctx(), store.reference()
    for subject in (SUBJECT, ("Elena Marsh", "1971-05-15"), OTHER_SUBJECT):
        for offset in (0, 1, 3, 4, 6):
            page = PageRequest(limit=2, offset=offset)
            assert ctx.audit.for_subject(subject, page) == ref.audit.for_subject(subject, page), (subject, offset)
        assert ctx.audit.denied_count(subject) == ref.audit.denied_count(subject)
    assert ctx.audit.denied_count(SUBJECT) == 1
    assert [e.chat_turn_id for e in ctx.audit.for_subject(SUBJECT, PageRequest()).items] == [None, None, 2, None]


def test_a_denial_writes_one_audit_record_on_each_store(store, twin):
    """Plan 5.3: a 403 writes exactly one Denied record, in its own write (application/guard.deny)."""
    before = store.probe.count("audit-event"), SqliteProbe(twin.path).count("audit-event")
    status, error = both(store, twin, "get", "/api/patients/1/visits", PARK)
    assert status == 403 and error["code"] == "forbidden"
    after = store.probe.count("audit-event"), SqliteProbe(twin.path).count("audit-event")
    assert after == (before[0] + 1, before[1] + 1)
    last, expected = store.probe.last("audit-event"), SqliteProbe(twin.path).last("audit-event")
    assert instants(last) == instants(expected)
    assert (last["auditOutcome"], last["actorValue"], last["path"], last["identifierValue"]) == (
        "Denied", "E1004", "/api/patients/{patient}/visits", "AUDIT-0005")


@pytest.mark.stores("oxigraph", "virtuoso")
def test_the_denial_is_one_insert_data(store):
    from application.guard import deny
    from infrastructure.clock import DemoClock
    from infrastructure.sparql.audit_repository import SparqlAuditRepository
    from infrastructure.sparql.unit_of_work import KgSession, SparqlUnitOfWork
    ctx = store.open_ctx()
    recorder = Recorder(ctx.audit.session.client)
    session = KgSession(recorder)
    ctx.uow, ctx.audit = SparqlUnitOfWork(session, DemoClock(DEMO_NOW)), SparqlAuditRepository(session)
    nurse = store.open_ctx().users.actor("Nurse", "E1004")
    with pytest.raises(Forbidden):
        deny(ctx, nurse, ctx.patients.get(1), "read", "/api/patients/{patient}/visits", "No.")
    assert len(recorder.updates) == 1 and recorder.updates[0].startswith("INSERT DATA")
    assert store.probe.last("audit-event")["auditOutcome"] == "Denied"


# Times whose text order is not their instant order (UTC in the comment), and one tie of instants.
MIXED = ["2026-10-31T10:00:00-04:00",        # 14:00Z
         "2026-10-31T09:30:00-07:00",        # 16:30Z (the newest)
         "2026-10-31T20:15:00+05:30",        # 14:45Z
         "2026-10-31T16:00:00Z",             # 16:00Z
         "2026-10-31T12:00:00-04:00"]        # 16:00Z: the same instant, a larger id


def test_audit_records_with_mixed_offsets(store, twin):
    found = {}
    for name, ctx in contexts(store, twin):
        with ctx.uow.write():
            for n, at in enumerate(MIXED):
                actor = (DOCTOR, OTHER_DOCTOR, STRANGER)[n % 3]
                ctx.audit.add(at, "read", "Denied" if n % 2 else "Allowed", actor, SUBJECT, f"/test/{n}")
        found[name] = ([ctx.audit.for_subject(SUBJECT, PageRequest(limit=3, offset=o)) for o in (0, 3, 6, 9)],
                       ctx.audit.denied_count(SUBJECT))
    assert instants(found["store"]) == instants(found["twin"])
    first = found["store"][0][0].items
    assert [e.path for e in first] == ["/test/1", "/test/4", "/test/3"]
    assert [e.identifier for e in first] == ["AUDIT-0006", "AUDIT-0009", "AUDIT-0008"]   # one write, five values
    assert first[0].actor_name == "Lucas Brennan" and found["store"][0][1].items[0].actor_name is None   # E9999
    assert found["store"][1] == 1 + 2


def test_a_stored_audit_record_cannot_change(store):
    from infrastructure.sparql.terms import iri
    ctx, ref = store.open_ctx(), store.reference()

    def change(c):
        if store.is_kg:
            c.audit.session.write_buffer().replace(iri("audit-event", 1), "path", "/changed")
        else:
            c.audit.conn.execute("UPDATE AuditEvent SET Path = '/changed' WHERE Id = 1")
    errors = []
    for c, write in ((ctx, change), (ref, lambda c: c.audit.conn.execute("DELETE FROM AuditEvent WHERE Id = 1"))):
        with pytest.raises(Invalid) as error:
            with c.uow.write():
                write(c)
        errors.append(error.value.message)
    assert errors == ["AuditEvent is append-only."] * 2


# ----- the chat: reads -----

def test_the_chat_port_reads(store):
    ctx, ref = store.open_ctx(), store.reference()
    for session_id in (1, 99999, -1, 0):
        assert ctx.chat.session(session_id) == ref.chat.session(session_id), session_id
        assert ctx.chat.turns(session_id) == ref.chat.turns(session_id), session_id
    for client_turn_id in ("demo-0001-1", "demo-0001-2", "demo-0001-3", "DEMO-0001-1", '" } ; DROP ALL ; #'):
        assert ctx.chat.turn_by_client_id(1, client_turn_id) == ref.chat.turn_by_client_id(1, client_turn_id)
    turns = ctx.chat.turns(1)
    assert [(t.seq, t.speaker, t.kind, t.citations) for t in turns] == [(1, "User", None, []),
                                                                       (2, "Assistant", "ask", [(3, 1)])]
    assert ctx.chat.session(1).patient_id == 1
    for actor in (DOCTOR, OTHER_DOCTOR, STRANGER):
        for subject in (SUBJECT, OTHER_SUBJECT):
            for offset in (0, 1, 2):
                page = PageRequest(limit=1, offset=offset)
                assert ctx.chat.sessions(actor, subject, page) == ref.chat.sessions(actor, subject, page)
    first = ctx.chat.sessions(DOCTOR, SUBJECT, PageRequest()).items[0]
    assert (first.turn_count, first.first_question) == (2, "Is she allergic to penicillin?")


# ----- the chat: writes -----

def test_start_and_list_sessions_on_each_store(store, twin):
    sessions = "/api/patients/1/chat/sessions"
    status, mine = both(store, twin, "post", sessions, OKAFOR)
    assert status == 201 and mine["identifier"] == "CHAT-0002" and mine["turns"] == [] and mine["patientId"] == 1
    assert both(store, twin, "post", sessions, ELENA)[0] == 201
    assert both(store, twin, "post", sessions, OKAFOR)[1]["identifier"] == "CHAT-0004"
    for user in (MOA, PARK):
        assert both(store, twin, "post", sessions, user)[0] == 403
    for user in (OKAFOR, ELENA, BRENNAN):
        listed = all_items(store.client(), sessions, user)
        assert listed == all_items(twin.client(), sessions, user), user
        for offset in (0, 1, 2, 3):
            assert both(store, twin, "get", sessions, user, params={"limit": 1, "offset": offset})[0] == 200
    assert [s["identifier"] for s in all_items(store.client(), sessions, OKAFOR)] == ["CHAT-0004", "CHAT-0002",
                                                                                     "CHAT-0001"]
    one = f"/api/chat/sessions/{mine['id']}"
    assert both(store, twin, "get", one, OKAFOR)[0] == 200
    assert both(store, twin, "get", one, BRENNAN)[0] == 403           # another user: a denial record
    for missing in ("/api/chat/sessions/99999", "/api/chat/sessions/-1"):
        assert both(store, twin, "get", missing, OKAFOR)[0] == 404
    reference = SqliteProbe(twin.path)
    for kind in ("chat-session", "audit-event"):
        assert instants(store.probe.rows(kind)) == instants(reference.rows(kind)), kind


def chat_turn(ctx, session_id: int, client_turn_id: str, cited: list[int], kind: str = "ask",
              subject=SUBJECT) -> tuple[int, int]:
    """A user turn (one write), then the reply turn with its citations and its audit record (one write)."""
    with ctx.uow.write() as now:
        user = ctx.chat.add_turn(session_id, client_turn_id, "User", f"Question {client_turn_id}?", now)
    with ctx.uow.write() as now:
        reply = ctx.chat.add_turn(session_id, client_turn_id + ":reply", "Assistant", "An answer.", now)
        if cited:
            ctx.chat.add_citations(reply, cited)
        ctx.audit.add(now, kind, "Allowed", DOCTOR, subject, "/api/chat/sessions/{session}/turns",
                      chat_turn_id=reply)
    return user, reply


def test_turns_and_citations_on_each_store(store, twin):
    found = {}
    for name, ctx in contexts(store, twin):
        chat_turn(ctx, 1, "t-1", [3, 5, 3, 1])
        with ctx.uow.write() as now:
            session = ctx.chat.create_session((CHAT, ctx.chat.next_identifier(CHAT, "CHAT-", 4)), DOCTOR, SUBJECT,
                                              now, "fake", None)
            first = ctx.chat.add_turn(session, "u-1", "Assistant", "A greeting.", now)    # two turns in one write
            ctx.chat.add_turn(session, "u-2", "User", "Is it here?", now)
            ctx.chat.add_citations(first, [7])
        _, reply = chat_turn(ctx, session, "t-2", [], kind="tell")
        with ctx.uow.write() as now:                 # a second record of the turn: the kind is the first one
            ctx.audit.add(now, "ask", "Allowed", DOCTOR, SUBJECT, "/test", chat_turn_id=reply)
        found[name] = ([ctx.chat.turns(1), ctx.chat.turns(session), ctx.chat.turn_by_client_id(1, "t-1:reply"),
                        ctx.chat.turn_by_client_id(session, "t-2")],
                       [ctx.chat.sessions(DOCTOR, SUBJECT, PageRequest(limit=1, offset=o)) for o in (0, 1, 2)],
                       ctx.chat.session(session))
    assert instants(found["store"]) == instants(found["twin"])
    (old, new, reply_one, user_two), summaries, session_row = found["store"]
    assert [t.seq for t in old] == [1, 2, 3, 4] and old[3].citations == [(3, 1), (5, 2), (1, 3)]
    assert old[3].kind == "ask" and reply_one == old[3] and old[2].kind is None
    assert [(t.seq, t.client_turn_id, t.kind) for t in new] == [(1, "u-1", None), (2, "u-2", None), (3, "t-2", None),
                                                                (4, "t-2:reply", "tell")]
    assert new[0].citations == [(7, 1)] and user_two == new[2]
    assert [s.items[0].first_question for s in summaries[:2]] == ["Is it here?", "Is she allergic to penicillin?"]
    assert summaries[0].items[0].turn_count == 4 and session_row.identifier == "CHAT-0002"
    reference = SqliteProbe(twin.path)
    for kind in ("chat-session", "chat-turn", "citation", "audit-event"):
        assert instants(store.probe.rows(kind)) == instants(reference.rows(kind)), kind


# ----- the guards (the unit of work directly: no use case can write these rows) -----

def write_error(ctx, change) -> Exception:
    with pytest.raises((Conflict, Invalid)) as error:
        with ctx.uow.write() as now:
            change(ctx, now)
    return error.value


def same_error(store, change) -> Exception:
    """The violating write gives the same error on the store and on SQLite (a failed write changes nothing)."""
    found, expected = write_error(store.open_ctx(), change), write_error(store.reference(), change)
    assert (type(found), found.message, found.fields) == (type(expected), expected.message, expected.fields)
    return found


def new_session(c, now, subject=SUBJECT) -> int:
    return c.chat.create_session((CHAT, f"CHAT-T-{subject[0][:5]}"), DOCTOR, subject, now, "fake", None)


def test_the_citation_check(store):
    def user_turn_cites(c, now):                          # a new user turn
        turn = c.chat.add_turn(1, "x-1", "User", "Hello.", now)
        c.chat.add_citations(turn, [3])

    def stored_user_turn_cites(c, now):                   # the stored user turn 1
        c.chat.add_citations(1, [3])

    def other_patient_new_session(c, now):               # a new session about another patient (a new turn)
        turn = c.chat.add_turn(new_session(c, now, OTHER_SUBJECT), "x-1", "Assistant", "Hello.", now)
        c.chat.add_citations(turn, [3, 4])

    def second_citation_fails(c, now):                    # the first citation is correct, the second is not
        turn = c.chat.add_turn(1, "x-1", "Assistant", "Hello.", now)
        c.chat.add_citations(turn, [3])
        c.chat.add_turn(1, "x-2", "User", "Hi.", now)
        c.chat.add_citations(turn + 1, [4])

    assert same_error(store, user_turn_cites).message == "Only an assistant turn can cite an assertion."
    assert same_error(store, stored_user_turn_cites).message == "Only an assistant turn can cite an assertion."
    assert same_error(store, other_patient_new_session).message == \
           "The cited assertion is not about the patient of the chat session."
    assert same_error(store, second_citation_fails).message == "Only an assistant turn can cite an assertion."
    # A stored session about another patient: the session is in one write, the citation in the next.
    for c in each_context(store):
        with c.uow.write() as now:
            session = new_session(c, now, OTHER_SUBJECT)
            turn = c.chat.add_turn(session, "y-1", "Assistant", "Hello.", now)
        with pytest.raises(Invalid, match="not about the patient"):
            with c.uow.write():
                c.chat.add_citations(turn, [2])
    ctx = store.open_ctx()
    with ctx.uow.write():                                 # a correct citation of a stored assistant turn
        ctx.chat.add_citations(2, [5])
    assert ctx.chat.turns(1)[1].citations == [(3, 1), (5, 1)]


def write_new_assertion(c, now, visit_id: int, number: int) -> int:
    """A new message, entry and assertion in the open write (the record rows of a "tell" turn): the SQLite record
    repository, or the write buffer of the KG (the record repository of agent B is a stub here)."""
    entry = NewEntryRow(visit_id=visit_id, category="Observation", code="family-history", code_system=LOCAL,
                        display=f"Family history {number}", text=None, recorded_at=now,
                        details={"Value": "Mother has diabetes.", "Unit": None})
    if c.store == "sqlite":
        message = c.records.add_message(("urn:test:message", f"MSG-T-{number}"), None, "Chat", "Patient", now, "x")
        entry_id = c.records.add_entry(("urn:test:entry", f"ENTRY-T-{number}"), entry)
        return c.records.add_assertion(message, 1, entry_id, None, now, "Report", "Agent", "Unconfirmed", "x")
    from infrastructure.sparql.terms import iri
    buf = c.patients.session.write_buffer()
    message = buf.create("message", {"identifierSystem": "urn:test:message", "identifierValue": f"MSG-T-{number}",
                                     "channel": "Chat", "origin": "Patient", "sentAt": now, "text": "x"})
    entry_id = buf.create("clinical-entry", {
        "identifierSystem": "urn:test:entry", "identifierValue": f"ENTRY-T-{number}", "during": iri("visit", visit_id),
        "code": entry.code, "codeSystem": entry.code_system, "display": entry.display, "recordedAt": now,
        "value": "Mother has diabetes."}, types=("Observation",))
    assertion = buf.create("assertion", {"about": iri("clinical-entry", entry_id), "seq": 1, "assertedAt": now,
                                         "intent": "Report", "source": "Agent", "verification": "Unconfirmed",
                                         "statement": "x"})
    buf.add(iri("message", message), {"contains": iri("assertion", assertion)})
    return assertion


@pytest.mark.parametrize("subject, error", [(SUBJECT, None),
                                            (OTHER_SUBJECT, "The cited assertion is not about the patient")])
def test_the_citation_check_of_new_assertions(store, subject, error):
    """A "tell" turn: the cited assertions, their entries (and a new report visit) are new in the same write."""
    for c in each_context(store):
        with c.uow.write() as now:
            session = new_session(c, now, subject)

        def tell(c=c, session=session):
            with c.uow.write() as now:
                visit = c.visits.create(1, ("urn:test:visit", "ENC-T-1"), "VR", "Patient report", None, now, None,
                                        end=now)
                cited = [write_new_assertion(c, now, visit, 1), write_new_assertion(c, now, 3, 2), 3]
                reply = c.chat.add_turn(session, "t-1:reply", "Assistant", "I recorded 2 new items.", now)
                c.chat.add_citations(reply, cited)
                c.audit.add(now, "tell", "Allowed", DOCTOR, subject, "/test", chat_turn_id=reply)
            return reply
        if error is None:
            reply = tell()
            assert len(c.chat.turn_by_client_id(session, "t-1:reply").citations) == 3 and reply
        else:
            with pytest.raises(Invalid, match=error):
                tell()


def test_the_audit_subject_check(store):
    def stored_turn(c, now):
        c.audit.add(now, "ask", "Allowed", DOCTOR, OTHER_SUBJECT, "/test", chat_turn_id=2)

    def new_turn(c, now):
        turn = c.chat.add_turn(1, "z-1", "Assistant", "Hello.", now)
        c.audit.add(now, "ask", "Allowed", DOCTOR, ("Elena Marsh", "1971-05-15"), "/test", chat_turn_id=turn)

    def new_session_and_turn(c, now):
        turn = c.chat.add_turn(new_session(c, now, OTHER_SUBJECT), "z-1", "Assistant", "Hello.", now)
        c.audit.add(now, "ask", "Allowed", DOCTOR, SUBJECT, "/test", chat_turn_id=turn)

    for change in (stored_turn, new_turn, new_session_and_turn):
        assert same_error(store, change).message == "The audit subject is not the patient of the chat session."
    ctx = store.open_ctx()
    with ctx.uow.write() as now:                          # the subject of the session: no error
        ctx.audit.add(now, "ask", "Allowed", DOCTOR, SUBJECT, "/test", chat_turn_id=2)
        ctx.audit.add(now, "read", "Allowed", DOCTOR, OTHER_SUBJECT, "/test")      # no turn: no check
    assert ctx.audit.denied_count(SUBJECT) == 1


@pytest.mark.skip(reason="needs the key guard key.chat-turn of agent D (guards_directory.py)")
def test_a_client_turn_id_is_unique_in_a_session(store):
    """UK_ChatTurn_ChatSessionId_ClientTurnId: the use case reads the turn first, so only the port can write it."""
    found = same_error(store, lambda c, now: c.chat.add_turn(1, "demo-0001-1", "User", "Again?", now))
    assert found.fields == {"key": "ChatTurn.ChatSessionId, ChatTurn.ClientTurnId"}


@pytest.mark.skip(reason="needs the key guard key.association of agent D (guards_directory.py)")
def test_a_turn_cites_an_assertion_one_time(store):
    """UK_Citation_ChatTurnId_AssertionId: a second citation of the same assertion by the same turn."""
    found = same_error(store, lambda c, now: c.chat.add_citations(2, [3]))
    assert found.fields == {"key": "Citation.ChatTurnId, Citation.AssertionId"}


# ----- the chat: a full turn through the API -----

def turn_count(store, twin) -> tuple:
    reference = SqliteProbe(twin.path)
    return tuple((store.probe.count(kind), reference.count(kind)) for kind in ("chat-turn", "citation", "audit-event"))


def test_an_ask_turn_on_each_store(store, twin, record_reads):
    """The rules mode (the fake model): the same reply, cards and records. The same clientTurnId gives the saved
    turns again (no new row)."""
    url = "/api/chat/sessions/1/turns"
    body = {"clientTurnId": "turn-1", "text": "Is she allergic to penicillin?"}
    status, first = both(store, twin, "post", url, OKAFOR, json=body)
    assert status == 200 and first["assistantTurn"]["kind"] == "ask" and first["assistantTurn"]["cards"]
    counts = turn_count(store, twin)
    assert both(store, twin, "post", url, OKAFOR, json=body) == (200, first)
    assert turn_count(store, twin) == counts
    assert both(store, twin, "post", url, ELENA, json={"clientTurnId": "turn-2", "text": "Any allergies?"})[0] == 403
    assert both(store, twin, "post", url, OKAFOR, json={"clientTurnId": " ", "text": "x"})[0] == 422
    assert both(store, twin, "get", "/api/chat/sessions/1", OKAFOR)[0] == 200
    assert both(store, twin, "get", "/api/patients/1/chat/sessions", OKAFOR)[1]["items"][0]["turnCount"] == 4
    reference = SqliteProbe(twin.path)
    for kind in ("chat-turn", "citation", "audit-event"):
        assert instants(store.probe.rows(kind)) == instants(reference.rows(kind)), kind


@pytest.mark.skip(reason="needs the record repository")
def test_a_tell_turn_on_each_store(store, twin):
    """A patient "tell" writes a report visit, a message, an entry and an assertion, and the reply cites it."""
    status, session = both(store, twin, "post", "/api/patients/1/chat/sessions", ELENA)
    url = f"/api/chat/sessions/{session['id']}/turns"
    body = {"clientTurnId": "t-1", "text": "My mother has diabetes."}
    status, turn = both(store, twin, "post", url, ELENA, json=body)
    assert status == 200 and turn["assistantTurn"]["kind"] == "tell" and turn["assistantTurn"]["recordedIds"]
    assert both(store, twin, "post", url, ELENA, json=body) == (200, turn)
    assert both(store, twin, "post", url, ELENA, json={"clientTurnId": "t-2", "text": "Thank you."})[0] == 200
    reference = SqliteProbe(twin.path)
    for kind in ("visit", "message", "assertion", "chat-turn", "citation", "audit-event"):
        assert instants(store.probe.rows(kind)) == instants(reference.rows(kind)), kind


@pytest.mark.skip(reason="needs the record repository")
def test_a_full_chat_on_each_store(store, twin):
    """A session, two "ask" turns, a "tell" turn of a doctor with no open visit, the session and the list."""
    status, session = both(store, twin, "post", "/api/patients/1/chat/sessions", OKAFOR)
    url = f"/api/chat/sessions/{session['id']}/turns"
    for n, text in enumerate(["Is she allergic to penicillin?", "What are her medications?",
                              "Her father died of a heart attack."]):
        assert both(store, twin, "post", url, OKAFOR, json={"clientTurnId": f"t-{n}", "text": text})[0] == 200
    assert both(store, twin, "get", f"/api/chat/sessions/{session['id']}", OKAFOR)[0] == 200
    assert both(store, twin, "get", "/api/patients/1/chat/sessions", OKAFOR)[0] == 200
    assert both(store, twin, "get", "/api/patients/1/audit", OKAFOR)[0] == 200


# ----- the full data: the time of the writes and of the reads -----

def timed(fn, *args):
    start = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - start


def test_the_audit_and_chat_writes_on_the_full_data(full_store):
    import sqlite3
    conn = sqlite3.connect(full_store.db_path)
    cited = [r[0] for r in conn.execute(
        "SELECT a.Id FROM Assertion a JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId "
        "JOIN Visit v ON v.Id = e.VisitId WHERE v.PatientId = 1 ORDER BY a.Id LIMIT 3")]
    conn.close()
    ctx = full_store.open_ctx()
    nurse = ctx.users.actor("Nurse", "E1004")
    patient = ctx.patients.get(1)
    before = ctx.audit.for_subject(SUBJECT, PageRequest()).total
    timings = {}
    from application.guard import deny

    def denial():
        with pytest.raises(Forbidden):
            deny(ctx, nurse, patient, "read", "/api/patients/{patient}/visits", "No.")
    _, first = timed(denial)                 # the first write of the process reads the latest time of the store
    _, timings["audit write (a denial)"] = timed(denial)

    def session():
        with ctx.uow.write() as now:
            return ctx.chat.create_session((CHAT, ctx.chat.next_identifier(CHAT, "CHAT-", 4)), DOCTOR, SUBJECT,
                                           now, "fake", None)
    session_id, timings["session write"] = timed(session)

    def user_turn():
        with ctx.uow.write() as now:
            return ctx.chat.add_turn(session_id, "t-1", "User", "Is she allergic to penicillin?", now)
    _, timings["user turn write"] = timed(user_turn)

    def reply_turn():
        with ctx.uow.write() as now:
            reply = ctx.chat.add_turn(session_id, "t-1:reply", "Assistant", "No.", now)
            ctx.chat.add_citations(reply, cited)
            ctx.audit.add(now, "ask", "Allowed", DOCTOR, SUBJECT, "/api/chat/sessions/{session}/turns",
                          chat_turn_id=reply)
    _, timings["reply turn write (3 citations, audit)"] = timed(reply_turn)
    turns, timings["turns read"] = timed(ctx.chat.turns, session_id)
    assert [t.speaker for t in turns] == ["User", "Assistant"] and turns[1].kind == "ask"
    _, timings["sessions read"] = timed(ctx.chat.sessions, DOCTOR, SUBJECT, PageRequest())
    page, timings["audit page read"] = timed(ctx.audit.for_subject, SUBJECT, PageRequest())
    assert page.items[0].chat_turn_id == turns[1].id
    assert page.total == before + 3 and turns[1].citations == [(a, n) for n, a in enumerate(cited, 1)]
    print(f"\n[audit and chat, full data, {full_store.name}] first write: {first * 1000:.1f} ms;",
          {k: f"{v * 1000:.1f} ms" for k, v in timings.items()})
    assert max(timings.values()) < full_store.time_limit(0.3), timings
