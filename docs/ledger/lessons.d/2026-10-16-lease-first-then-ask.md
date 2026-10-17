## 2026-10-16 — an exclusive operation and a worker must take their two steps in opposite orders: the operation opens its window and then reads the leases, the worker takes its lease and then reads the window (PR #1429)

**What was found.** The storage guard's drain read `owns_the_machine()` and later took its corpus lease; an encryption in place that opened its window and then waited for the leases could land between the two, find no lease, and swap the file while the drain was about to open it. With a drain that needs no gate (PASSIVE) nothing else keeps it out.

**The rules.**
1. **Each side writes its own fact first and reads the other's second**: the operation (window, then leases), the worker (lease, then window). Either order alone leaves a gap; the pair leaves none, because one of the two reads must come after the other's write.
2. **The wait is bounded and refuses by name**: the route answers 409 and lists the leases rather than swapping under them or waiting for ever (the restore's 180 s).
3. **A worker that declines stamps nothing**: a drain that found the machine owned is not a drain that ran, so the cadence is not taken and it runs as soon as the machine is free.
4. **Test the ordering, not the outcome**: a test records which leases are held at the moment of each ask (`[[], ["storage-guard-drain"]]`), so moving the second ask outside the lease fails it.
