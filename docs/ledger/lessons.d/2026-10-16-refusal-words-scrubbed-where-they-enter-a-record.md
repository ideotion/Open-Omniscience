## 2026-10-16 — a refusal's words are scrubbed where they enter a record or a log, and read where they are made (PR #1406)

**What was found.** The repair's refusals (`Declined`, and `salvage.SalvageRefused` re-raised as one) carry a sentence, and `run()` wrote that sentence unchanged into a log line and into `reason_text`, which rides the
boot-sequence status and from there the Diagnostics bundle's `columnar.json`. Every producer said a fixed sentence (a code, numbers, a class name through `type(exc).__name__` or `damage.failure_text`), so nothing leaked — and nothing
KEPT it that way: the next producer that wrote `f"... ({exc})"` for a keyed connection would have carried a `PRAGMA key = '…'` statement to the status and the bundle with no test red. The same two log calls were also the last
entry of `tests/data/exc_info_allowlist.json` (two `exc-arg` hits), and `repair.py` had been left out of the sink sweep (`tests/test_sink_sweep_records.py`) until its own PR landed.

**The rules.**
1. **Scrub where the text enters the record or the log, not where it is produced.** The producers are many and each says something different; the two handlers in `run()` are the one place the words become a record. Both now write
   `exception_text(refusal, typed=False)`, the repo's one call for a caught exception's text (a hand-made `scrubbed(refusal.detail)` is what `test_no_source_file_hands_a_caught_exceptions_text_to_scrubbed_by_hand` refuses, even for
   our own class: it has no walk of the chain for a `UnicodeError`). The scrub comes before any cut a reader makes, so a cut can never split a passphrase and leave half of it. The re-raise of a salvage refusal as a `Declined` is
   made of the scrubbed words too.
2. **Read what a producer is made of, as well as what a handler does with it.** `tests/test_refusal_detail_source.py` reads every `Declined(...)`/`SalvageRefused(...)` call in `repair.py` and `salvage.py`: a caught exception may be
   there only as `type(x).__name__`, as the argument of `failure_text`/`failure_label`, or — when the `except` clause names ONLY our own refusals (`LibraryBusy`, `Declined`, `SalvageRefused`) — as `str(x)`, `exception_text(x)`,
   `x.detail` or `x.code`; a name assigned from an exception is followed (`=`, `+=`, a tuple unpacking, a walrus). Every form has a negative control, and 12 weakenings of the reading are each killed by a named control.
3. **A guard keyed by the text of a line cannot see the clause above the line.** The sink sweep excuses `raise Declined("writer-busy", str(busy)) from busy` by its text. Widening `except LibraryBusy as busy` to
   `except (LibraryBusy, OSError) as busy` leaves the line, so the sweep stays green (measured: that mutant SURVIVES the sweep alone) while `str(busy)` is now an `OSError`'s words. The source reading above looks at the clause and
   kills it. When a table of allowed lines is the guard, ask what in the line's surroundings the allowance silently depends on.
4. **An exclusion written as "until its PR lands" is a debt with an owner: pay it in that PR.** `repair.py` joined the sink sweep here (nine counted lines, each a read of our own refusal or of a salvage failure's table/class
   label) and its `exc_info` allowance went to zero, leaving the allowlist `{}` so the ratchet still forbids a new site.
5. **A scanner reads `refusal.code` in a log call as the exception.** Bind the field to a name first (`code = refusal.code`) and log the name; the planted-passphrase test is the proof, not the shape of the line.
6. **The sink test must read the copy the bundle builder makes, not only `snapshot()`.** `dict(bundle._all_diagnostics_members(None))["columnar.json"]()` is the producer's copy before the bundle's final scrub; asserting on it (and not
   on the archive bytes) is what proves OUR scrub works rather than the net beneath it. The planted words put the passphrase at the two places a cut of 200 or 300 characters would split it, so a cut added before the scrub fails.

Tests: `tests/test_refusal_detail_source.py` (47), `tests/test_repair.py::test_a_refusal_whose_words_hold_the_passphrase_reaches_no_log_record_status_bundle_or_job_row_with_it` (both refusal kinds; log, `repair.snapshot()`,
`boot_sequence.snapshot()`, the bundle's `columnar.json`, the job row, the raised refusal, the registry's records and `database-damage.json`), 9 scrub-removal mutants and 4 of 5 producer mutants killed (the fifth is the gap shown on purpose, rule 3).
