"""The FHIR onboarding of the full data set (Synthea sample + curated scenarios)."""
from __future__ import annotations

import json

import pytest

from infrastructure import config
from infrastructure.fhir.reader import read_ndjson_gz
from infrastructure.sqlite.onboarding_store import TABLES

pytestmark = pytest.mark.slow

PATIENT_B = ("Marlin805 Reggie481 Nienow652", "1966-02-18")


def scalar(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def test_every_table_has_rows_and_the_counts_match_the_data(db):
    counts = {t: scalar(db, f"SELECT COUNT(*) FROM {t}") for t in TABLES}
    assert all(counts.values()), {t: c for t, c in counts.items() if c == 0}
    assert counts["Patient"] == 113          # 112 Synthea patients + Patient A
    assert counts["Visit"] == 5090           # 5,087 Synthea encounters + 3 curated visits
    assert counts["Department"] == 8 and counts["Location"] == 19
    assert counts["Staff"] == 267 + 25       # Synthea doctors + TRIAD General staff


def test_integrity_and_the_value_checks(db):
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert scalar(db, """SELECT COUNT(*) FROM CareTeamMember m WHERE NOT EXISTS (
        SELECT 1 FROM Staff s WHERE s.IdentifierSystem = m.MemberSystem AND s.IdentifierValue = m.MemberValue)""") == 0
    assert scalar(db, "SELECT COUNT(*) FROM Message m WHERE NOT EXISTS "
                      "(SELECT 1 FROM Assertion a WHERE a.MessageId = m.Id)") == 0
    assert scalar(db, "SELECT COUNT(*) FROM ClinicalEntry e WHERE NOT EXISTS "
                      "(SELECT 1 FROM Assertion a WHERE a.ClinicalEntryId = e.Id)") == 0
    assert scalar(db, """SELECT COUNT(*) FROM (SELECT a.ClinicalEntryId FROM Assertion a
        WHERE NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)
        GROUP BY a.ClinicalEntryId HAVING COUNT(*) > 1)""") == 0


def test_the_slide_chain_of_patient_a(db):
    rows = db.execute("""
        SELECT s.Role, m.Origin, a.Verification, a.SupersedesId IS NOT NULL AS Supersedes
        FROM Assertion a JOIN Message m ON m.Id = a.MessageId JOIN Staff s ON s.Id = m.StaffId
        JOIN ClinicalEntry e ON e.Id = a.ClinicalEntryId
        WHERE e.IdentifierValue = 'AllergyIntolerance/ai-elena-penicillin' ORDER BY a.AssertedAt""").fetchall()
    assert [tuple(r) for r in rows] == [("MOA", "Patient", "Unconfirmed", 0),
                                        ("MOA", "OtherClinic", "Unconfirmed", 1),
                                        ("Doctor", "Staff", "Refuted", 1)]


def test_patient_b_takes_metformin(db):
    count = scalar(db, """
        SELECT COUNT(*) FROM Patient p JOIN Visit v ON v.PatientId = p.Id
        JOIN ClinicalEntry e ON e.VisitId = v.Id JOIN Prescription pr ON pr.ClinicalEntryId = e.Id
        JOIN Assertion a ON a.ClinicalEntryId = e.Id
        WHERE p.Name = ? AND p.DateOfBirth = ? AND pr.Status = 'active' AND lower(e.Display) LIKE '%metformin%'
          AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id)""", *PATIENT_B)
    assert count >= 1


def test_synthea_visits_are_re_homed_into_triad_general(db):
    assert scalar(db, "SELECT COUNT(*) FROM VisitLocation") == scalar(db, "SELECT COUNT(*) FROM Visit")
    emergency = db.execute("""
        SELECT DISTINCT l.IdentifierValue FROM Visit v JOIN VisitLocation vl ON vl.VisitId = v.Id
        JOIN Location l ON l.Id = vl.LocationId
        WHERE v.Class = 'EMER' AND v.IdentifierSystem = ?""", (config.SYNTHEA_SYSTEM,)).fetchall()
    assert [r[0] for r in emergency] == ["ER-UNIT"]


def test_each_patient_has_an_active_care_team(db):
    without = scalar(db, """
        SELECT COUNT(*) FROM Patient p WHERE NOT EXISTS (
            SELECT 1 FROM Visit v JOIN ClinicalEntry e ON e.VisitId = v.Id
            JOIN CareTeam ct ON ct.ClinicalEntryId = e.Id AND ct.Status = 'active'
            JOIN Assertion a ON a.ClinicalEntryId = e.Id
            WHERE v.PatientId = p.Id AND NOT EXISTS (SELECT 1 FROM Assertion n WHERE n.SupersedesId = a.Id))""")
    assert without == 0


def test_jun_park_is_not_on_a_care_team_of_patient_b(db):
    count = scalar(db, """
        SELECT COUNT(*) FROM Patient p JOIN Visit v ON v.PatientId = p.Id
        JOIN ClinicalEntry e ON e.VisitId = v.Id JOIN CareTeam ct ON ct.ClinicalEntryId = e.Id
        JOIN CareTeamMember m ON m.CareTeamId = ct.Id
        WHERE p.Name = ? AND p.DateOfBirth = ? AND m.MemberValue = 'E1004'""", *PATIENT_B)
    assert count == 0


def test_mapping_check_against_the_source_file(db):
    """Compare mapped fields with the source FHIR data, for the first 40 resources of each type."""
    seen = {"Patient": 0, "Encounter": 0, "Condition": 0, "Observation": 0, "MedicationRequest": 0}
    for res in read_ndjson_gz(config.SYNTHEA_PATH):
        rtype = res["resourceType"]
        if rtype not in seen or seen[rtype] >= 40:
            continue
        seen[rtype] += 1
        if rtype == "Patient":
            row = db.execute("SELECT p.DateOfBirth, p.Sex FROM Patient p JOIN PatientIdentifier i ON i.PatientId = p.Id "
                             "WHERE i.System = ? AND i.Value = ?", (config.SYNTHEA_SYSTEM, res["id"])).fetchone()
            assert tuple(row) == (res["birthDate"], res["gender"])
        elif rtype == "Encounter":
            row = db.execute("SELECT Class, StartDate FROM Visit WHERE IdentifierValue = ?", (res["id"],)).fetchone()
            assert tuple(row) == (res["class"]["code"], res["period"]["start"])
        else:
            row = db.execute("SELECT Code, RecordedAt FROM ClinicalEntry WHERE IdentifierSystem = ? AND IdentifierValue = ?",
                             (config.SYNTHEA_SYSTEM, f"{rtype}/{res['id']}")).fetchone()
            assert row is not None, res["id"]
            if rtype == "MedicationRequest":
                assert row["RecordedAt"] == res["authoredOn"]
            else:
                assert row["Code"] == res["code"]["coding"][0]["code"]
    assert all(v == 40 for v in seen.values())


def test_the_committed_report_and_seed_file_are_current(full_db, tmp_path):
    import main
    from infrastructure.sqlite.connection import connect
    from infrastructure.sqlite.sql_export import export_scenarios
    out = tmp_path / "02.sql"
    export_scenarios(connect(full_db), out)
    assert out.read_text(encoding="utf-8") == (config.SQL_DIR / "02_insert_seed.sql").read_text(encoding="utf-8"), \
        "Run: python src/backend/main.py export-sql"
    committed = json.loads(config.ONBOARD_REPORT_PATH.read_text(encoding="utf-8"))
    assert committed["rows"] == {t: scalar(connect(full_db), f"SELECT COUNT(*) FROM {t}") for t in TABLES}, \
        "Run: python src/backend/main.py ensure-db --reset-db"
