<h1>
  <img src="assets/triad-icon.png" alt="" height="30" align="absmiddle">
  TRIAD
</h1>

**Trusted RDF Interoperable Agent Data**

CSC 501; Algorithms and Data Models (Fall 2026), Prof. Hossein Fani
University of Victoria

A data model for clinical records created and revised by multiple people over
time: typed entities for patients, encounters and clinical assertions, with
explicit relationships for authorship and revision, so the current state is
reached by traversal rather than by search. Clinical entities are modelled
against the HL7 FHIR standard.

## Data model (Milestone 4)

TRIAD records each clinical fact as an **Assertion**. A staff member issues a
**Message**, and the message contains one or more assertions. Each assertion
is about one **ClinicalEntry**, and each entry belongs to one **Visit** of a
**Patient**. A unary **Supersedes** relationship records what replaced what.
The current fact is the assertion that nothing supersedes.

The diagram is a tree: there is exactly one path between any two entity sets.
Grey marks the TRIAD contribution (authorship, revision and the agent layer).

![TRIAD ER diagram](src/backend/models/er/TRIAD_ERD.png)

- Notes on the model (notation, design rules, changes from Milestone 2, FHIR R4
  alignment): [`src/backend/models/er/README.md`](src/backend/models/er/README.md)
- The diagram as PDF: [`src/backend/models/er/TRIAD_ERD.pdf`](src/backend/models/er/TRIAD_ERD.pdf)
- The user flows of the prototype: [`USER_FLOWS.md`](USER_FLOWS.md)
- The Milestone 2 draft stays in [`assets/designing_erd/`](assets/designing_erd/).

## Team

- Asish George
- Mohamed Khaled

## Repository layout

```
proposal/                     Milestone 1: project definition (LaTeX source + compiled PDF)
background_and_related_work/  Milestone 2: background, related work and draft ERD (LaTeX source + compiled PDF)
USER_FLOWS.md                 Milestone 4: the user flows of the prototype
src/backend/models/er/        Milestone 4: the ER diagram and its notes
src/backend/data/             Milestone 4: the source data (Synthea FHIR R4 sample and the TRIAD scenario data)
src/scripts/                  Milestone 4: scripts that get and build the data
doc/                          Milestone 4: project notes (for example, the AI review log)
assets/figures/               Figures used in the reports
assets/designing_erd/         Milestone 2: ERD draw.io sources and data-model documentation
assets/                       Logo and icon
```

## Milestones

| # | Deliverable | Due | Report |
|---|-------------|-----|--------|
| 1 | Project definition and team formation | Sep 23 | [PDF](proposal/TRIAD_Proposal.pdf) |
| 2 | Background and related work | Oct 7 | [PDF](background_and_related_work/02_Background.pdf) |
| 3 | 3MT proposal presentation | Oct 15 | |
| 4 | Solution design and implementation (relational) | Nov 4 | In progress |
| 5 | Evaluation | Nov 18 | |
| 6 | 10MT demo | Nov 26 | |
