# After 1.0 — the backlog, and what is never built

**Status: written 2026-11-20 for `RELEASE_0.9_GATE.md` row H (Q118 = a).** Each item cites the ruling that put it
here. A Q, R or RC id resolves to its line in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md). A V1-n
id resolves to the §7 table of [`docs/design/V1_PATHWAY_2026-07-14.md`](../design/V1_PATHWAY_2026-07-14.md); those
rulings predate the index. `tests/test_post_1_0_backlog.py` reddens when a cited id stops resolving.

This file decides no priority, order or release for any item (brief `S09-01` S2: «may not decide»). An item
leaves the backlog only by a new ruling.

## 1. Backlog: wanted, after 1.0

- **Full text of all twelve Wikipedia editions.** V1-9 sets the 1.0 bar at one full edition plus the scaling
  machinery proven. It un-gates editions 2 to 12 from 1.0 without retracting them, so they land per storage
  milestone. Ruling: V1-9.
- **Election rosters and poll Tier-2.** V1-8 makes the election calendar the 1.0 scope, and moves rosters and
  poll Tier-2 after 1.0. (RC12 = c separately places raw poll data in 0.8. This file does not decide how the two
  meet.) Rulings: V1-8, RC12.
- **Case law, with ECLI identity.** Ruling: Q929 = a.
- **Bills and drafts, as their own lifecycle.** The law model refuses `bill` and `draft` by name today. Ruling:
  Q902 (its note: «include to add c (bills and drafts) to the post beta»).
- **Subnational law beyond what 0.7 reaches.** Q903 holds a recorded CONFLICT: (a) says subnational is post-beta,
  (b) says from 0.7. Q928 follows Q903. The CONFLICT is the maintainer's to resolve (`RELEASE_0.7_GATE.md` §3),
  so this item covers only what 0.7 leaves. Rulings: Q903, Q928.
- **Whatever `RELEASE_0.8_GATE.md` §3 cuts from the beta scope.** Nothing has been cut as of 2026-11-20. Ruling:
  Q118.

## 2. Ruled never: not backlog

These are listed so that they are not proposed again.

- **Scheduled automatic exports.** Ruling: Q220 = c.
- **Sending bulletins by mail from the app.** Download and paste stays the way out. Ruling: Q1131 = a (register D3).
- **Stored mailbox credentials.** Each pull asks again. Ruling: Q1137 = a (register I1).
- **Regular expressions in search.** A deliberate omission. Ruling: Q613 = a.
- **Wikimedia Enterprise and other keyed APIs.** No key-gated source. Ruling: Q718 = a.

## 3. Declined: not backlog

- **The ohsome pre-tracking history for OSM.** Q814 chose (b), the full-history planet; (c), ohsome, was not
  chosen. Ruling: Q814.

## 4. Named by the gate, but not listed above, and why

- **Religious calendars and the eclipse canon (Q1135).** Row H's text lists Q1135 = b («drop the feature») as
  never. RC13 was answered on 2026-09-29: a dedicated networked session researches the dates from published
  calendars and authorities, with eclipses (the eclipse half was confirmed as R99). So it is a ruled build,
  neither never nor backlog, though Q1135's own index line still carries the old CONFLICT note. Rulings: Q1135,
  RC13, R99.
