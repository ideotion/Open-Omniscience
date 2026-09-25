# Scheduler lanes click-through — 2026-09-25 (S04-08 S3, gate row O)

Chromium (Playwright, `/opt/pw-browsers/chromium`) against a real server
(`OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0`, port 8743) whose `app_state` row was
seeded as an install left in the retired **Markets** mode: `{"mode": "markets", ...}`.
Languages switched through the real top-bar switcher (invariant #15). The first-run guide
opens over a fresh install and is closed before each step; it is not the surface under test.

| View | Result |
|---|---|
| en / fr / ar at 1440 px, en at 375 px | The retired-mode line visible and translated (ar right-to-left); both markets opt-ins checked by the migration; crawl caps shown; no `#sch-mode`; no horizontal scroll; **0 page errors** |
| Dismiss → uncheck "Run my price-extraction rules" → Save → reload | Line hidden and stays hidden (`retired: []`); `auto_run_market_rules=false` and `auto_refresh_stat_subscriptions=true` persisted; `mode` absent from the config payload; targets preview renders with no mode gate |

`report.json` holds the measured values; `walk.py` reproduces it. **Found and fixed before
this walk:** `applySchedConfig` still called the removed `toggleCrawlFields()`, a
ReferenceError on every open of the panel that no Python test could see.

**Still owed:** the maintainer's own click-through (Q1128 = a). The targets preview's
"sources targeted … by language" line renders in English on the fr/ar pages; that string
predates this change and is out of its scope.
