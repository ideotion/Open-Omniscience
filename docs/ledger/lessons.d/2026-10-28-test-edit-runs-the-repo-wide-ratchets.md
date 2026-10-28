## 2026-10-28 — Editing a test file runs the repo-wide ratchets too, not only the file and its neighbours (#1617, two Core-only reds from two test-only edits)

**What was found.** #1617 went red twice in the Core-only job, each time from a test-only edit of `tests/test_collector_immediate_stop.py`. First a source-text pin on `should_stop=self._stop.is_set` broke when `_default_run_once` was handed `_pass_should_stop` (a grep of `tests/` for the replaced line would have found it). The fix for that, two `src.split(...)` calls to read the decider, added two hand-rolled source-slicing sites and put `tests/test_source_slicing_discipline.py` at 232 against a budget of 230. The touched file, its neighbours and the sink/os-patch/ledger guards were all green locally both times; the ratchet lives in a file that touches none of them.

**What it cost.** Two full Core-only runs (about 50 minutes each) and a second round trip to the coordinator, for edits that could not have changed behaviour.

**Rules.**
1. **After any edit to a file under `tests/`, run the repo-wide ratchets**: `tests/test_*discipline*.py` and `tests/test_*ratchet*.py`, beside the sink, os-patch and ledger guards. They scan every test file, so the file you edited is not the file that fails.
2. **Read Python source in a test with `tests.js_source_helper.python_function_source`**, never a new `split(...)[1]`; the ratchet counts the splits and the helper takes its bounds from `ast`.
3. **A fix for a red is an edit too**: it gets the same battery as the change it fixes.
