## 2026-10-27 — a second caller of a guarded build inherits the guard by calling the guard, not by copying the build

**Found by the Q's measurement of every GET route (R278).** `GET /api/diagnostics/rollup-benchmark` built the whole-corpus keyword rollup in memory, the build that crashed the app in #1310, and met none of the guards that the served build had been given: no exclusive window, boot order, memory guard, stop hold, killed-build marker or affordability check, and no lock against a served build running beside it. The guards had been added where the build's one caller lived (the dispatcher), so a second caller written earlier for a different purpose never saw them. The 0.5.0 fix was correct and incomplete for exactly that reason.

**Rules.**
1. When a build is made safe by checks that sit in its caller, every OTHER caller of the build is unsafe until it makes the same checks. Factor the checks into one function the callers share (`rollup_serve.first_start_decline`, the dispatcher's verdict loop moved out unchanged) rather than copying the list, which drifts.
2. A shared check that depends on the caller's context must be asked in the right context. Three verdicts stand aside while the persisted store is active, and the benchmark always builds in memory, so it asks them inside `rollup_serve.inmemory_view()`, a per-thread override: the question is about the build that will run, not about the store the app happens to serve from. A per-thread view cannot leak into the serve's own decisions.
3. A caller that declines reports it in its own result and does not write the serve's status (`last_skip`): a benchmark's refusal is not the serve's decline.
4. A caller that builds beside the serve takes the serve's build lock without waiting, and releases it in a `finally` taken straight after the acquire (a decline and an error both leave it free).
5. Test the refusal with the real verdict and a seeded hold, and the build entry points patched to raise: the test then fails if the guard is skipped, not merely if the answer changes. Tests that are about something else stub the verdicts out, because the real ones read the runner's memory.

**Also fixed here.** `columnar.open_store` attached the persisted connection and, if a later step raised, fell back to memory without closing it. Close what you opened before you fall back; the file unlink after it needs the handle gone on Windows.

**Limits, stated.** The per-batch memory-guard poll inside the build is the serve's alone (its hook also writes the build progress record), so the benchmark is bounded at its start by the verdicts and in the build by the budget's DuckDB limit. The cross-site guard on the GET route is a separate item (RC2).
