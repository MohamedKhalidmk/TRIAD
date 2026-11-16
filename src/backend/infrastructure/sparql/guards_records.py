"""The assertion guards (agent B): the rules of the Assertion and CareTeamMember triggers of SQLite.

STUB: agent B writes the bodies. Each guard is registered already (guards.register), so the unit of work runs it
at each commit that touches its kinds. A stub body does nothing. Each docstring gives the SQLite rule and the
exact error. Read stored facts with one SELECT (facts.select) and the change with change.created(...),
change.links_to(...). See guards.py and README.md.

Do not edit guards.py: add a guard here with @register(..., owner="B").
"""
from __future__ import annotations

from infrastructure.sparql.change import Change
from infrastructure.sparql.guards import Facts, register


@register("assertion.supersedes-not-itself", kinds=("assertion",), owner="B")
def supersedes_not_itself(change: Change, facts: Facts) -> None:
    """SQLite: CHECK (SupersedesId IS NULL OR SupersedesId <> Id).

    Error: check_failed("CHECK constraint failed: SupersedesId IS NULL OR SupersedesId <> Id").
    """


@register("assertion.supersede-check", kinds=("assertion",), owner="B")
def supersede_check(change: Change, facts: Facts) -> None:
    """SQLite: TR_Assertion_Supersede_Check. For a new assertion with triad:supersedes:

    - the superseded assertion is not newer (compare the instants of assertedAt, not the text):
      trigger_failed("The superseded assertion is newer than the new assertion.");
    - it is about the same patient: trigger_failed("The superseded assertion is about another patient.");
    - new in Milestone 5 (plan 1.7): the supersedes chain has no cycle.
    The superseded assertion can be stored, or new in the same change.
    """


@register("assertion.one-head-per-entry", kinds=("assertion",), owner="B")
def one_head_per_entry(change: Change, facts: Facts) -> None:
    """SQLite: TR_Assertion_One_Head_Per_Entry. A new assertion about an entry that has a current assertion
    must supersede that assertion.

    Error: trigger_failed("The entry has a current assertion. The new assertion must supersede it.").
    The use case checks this first (409); this guard is the second line, under the write lock.
    """


@register("assertion.one-patient-per-message", kinds=("assertion", "message"), owner="B")
def one_patient_per_message(change: Change, facts: Facts) -> None:
    """SQLite: TR_Assertion_One_Patient_Per_Message. All assertions of a message are about one patient.

    Error: trigger_failed("All assertions of a message must be about one patient.").
    """


@register("care-team-member.is-staff", kinds=("care-team-member",), owner="B")
def care_team_member_is_staff(change: Change, facts: Facts) -> None:
    """SQLite: TR_CareTeamMember_Staff_Check. (memberSystem, memberValue) is the identifier of a staff member.

    Error: trigger_failed("The care-team member is not a staff member.").
    """
