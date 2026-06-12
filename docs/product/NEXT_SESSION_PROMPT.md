# Next-session opening prompt (single-use)

> **For the maintainer:** paste everything between the rulers into the FIRST
> message of the next Claude session, filling the one bracketed slot. Delete
> this file once used (the ledger remains the source of truth; this is just
> the ignition key). Written 2026-06-12, at the close of the DB-reliability +
> SQLCipher session (PR #77).

---

**Session mission: the PERFORMANCE BATCH (0.09 cycle) + field-report triage.**

Read `CLAUDE.md` in full first, as always — it overrides anything stale in
this prompt. Context: the DB-reliability batch shipped in PRs #76/#77
(merge-only restore + torture suite 10/10; SQLCipher at-rest encryption by
default with unlock UX, doctor, encrypt tool; 3-OS CI smoke green). Remaining
riders from that batch are ledgered (D1/D4 state-into-DB migrations, Settings
restore-preview UI, signing-key re-wrap in the encrypt tool, launcher
passphrase prompt) — they are NOT this session's mission unless room remains.

**Part 1 — field-report triage (do this first).** Here is my collected list
of UI glitches, bugs and observations from live testing:

[PASTE YOUR NUMBERED LIST HERE — screenshots/logs welcome; one line per item
is enough, e.g. "3. The X panel overlaps Y when the window is narrow"]

Triage rules (as agreed): record EVERY item in the ledger same-turn per the
protocol; quick fixes ship in this session as a dedicated polish batch
(tests + locale keys ×12 for any chrome touched; node --check after UI
edits); anything structural folds into its queued home in CLAUDE.md instead
of being half-built now — tell me which went where.

**Part 2 — the performance batch (the session's main work).** My corpus hit
6.4k articles / 228k keywords / 243 MB and the app got very slow; the
keyword diagnostics export initially failed at that scale. The ledgered
scope (see the PERFORMANCE BATCH entry in CLAUDE.md for the full record):
profile the hot endpoints against a real-scale corpus first — measure, then
fix, then re-measure and show me the numbers; precompute/persist keyword
totals or add the covering index on keyword_mentions; stream/paginate the
diagnostics export so it cannot time out; statement timeouts; PRAGMA
optimize/ANALYZE at boot; cached counts for vitals/Library; a VACUUM tool in
Settings; mmap for plaintext stores (NOT through the SQLCipher codec);
cachetools TTL caches for hot aggregations. The 64 MiB page cache +
temp_store=MEMORY already shipped. Acceptance: the keyword export downloads
cleanly at 228k keywords, and the Console feels responsive on a 243 MB
corpus on a 2-core Qubes VM. True multi-core (worker processes) only if the
cheap wins prove insufficient — single-writer SQLite stays the design.

Standing constraints: honesty by construction (degrade loudly, n shown,
caveats; no fabricated anything); local-first, zero network at boot; full
suite green + BOTH venv profiles when deps change; mypy ratchet ≤ baseline;
locale keys ×12 for new chrome; ledger updated same-turn for every ruling;
update docs/product/RELEASE_0.1_RC_GATE.md rows you close. Work on a fresh
branch, draft PR onto `0.09`, subscribe to its CI. The RC gate file carries
the full remaining map and the recommended order if you finish early.

---
