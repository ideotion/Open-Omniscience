## 2026-11-14 — a fault stub whose signature fell behind injects a TypeError, and a one-line lambda fires no LINE event (OPEN_QUEUE 30, R412, PR #1996)

**What was found.** The first run of the committed fault-reach audit (`scripts/fault_reach_audit.py`) over 11,848 test functions found
one vacuous test the October hand run could not have shown: `tests/test_volume_job.py::test_a_pause_hiccup_never_aborts_the_restore`
replaced `pause_for_exclusive_operation` with `_boom_pause(timeout=10.0)`, and since R383 the restore calls it with `claim=`. The call
raised `TypeError` before the stub's body ran, the restore's `except Exception` caught that, and the test stayed green while proving
the restore survives a signature mistake, not the scheduler failure it describes. Narrowing the except to `TypeError` kept the old
test green; the fixed stub (`*_a, **_k`) goes red under that mutant. Building the tool turned up a second fact: on Python 3.13 a
one-line lambda runs without a single `sys.monitoring` LINE event of its own, so a `(_ for _ in ()).throw(exc)` lambda is seen only
through PY_START (its code object starting at the lambda's line).

**What it cost.** Nothing shipped wrong, but the test had guarded nothing since the `claim=` change, and a first version of the tool
reported a parametrized lambda fault that fired as never fired.

**The rule.** (1) A fault stub takes `*args, **kwargs` unless the test is about the signature: a stub that copies the real
signature falls behind when the real one grows an argument, and the fault it injects becomes a `TypeError` that any broad
`except` swallows. (2) A test of "a raise here is survived" should assert something only the intended fault produces (the
stub's own message in the log, a counter the stub bumps), not only that the run ended well. (3) To ask whether code ran, use
`sys.monitoring` with LINE for statements and PY_START for lambdas, and return `DISABLE` everywhere else; never rewrite the
test file to count.
