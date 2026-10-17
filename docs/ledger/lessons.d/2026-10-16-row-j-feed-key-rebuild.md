## 2026-10-16 — DROPPING A PARENT TABLE UNDER FOREIGN KEYS DELETES ITS CHILDREN; A MIGRATION IS NOT RUN ALONE; A SUBPROCESS TEST READS THE OTHER TREE

(1) **`DROP TABLE sources` with `PRAGMA foreign_keys=ON` deletes the rows of every table that references it `ON DELETE CASCADE`** (SQLite performs an implicit `DELETE FROM` first), which is every article of the corpus. The pragma is a silent no-op inside a transaction, so the rebuild runs in autocommit, turns it OFF, READS IT BACK and refuses if it did not take, and compares the id set before the drop: a child can only dangle if a parent id moved. **Rule: a test for a rebuild gives the parent children and counts them after; the demonstration that a naive drop cascades is a test too, so the care cannot become decoration.**

(2) **A revision that needs no open transaction cannot assume none is open.** A restore of an old backup runs several revisions on one connection; an earlier one's DML leaves the driver's implicit transaction open. The first cut refused there and would have broken every restore of an old backup; neither its own tests nor review saw it, the full run did. The revision now commits first; the boot path still refuses to commit for a caller.

(3) **A test that spawns a subprocess imports the MAIN tree's `src` through the editable install**, even when pytest runs inside a git worktree, so a fix made in the worktree looked unfixed. Verify such a test from the main tree.

(4) **A module `models.py` imports is loaded by every index pass** and must be triaged in `analytics/engine_identity.NOT_OUTPUT_AFFECTING`.
