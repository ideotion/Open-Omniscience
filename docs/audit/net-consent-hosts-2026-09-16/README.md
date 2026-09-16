# Click-through record — the network-consent dialog's per-lane host disclosure

**Surface:** `#net-consent` (`src/static/index.html`) with the Q1002 lane list.
**Slice:** `S04-01`, `RELEASE_0.4_GATE.md` row H. **Rulings:** Q1001 = a, Q1002 = a.
**Bar:** Q1128 = a — Chromium in the sandbox **plus the maintainer's own click-through**.
This record is the first half. **The maintainer's pass is still owed** and is the only
thing that makes this surface *verified*; what follows is *Chromium-verified (remote
sandbox)*.

**Engine:** Chromium 1194 (`/opt/pw-browsers/chromium-1194`), Playwright sync API.
**Harness:** [`clickthrough.py`](clickthrough.py), run against a throwaway instance
(`OO_DATA_DIR=<tmp> OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1`, port 8010).
**Raw observations:** [`observations.json`](observations.json).

## The state every observation was made in

`OO_NO_SCHEDULER=1` skips the boot-time kill-switch activation, so the instance starts
**online** — measured, not assumed: `GET /api/system/network` answered `{"online": true}`
on a fresh boot. A consent-gate check made in that state proves nothing, because
`ensureOnline` returns immediately and the popup never opens. The harness therefore
**engages airplane mode explicitly** (`POST /api/scheduler/stop`, the Stop button's own
path) and asserts it engaged before touching the UI. Every observation below was made
with the kill switch ON.

The first-launch guide is modal and covers the top bar; it is dismissed by a **real
click** on `#gw-close`, not a scripted `close()`, and airplane mode is re-asserted
afterwards. The dialog itself is opened by a real `page.click("#net-toggle")`.

## What was observed

| # | Observation | Result |
|---|---|---|
| 1 | The dialog opens from the top-bar airplane toggle and renders 14 lanes in 3 buckets | ✅ |
| 2 | Every one of the 14 lanes carries a host hover (`[title]` → `.oo-tip-target`) | ✅ 14 of 14 |
| 3 | Hovering a lane opens the ONE shared `#oo-tip` bubble with that lane's hosts | ✅ visible, text matches |
| 4 | An enumerable lane's hover names its hosts verbatim | ✅ e.g. Calendars → all 14 |
| 5 | A class lane's hover gives the count and points at the security notes | ✅ Press → `9033 hosts — …` |
| 6 | A lane with no opt-out says so in its hover | ✅ Law, Calendars |
| 7 | A lane whose opt-out the API cannot reach says *that* instead | ✅ Hazard feeds |
| 8 | A lane outside the ethical fetcher says so | ✅ Newsletter mailbox, Chain of custody |
| 9 | Both standing caveats stay **visible in the dialog**, not moved into the hover | ✅ en, ar, zh |
| 10 | `dir` flips to `rtl` in Arabic and the dialog mirrors | ✅ |
| 11 | Turning a lane off moves it to "Switched off right now" | ✅ `world_discovery_per_pass: 0` → Source discovery moves |
| 12 | Turning the hazard lane off does **not** move it — the PUT is discarded | ⚠ **finding**, see below |
| 13 | At 375×667 both buttons are reachable without scrolling | ✅ after the fix below |
| 14 | At 375×667 both standing caveats are in normal flow and reachable | ✅ |

## Two things this run found

**1. The hazard feeds' documented opt-out does not work.** `PUT /api/scheduler/config
{"auto_track_signals": false}` returns **HTTP 200** and the value reads back `true`.
`auto_track_signals` is a real `SchedulerSettings` field and `save_settings` honours it,
but `SchedulerConfigUpdate` — the request model the endpoint validates against — does not
declare it, so `model_dump(exclude_unset=True)` returns `{}`. The lane correctly stays in
"Runs on every collection pass", and its hover now says why. Not fixed here; recorded in
`docs/ledger/OPEN_QUEUE.md` (2026-09-16) with the two sibling cases.

**2. The dialog overflowed at phone width, and what fell off was the decision.** Before
the fix: **851px of content in a 667px viewport** at 375×667, with both caveats and both
buttons below the fold and no useful scroll. Fixed by giving `#net-consent` the shape
`#guide-wizard` already uses — a scrolling body (`max-height:58vh;overflow:auto`) with the
controls pinned outside it. After: **521px in 667px**, dialog not clipped, "Go online" in
the viewport without scrolling, the last caveat reachable by scrolling the body.

The page's **horizontal** scroll at 375px is **pre-existing**: it is present with the
dialog closed too, measured in the same run. Not attributed to this change.

## Screenshots

| File | What it shows |
|---|---|
| `net-consent-en.png` | 900×1000, English — the full dialog |
| `net-consent-ar.png` | 900×1000, Arabic — RTL mirroring |
| `net-consent-zh.png` | 900×1000, Simplified Chinese |
| `net-consent-en-lane-off.png` | Source discovery moved to "Switched off right now" |
| `net-consent-en-375.png` | 375×667 — both buttons pinned and reachable |
| `net-consent-en-375-scrolled.png` | 375×667, body scrolled — the last caveat on screen |

## What still awaits the maintainer

1. **Their own click-through** of this dialog on their machine (Q1128 = a). That is what
   closes row H's verification half; nothing here substitutes for it.
2. **Their word on the lane grouping names** used in the table and the hover — a design
   note in brief `S04-01`, binding nobody until said.
3. **A ruling on where the three broken ride-along opt-outs get fixed** (`OPEN_QUEUE.md`,
   2026-09-16). Row T (`S04-13`) is the natural home; nothing is assumed.
