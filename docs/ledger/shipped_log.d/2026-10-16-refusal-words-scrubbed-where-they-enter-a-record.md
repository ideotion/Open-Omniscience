## 2026-10-16 — a repair refusal's words are scrubbed where they enter a record or a log (R138) (PR #1406)

`run()` in `src/database/repair.py` wrote `refusal.detail` (of a `Declined`, or of a `salvage.SalvageRefused` re-raised as one) straight into two log lines and into `reason_text`, which the boot-sequence status
(`boot_sequence.snapshot()["repair_database"]`) and the Diagnostics bundle's `columnar.json` carry. Every producer said a fixed sentence, so nothing leaked; nothing kept it so. R138 (the coordinator session's ruling on the WAL
thread's note): the words now enter both the record and the log through `exception_text(refusal, typed=False)`, before any cut; the re-raised `Declined` is made of the scrubbed words; the last `exc_info` allowance
(`tests/data/exc_info_allowlist.json`, two `exc-arg` hits in `repair.py`) is gone and the file is `{}`; `repair.py` joins `tests/test_sink_sweep_records.py` (nine counted lines).

- **No text changed.** Every current sentence is the same string; the only difference is a passphrase the process holds, which is taken out.
- **Source reading:** `tests/test_refusal_detail_source.py` reads each `Declined(...)`/`SalvageRefused(...)` call (code, words, `detail=` and facts, through the names assigned in the same function): a caught exception may only be
  `type(x).__name__`, an argument of `failure_text`/`failure_label`, or, under an `except` that names only `LibraryBusy`/`Declined`/`SalvageRefused`, `str(x)`/`exception_text(x)`/`x.detail`/`x.code`. 47 checks including a negative
  control for every form; 12 weakenings of the reading each killed by a named control.
- **Sink test:** a passphrase planted in a `Declined` and in a `SalvageRefused` (placed where a cut at 200 or 300 characters would split it) is absent from the log, `repair.snapshot()`, `boot_sequence.snapshot()`, the bundle
  builder's `columnar.json`, the job row, the raised refusal, the registry's records and `database-damage.json`; the scrubbed words are present whole. Removing the scrub at any of the five places, cutting before it, or
  replacing it with `str` fails the named test (9 mutants).
- **A gap shown on purpose:** widening `except LibraryBusy as busy` to `(LibraryBusy, OSError)` leaves the sweep's allowed line unchanged and the sweep green; only the source reading above fails it.
