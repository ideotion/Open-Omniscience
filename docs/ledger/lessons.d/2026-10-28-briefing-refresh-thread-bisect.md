## 2026-10-28 — The thread that outlived a test and wrote briefing_cache.json into the R236 test dir: bisect result (RC2, R333, after #1596 and #1629)

**The question.** Before R333 a `briefing_cache.json` appeared in a folder a test had pointed the data directory at (R236). Which thread wrote it, and from which test?

**What RC2's bisect observed.** The thread left behind after a test is `oo-briefing-refresh`, started by `tests/test_api_wiring.py::test_wired_endpoints_dispatch_not_404`. Path: `src/api/briefing.py:173 get_briefing` calls `src/briefing/service.py:631 _ensure_background_refresh()`, which starts the thread at `service.py:139 thread.start()`. On main the quiesce fixture reaps it after 0.801 s (observed). The starter was already pinned by #1596 (the `_run_cache_path` contextvar is set for `_bg_refresh`/`_ensure_background_refresh`) and is reaped by R333.

**What is inferred, not observed.** That this was the thread that wrote `briefing_cache.json` into the R236 test dir before R333 is INFERRED from the starter, the path it writes and the timing; no run caught the write itself.

**The sibling path (#1629).** The scheduler starts its own refresh thread, `oo-briefing-bg` (`BackgroundScheduler._refresh_briefing_async`). A new thread starts with an EMPTY contextvars context, so the pin the starter holds does not reach it: the scheduler resolves the cache path before it starts the thread and pins it for the whole run (`cache_path_for_a_new_run` / `pinned_cache_path` in `src/briefing/service.py`). Test the helper directly: a scheduler-level test cannot see the reset, because the reset happens in a thread whose context is thrown away (the first version of that test was green without the reset, i.e. vacuous).

**Rule.** When a file lands in a folder a test made, find the thread by bisecting the suite for the leftover thread first, and say which part of the chain was seen and which was reasoned. A contextvar set in the starter pins nothing in a thread the starter creates unless the value is passed in explicitly.

**Not fixed here, stated.** `Thread.start()` raising inside `_refresh_briefing_async` leaves `_briefing_bg_lock` held. It is older than #1629, was routed to the keyword lane as a defect candidate, and is not in that PR.
