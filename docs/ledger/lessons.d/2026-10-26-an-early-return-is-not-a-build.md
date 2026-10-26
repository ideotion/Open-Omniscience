## 2026-10-26 — an early return is not a build: a function that can decline to run must say so, or its caller reports success

**Found by an independent read of #1510 (note 3, predating that PR).** `_refresh_persisted_build` returned `None` both after a refresh and when it opened no connection at all (the passphrase or the secure backend went away between the verdict and the call). The dispatcher reads "returned without raising" as "built": it released any hold, reset the run of failures and recorded `built`, for a call that refreshed nothing. On the dormant persisted path the cost is a status that says `built` when nothing was, and a failure run that a no-op ends.

**Rules.**
1. A function with an early return on a missing resource returns something its caller can tell apart from a finished job (here `False`; `True` after a refresh), and the caller treats the early return as a decline: no build ran, so no `built`, no release, no reset of a failure run.
2. When existing callers or test stubs return `None` for success, check for the explicit sentinel (`is False`), not for falsiness: `not result` turns every stub that returns nothing into a decline (the mutation that does exactly this fails two existing tests).
3. The decline names itself (`last_skip` reason `persisted-unavailable`), so a reader of the status sees "declined, and why" and not an absent build.

**Limits, stated.** The no-connection path is reached only on the persisted store, which is dormant in shipped code; it is read from code and exercised through a stub, as in #1510.
