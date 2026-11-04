# Milestone 4 design review (Mohamed Khaled)

My review of the relational schema on `m4-relational` (29 relations, 11 triggers).
The schema runs cleanly: all five SQL scripts execute on a fresh database with no
foreign-key violations, and every constraint case in `05_constraint_violations.sql`
fails as expected. The points below are design trade-offs to settle in Milestone 5.

## 1. Authorship is now per message, not per fact

After the Milestone 2 feedback, Assertion is a weak entity owned by Message, so an
assertion's author is the message issuer (`Message.StaffId`). This is cleaner, but it
narrows the claim TRIAD made in Milestone 1: that every fact records who asserted it.

Example: an MOA types up a phone call that carries the nurse's vitals and the doctor's
order. All three assertions are attributed to the MOA. `Source` and `Intent` record how
a claim was made, not who originally made it.

Options:
1. Keep it and state the limitation in the report.
2. Add an optional `AssertedBy` foreign key to Staff on Assertion, defaulting to the
   message issuer, so a relayed claim keeps its real author.

## 2. The patient key (Name, DateOfBirth) can collide

`Patient` uses (Name, DateOfBirth) as its candidate key, and a trigger forbids updating
it because the chat and audit logs store it as a value. Two real patients can share a
name and a birth date, and a name correction is then impossible without breaking the
logs.

Options:
1. Keep it for the course prototype and document it.
2. Key the logs on a stable identifier (for example the PatientIdentifier MRN) instead
   of the name, so the patient's name can be corrected.
