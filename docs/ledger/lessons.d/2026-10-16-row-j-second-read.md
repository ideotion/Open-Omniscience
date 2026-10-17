## 2026-10-16 — A COPIED VERDICT NEEDS ITS HISTORY HANDLED TOO; A RULING'S CONDITION CAN NAME A FACT THE STORE NEVER RECORDED; A TEST OF "ONE NEW ROW" IS BLIND TO THE SECOND

The second independent read of row J (the R148 restore sibling and the J3 import path) found these, each now fixed with a test that fails without the fix:

(1) **Overriding a row's status while still copying its judging history leaves a state the integrity check calls broken, in both directions** (disqualified outlet, incoming qualified feed: the repair script would re-admit it; qualified outlet, incoming disqualified: collectable at once and counted as laundered). The new test's fixture wrote no attempt rows, so it never met the history. **Rule: a fixture for "this row takes another row's verdict" must give the row a history of its own.** R149 teaches the check that a newer `inherited` attempt is the authority for the status, and lists those rows apart.

(2) **A ruling's condition ("its verdict equals the live status") named a field the store never recorded**: an `inherited` attempt holds the word `inherited`, not the verdict it handed on. It was implemented as the verdict class and the limit was written into the ruling's row, the docstring and the open queue, instead of being met by a schema change nobody had ruled on. **Rule: before building a ruling's condition, check each noun in it is a column.**

(3) **A bookkeeping placeholder (`-1` for "a row I just created") is a lookup that returns nothing.** A CSV import of a multi-feed outlet new to the store kept the first feed and errored on the rest; the importers now track the real id, and the "the domain's only row" fallback applies only when the import carries ONE record for the domain (the restore merge's one-to-one rule), so several feeds into a store holding one are siblings.

(4) **A tag skipped because the row already carried it was never recorded as merged, so an operator's removal of it was undone at the next boot** (223 of 240 real merges share a tag with their target row). Record what the catalogue OFFERED, not only what it added.

(5) **Two paths that hand a new sibling "the outlet's verdict" must pick the same row.** The seeder skipped past a curated stamp to nothing; the restore skipped past it to a measured verdict. Both now read: the stricter measured verdict, otherwise the oldest measured one.

(6) **An old ratchet that counted a quantity whose meaning had changed gave false failures and false messages** (the multiplicity per domain after the key moved). It was retired and the losses are pinned where they are measured.

(7) **The blocking lint lane (ruff F,B) was not run on the J heads until the second read; three findings introduced by the branch would have failed CI** (an import the lookup made unused, one the seeder stopped using, `zip()` without `strict=`).
