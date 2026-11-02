# AI review log

This log records the work that an AI tool (Claude Code) did in Milestone 4.
For each phase, it records what we checked and what we changed.
The team uses this log to write the Level D critique of the AI output.

| Phase | AI task | What we checked | Result |
|---|---|---|---|
| 0 | Set up the branches and the ignore rules. | We ran `git check-ignore` on the course files, a database file and a downloaded zip. We checked that the preprocessed data is not ignored. | The rules work. No change. |
| 1 | Draft `USER_FLOWS.md`: the one-hospital world, the permissions and the hospital-visit journey. | The team read the draft. The team decided the re-homing (approved as drafted) and the staff method (seeded staff). Nine review agents checked the plan for this phase and found gaps: no update or delete steps, a nurse who could not reach the 403 case, and a matrix that did not agree with the journey. | We added the UPDATE, DELETE and 409 steps, a "Find a patient" path for the 403 case, and a matrix that agrees with the journey. |
| 2 | Write the fetch script, the hospital profile and the scenario builder. Pick Patient B. | We ran the fetch script two times and compared the SHA-256 of the output. We checked the uncompressed SHA-256 against the manifest. We ran the scenario builder two times and compared the output. We checked all 147 bundle entries with the `fhir.resources` R4B models. The builder checks Patient B and the care team rule (Jun Park is not on a care team of Patient B). | All checks pass. A review agent found that the "latest" Synthea URL changes almost every day, so we use a URL with a fixed commit. The journey said "Her father", but Patient B is male, so we changed the text to "The patient's father". |
