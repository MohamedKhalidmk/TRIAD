# AI review log

This log records the work that an AI tool (Claude Code) did in Milestone 4.
For each phase, it records what we checked and what we changed.
The team uses this log to write the Level D critique of the AI output.

| Phase | AI task | What we checked | Result |
|---|---|---|---|
| 0 | Set up the branches and the ignore rules. | We ran `git check-ignore` on the course files, a database file and a downloaded zip. We checked that the preprocessed data is not ignored. | The rules work. No change. |
| 1 | Draft `USER_FLOWS.md`: the one-hospital world, the permissions and the hospital-visit journey. | The team read the draft. The team decided the re-homing (approved as drafted) and the staff method (seeded staff). Nine review agents checked the plan for this phase and found gaps: no update or delete steps, a nurse who could not reach the 403 case, and a matrix that did not agree with the journey. | We added the UPDATE, DELETE and 409 steps, a "Find a patient" path for the 403 case, and a matrix that agrees with the journey. |
