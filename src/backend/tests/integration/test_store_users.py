"""The users, the current user and health on each store (the example of the store fixture, plan 5.6).

Each test runs on SQLite and on the knowledge graph (Oxigraph; Virtuoso with TRIAD_TEST_STORES), with the scenario
data. A KG store must give the same response as SQLite on the same data: `reference` is a SQLite client on the
SQLite copy of the store.
"""
from __future__ import annotations

import pytest

from application.users import PINNED_KEYS
from tests.conftest import all_items, as_user, make_client

ELENA, SOFIA, PARK, OKAFOR = "Patient:MRN-000001", "MOA:E1001", "Nurse:E1004", "Doctor:E1005"
INJECTIONS = ('" } ; DROP ALL ; #', '"', "\\", "\\u0022 } ; CLEAR ALL ; #", "'; DROP", "$q", "a\nb")


@pytest.fixture
def reference(store):
    """A SQLite client on the same data as the store."""
    return make_client(store.db_path)


def test_health_names_the_store_and_the_ontology(store, reference):
    health = store.client().get("/api/health").json()
    expected = reference.get("/api/health").json()
    assert health["store"] == store.name
    assert health["ontologyVersion"] == ("5.0.0" if store.is_kg else None)
    assert {k: v for k, v in health.items() if k not in ("store", "ontologyVersion")} == \
           {k: v for k, v in expected.items() if k not in ("store", "ontologyVersion")}
    assert health["now"] == "2026-10-30T09:00:00-04:00"       # the fixed demo time is after the data


def test_the_users_are_the_same_on_each_store(store, reference):
    api = store.client()
    users = all_items(api, "/api/users")
    assert users == all_items(reference, "/api/users")
    assert [u["key"] for u in users[:8] if u["pinned"]] == [k for k in PINNED_KEYS if k != PINNED_KEYS[1]]
    assert users[0] == {"key": ELENA, "role": "Patient", "name": "Elena Marsh", "detail": "born 1971-05-14",
                        "pinned": True, "patientId": 1, "staffId": None}
    rest = [u for u in users if not u["pinned"]]
    assert [(u["name"].lower(), u["key"]) for u in rest] == sorted((u["name"].lower(), u["key"]) for u in rest)


@pytest.mark.parametrize("params", [{}, {"role": "Nurse"}, {"role": "Doctor"}, {"q": "a"}, {"q": "PARK"},
                                    {"role": "Patient", "q": "elena"}, {"q": "no such name"}])
def test_each_page_is_a_slice_of_the_full_list(store, reference, params):
    api = store.client()
    full = all_items(reference, "/api/users", **params)
    for offset in (0, 3, 7, len(full), len(full) + 5):
        page = api.get("/api/users", params={**params, "limit": 3, "offset": offset}).json()
        assert page["total"] == len(full)
        assert page["items"] == full[offset:offset + 3]


@pytest.mark.parametrize("key", [ELENA, SOFIA, PARK, OKAFOR, "Doctor:E1006", "Nurse:E1002"])
def test_one_user_and_the_current_user(store, reference, key):
    api = store.client()
    one = api.get(f"/api/users/{key}")
    assert one.status_code == 200 and one.json() == reference.get(f"/api/users/{key}").json()
    me = api.get("/api/me", headers=as_user(key))
    assert me.status_code == 200 and me.json() == one.json()


def test_the_user_header_and_the_unknown_users(store):
    api = store.client()
    assert api.get("/api/me").status_code == 401 and api.get("/api/me").json()["code"] == "no_user"
    for key in ("Doctor:E9999", "Nobody", "Patient:MRN-999999", "Nurse:E1005", "Doctor:"):
        assert api.get("/api/me", headers=as_user(key)).status_code == 401, key
    for key in ("Doctor:E9999", "Nobody", "Patient:no-such-id"):
        response = api.get(f"/api/users/{key}")
        assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert api.get("/api/users?role=Admin").status_code == 422


@pytest.mark.parametrize("text", INJECTIONS)
def test_a_search_text_cannot_change_the_query(store, text):
    """Plan 5.2: the escape function. The search works, and no graph changes."""
    api = store.client()
    users = store.probe.count("patient"), store.probe.count("staff")
    response = api.get("/api/users", params={"q": text})
    assert response.status_code == 200 and response.json()["total"] == 0
    assert api.get("/api/users", params={"q": text, "role": "Doctor"}).status_code == 200
    assert api.get(f"/api/me", headers=as_user(f"Doctor:{text}")).status_code == 401
    assert (store.probe.count("patient"), store.probe.count("staff")) == users
    assert api.get("/api/users", params={"q": "okafor"}).json()["total"] == 1


@pytest.mark.stores("oxigraph")
def test_triad_store_oxigraph_starts_the_app_from_the_environment(store, monkeypatch, tmp_path):
    """uvicorn main:create_app --factory (dev.sh) with TRIAD_STORE=oxigraph: the settings come from the environment."""
    import main
    from fastapi.testclient import TestClient
    from infrastructure import config
    monkeypatch.setattr(config, "load_env_file", lambda *args, **kwargs: [])
    for name, value in {"TRIAD_STORE": "oxigraph", "TRIAD_KG_OXIGRAPH_PATH": str(store.settings.kg_oxigraph_path),
                        "TRIAD_DB_PATH": str(tmp_path / "no-database.db"), "TRIAD_SPARQL_LOG": "off",
                        "TRIAD_NOW": "2026-10-30T09:00:00-04:00"}.items():
        monkeypatch.setenv(name, value)
    api = TestClient(main.create_app())                       # no SQLite database is needed in KG mode
    assert api.get("/api/health").json()["store"] == "oxigraph"
    assert api.get("/api/users").json()["total"] == 26
    assert api.get("/api/me", headers=as_user(OKAFOR)).json()["name"] == "Amara Okafor"


@pytest.mark.stores("oxigraph", "virtuoso")
def test_the_kg_store_holds_the_build_marker_and_the_counters(store):
    from infrastructure.rdf.kg_store import triple_store
    from infrastructure.sparql import ids
    import main
    client = main.kg_client(store.settings)
    marker = triple_store(store.settings, client).marker()
    assert marker is not None and marker.ontology_version == "5.0.0" and marker.scope == "all"
    counters = ids.read_counters(client)
    assert counters["assertion"] == store.probe.count("assertion") == 10
    assert counters["patient"] == 1 and counters["staff"] == 25
