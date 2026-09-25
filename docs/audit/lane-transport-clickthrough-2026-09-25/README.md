# Lane transport click-through — 2026-09-25 (S04-08 S5, gate row O)

Chromium (Playwright, `/opt/pw-browsers/chromium`) against a real server
(`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0`, uvicorn on port 8745, no proxy variables in its
environment) on a data folder that `seed.py` prepared: protected mode ON through
`socks5h://127.0.0.1:9`, the discard port, where nothing listens. Every fetch is handed that
proxy, so the walk shows real transport failures while nothing can leave the machine. Two
download states are seeded the way a process leaves them (a map region the Pause button
stopped, one a killed process left mid-transfer); everything else is produced live.
Languages switched through the real top-bar switcher (invariant #15); airplane mode left and
re-entered through the real plane button and the consent popup's own buttons; the task
manager opened through the real top-bar button, which opens `/tasks` as its own page.

| View | Result |
|---|---|
| Consent popup, protected mode, en / fr / ar | Every lane's hover names its transport in the operator's language: `through your proxy` for the twelve that honour it, `mostly direct` for Local AI (only the installer check is proxied), `direct, even with protected mode on` for the newsletter mailbox and chain of custody. The popup's footer: `Fetches ride the proxy you configured; a lane never falls back to the clear internet on its own.` Arabic right-to-left |
| Same popup, transparent mode with the proxy still stored | Every lane reads `direct — protected mode is off`, and the footer says the hosts see your address. A stored proxy is not read as a route in use |
| Online through `Go online`, the Wikipedia stream behind the dead proxy | `wiki_lane.reason = transport-waiting`, `waiting_on` = the real SOCKS `Connection refused`; the W toggle's hover says `Waiting for a connection: …` in en / fr / ar and it is NOT drawn as live |
| The French dump resumed online | `failed`, with the proxy's refusal verbatim in the task manager: `Failed: SOCKSHTTPSConnectionPool(host='dumps.wikimedia.org' …) Connection refused` |
| Task manager, en / fr / ar | Each paused download says who paused it: `Paused by airplane mode. Resume asks to go online first.` (two started while offline), `Paused by you.` (asia), `Paused when the app stopped mid-download; the partial file is kept.` (africa, demoted by the boot). Translated in all three |
| Back to airplane mode through the plane button | `online: false`; the stream stops within one slice: `active: false`, `reason: airplane-mode` |

`report.json` holds the measured values; `seed.py` and `walk.py` reproduce it. **0 page
errors.** Every 500 in the server log and every console error was `/api/briefing`, below.

**Found and fixed by this walk, before it was recorded:**

- **The Wikipedia stream kept sleeping through airplane mode.** A backoff after a failed
  connection was one long sleep, so the stream went on reporting itself running for up to
  five minutes (`MAX_BACKOFF_S`) after the operator went offline or pressed Stop. It now waits in one-second
  slices and ends on Stop, or is refused BY NAME on the kill switch, within one slice
  (`tests/test_lane_transport.py::test_a_STOP_ends_a_long_backoff_within_one_slice`,
  `::test_AIRPLANE_MODE_during_a_backoff_is_refused_by_name_within_one_slice`); a backoff
  nobody interrupts is still waited in full.
- **The Wikipedia lane never stored anything on a fresh install.** The drain and the pin
  opened `wiki.db` with `lane_session("wiki", create=True)`, which makes the FILE but not
  its schema, so the first drain failed, lane status answered 500, and every later drain
  found an empty file. Both now go through `wiki_lane_session()`, which runs
  `create_lane("wiki")` first, and with it the locked-store refusal and the plaintext-lane
  refusal beside an encrypted corpus (Q1005). An install that already has the empty file
  is repaired on its next drain (`tests/test_wiki_lane_schema.py`, which also forbids any
  module outside the store from passing `create=` again).
- **The task manager the top-bar button opens showed no cause.** `/tasks` is its own page
  with its own row renderer, so the cause drawn in the in-app window never reached it.
  It now draws the same lines; `tests/job_why_node_test.js` runs every assertion against
  both renderers and checks each actually calls its function.
- **The offline hint covered the open language menu.** Cancelling the consent popup
  raises the prominent `You're offline` hint just under the top bar, where the language
  menu drops down; at z-index 360 against the menu's 300 it covered the first five
  languages, and Playwright's own log said the hint "intercepts pointer events" on a
  click at `Français`. The menu now stacks above it
  (`test_repo_invariants.py::test_the_OPEN_language_menu_sits_above_the_net_coach`).

**Handed to another thread:** `GET /api/briefing` answers 500 on this build
(`src/api/briefing.py:74` calls `.values()` on a list). It is not this slice's code and is
fixed in its own thread; the Home briefing panel says `The briefing could not be read just
now` rather than claiming the corpus is empty.

**Seen, not investigated (not this slice's surface):** after switching the main app to
French, the Home strip's `Your library is empty — head to Collect…` and `Automatic
collection: stopped` stayed English, though both strings are keyed in every locale.

**Still owed:** the maintainer's own click-through (Q1128 = a).
