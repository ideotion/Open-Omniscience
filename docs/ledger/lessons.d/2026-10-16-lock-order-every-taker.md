## 2026-10-16 — a rule about the order of two resources holds only if every taker obeys it: the hooks were fixed and eleven raw sites were not (PR #1421)

**What was found.** `connection_first` made the ORM hooks ask the pool before the write gate, and the Opus read of the follow-on found eleven other places that took both and still took the gate first. Reproduced with a pool of two: the gate holder failed with `TimeoutError` after 3.3 s where it took 0.3 s, the queued writers having the connections.

**The rules.**
1. **When a fix makes one taker obey an order, search for every taker of both resources before calling it done**, not only the family the defect was seen in. Here the grep was `with write_lock(` plus a pooled checkout (`connect`, `raw_connection`, `begin`, `session.connection()`, `begin_nested()`).
2. **Leave a scan behind, and prove the scan.** `tests/test_gate_connection_order.py` reads every `with write_lock(...)` in `src/`, fails on a checkout in a later item or in the body, and is itself tested on snippets of every wrong shape and every right shape; each exemption (a `begin_nested()` after an earlier `connection()` in the same function) has a snippet that must NOT be exempt (a `connection()` only after the gate, or an unrelated line before).
3. **Give each repaired site a probe and one headline**: the probe counts the connections the pool has out when the gate is first asked for; the headline shows a site waiting for the pool while the gate is free.
4. **State what the scan cannot see.** It is syntactic: a checkout deeper in a call made under the gate shows in a bundle as a pool timeout while the gate is held.
