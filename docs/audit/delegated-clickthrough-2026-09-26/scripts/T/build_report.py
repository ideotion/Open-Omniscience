import json
D = "/tmp/claude-0/walk/T"
report = {
 "row": "T",
 "environment": {
  "encrypted": True,
  "seed": "scripts/ui_clickthrough_seed.py --mini (24 synthetic articles) with OO_DB_PASSPHRASE='walk-pass-2026' and OO_DB_PLAINTEXT unset; the db header was checked and is ciphertext; /api/system/lock-state reported unlocked-encrypted after the unlock",
  "ports": [8846],
  "scratch_dir": "/tmp/claude-0/walk/T/",
  "notes": ("origin/main 462145c (detached, shallow clone), Chromium /opt/pw-browsers/chromium headless via Playwright sync, 1440x950 main pass, 375x812 phone pass. "
            "DEVIATIONS FROM THE STEP SHEET: (1) encrypted store instead of the sheet's OO_DB_PLAINTEXT=1, as the harness requires, so T1 correctly opens on the /unlock passphrase screen (#pw -> #btn-unlock); (2) port 8846 instead of 8010 (8847 unused); "
            "(3) --mini seed (the row needs little data). Boot 1 (T1-T7, 375 pass, T9/T10 reads) = PID 14894 started with neither OO_DB_PASSPHRASE nor OO_DB_PLAINTEXT nor OO_NO_SCHEDULER, so it booted LOCKED and in airplane mode. "
            "Boot 2 (T8) = PID 17174, same data dir, OO_NO_SCHEDULER=1 as the step prescribes (online, scheduler not running, wiki_lane active=false reason not-started). Both launched with the open-omniscience console script, proxy env vars unset; both killed by PID afterwards. "
            "An lsof monitor sampled PID 17174's internet sockets every second through its whole online window: zero non-loopback sockets. No consent 'Go online' button was ever clicked. "
            "T7's line was run through page.evaluate (the exact console snippet); T9 opened the hidden window with toggleVitals() as the step itself prescribes. Scripts: walk1.py, walk1b.py (T5 retries + app offline titles), walk2.py (T8), probe_lanes.py, probe375.py; raw measurements in walk1.json, walk1b.json, walk2.json.")
 },
 "steps": [
  {"id": "T1", "result": "pass", "locales": ["en"], "screenshot": f"{D}/T-T1-unlock-en.png, {D}/T-T1-home-en.png",
   "observed": "Encrypted store, so /unlock showed the passphrase view (#view-unlock), which is expected on this path. No legal screen (#view-legal hidden). After the unlock it landed on /#home. After 8 s with no clicks there was no guide wizard and no consent dialog. The plane was FILLED (fill=currentColor, class off) and body had .net-offline. The top bar showed a red inset 2px edge, rgb(192,57,43) in Ink. /api/system/network returned online:false. The coach bubble was showing. Sidebar Feed listed 20 synthetic articles (e.g. 'Mini technology 5 — en')."},
  {"id": "T2", "result": "pass", "locales": ["en"], "screenshot": f"{D}/T-T2-coach-4themes-en.png",
   "observed": "Bubble text was exact: 'You're offline. Switch off airplane mode to go online and start collecting.' and 'You'll confirm before anything connects.'. 'Not now' sat on the left (x=1245) and 'Go online' on the right (x=1331). Both buttons are unclassed. Theme tiles were clicked in Settings > Graphics. In Ink, Paper, Solar and Mint the computed styles of the two buttons were IDENTICAL: same background (Ink rgb(91,157,217), Paper rgb(154,106,47), Solar rgb(181,137,0), Mint rgb(46,125,91)), same text colour, weight 600, 12px, height 28px, border 0 on all sides, no outline, opacity 1, no filter, no shadow. The diff list was empty in all four. Only the widths differed (Ink 78.08 vs 85.97 px). The bubble stayed visible from Home to Feed to Settings. The walk finished on Ink."},
  {"id": "T3", "result": "pass", "locales": ["fr", "ar", "zh", "en"], "screenshot": f"{D}/T-T3-coach-fr.png, {D}/T-T3-coach-ar.png, {D}/T-T3-coach-zh.png",
   "observed": "Switched live with the top-bar #lang-switch. fr: 'Plus tard' / 'Passer en ligne', body 'Vous êtes hors ligne. Désactivez le mode avion pour passer en ligne et lancer la collecte.', sub translated. ar: 'ليس الآن' / 'الاتصال', dir=rtl, the page and the button order mirrored, both sentences translated and readable. zh: '暂不' / '联网', both sentences translated. In every language the two buttons were computed-identical (empty diff). SIDE OBSERVATION (not a row-T fail, recorded as a P3 defect): the bubble does NOT re-anchor on a language or direction switch. After the switch to ar the plane moved to x=186 while the bubble stayed at x=1162, 1019 px from the plane, over the sidebar brand and the Graphics subtab. A 6 px window resize re-anchored it (13 px). Switching on to zh then en left it 986 px away at the left edge."},
  {"id": "T4", "result": "pass", "locales": ["en"], "screenshot": f"{D}/T-T4-consent-en.png, {D}/T-T4-consent-lanes-filled-en.png",
   "observed": "The bubble's 'Go online' opened #net-consent 'Go online?' (reason 'Allow network requests again', interfaces 'eth0: 192.0.2.2', both hints visible). The server stayed offline while the dialog was open. The lane list still read '…' at about 1.2 s. A separate probe showed it fills within about 1 s ('Runs on every collection pass: Press collection n=9033 …'), so this is not a defect. The dialog's 'Stay offline' keeps .secondary (quieter), as intended. After 'Stay offline': the bubble was gone, localStorage oo_net_coach_v1 = {\"seen\":1,\"dismissed\":true}, the plane was still filled, the red edge was still there, no 'Back online' toast appeared, and /api/system/network was online:false."},
  {"id": "T5", "result": "fail", "locales": ["en", "fr", "ar", "zh"], "screenshot": f"{D}/T-T5-tasks-while-offline-en-fr-ar-zh.png",
   "observed": "#tm-open opened a new tab 'Task manager · FOOS' (/tasks). The server was in airplane mode (/api/system/network online:false, /api/scheduler/status online:false). Even so, the Task manager's plane was HOLLOW (fill=none), NOT red, and its hover title read 'Online — click to go offline (airplane mode); every new network request will be refused.'. The summary state read 'Idle', not 'Airplane mode'. Retried three times straight on /tasks with 6, 12 and 20 s waits: identical every time. The expected offline text 'Offline (airplane mode) — click to go online in the app; …' never appeared in any language. Cause: taskmanager.html:522-524 derives the state from act.online of /api/scheduler/activity, and that payload has no 'online' key. src/scheduler/runner.py:2282-2308 returns status() plus extras; only src/api/scheduler.py:130 _status_payload adds it for the /status responses. So undefined !== false paints online, always. What DID work: the title re-translated live without a reload (fr/ar/zh online strings exact, ar mirrored), but for the wrong state. Side effect of the live switch: after ar→zh the summary strip (state, metric labels, 'Live') stayed in Arabic until the next poll (P3)."},
  {"id": "T6", "result": "pass", "locales": ["en", "fr", "ar", "zh"], "screenshot": f"{D}/T-T6-knob-hover-max-en.png, {D}/T-T6-click1-en.png, {D}/T-T6-click2-en.png",
   "observed": "The fresh folder started at Maximum: config collect_rate_mode=maximum, class rate-max, needle rotate(48), accent rgb(91,157,217). The #oo-tip hover read 'Collection speed: Maximum — uses your connection fully (politeness per host unchanged). Click for the considerate 500 KiB/s target.' Click 1: the needle swung to rotate(-48), the accent went (rgb(232,235,240)), the toast read 'Collection speed set to the 500 KiB/s target — applies from the next pass.', config mode=target/500, and Settings > Advanced > Collection > Advanced (legacy) showed '500 kbps' with slider value 2 (3rd of 7 stops). Click 2: needle and accent back, toast 'Collection speed set to Maximum — applies from the next pass.', Settings 'Maximum' with the slider at 6 (far right), config maximum. A MutationObserver on #net-consent counted 0 opens, and the app stayed offline throughout. Settings > Wikipedia and > OpenStreetMap had no range or number input and no text matching speed/bandwidth/kbps/KiB/rate: there is no per-download cap. Re-checked in fr/ar/zh: the hover and both messages were translated and the slider stayed in sync. The KiB/s vs kbps wording is visible and already known (OPEN_QUEUE:697), so it is not counted here."},
  {"id": "T7", "result": "pass", "locales": ["en"],
   "observed": "150 sequential fetch('/api/articles?limit=1') from the app page: ok 150, refused 0, no other statuses, 1.6 s."},
  {"id": "T8", "result": "fail", "locales": ["en", "fr", "ar", "zh"], "screenshot": f"{D}/T-T8-app-online-en.png, {D}/T-T8-tasks-online-en-fr-ar-zh.png, {D}/T-T8-tasks-after-offline-click-en.png",
   "observed": "ONLINE HALF PASSES. Boot with OO_NO_SCHEDULER=1: online:true, scheduler running=false, wiki_lane active=false. Both planes were hollow. The app's styled bubble and the /tasks title both read 'Online — click to go offline (airplane mode); every new network request will be refused.', and the summary read 'Idle'. Nothing said 'stops all collection'. Live switches in /tasks, sampled every 100 ms: the title flipped to the exact fr/ar/zh strings 100–150 ms after the menu click, with no /api/scheduler/activity poll in between, so the oo:langchange listener did it. OFFLINE HALF FAILS. One click on the /tasks plane: the POST worked (/api/system/network online:false; the app tab repainted filled/offline within 6.5 s), and #tm-conn showed 'Offline — every new network request is refused. One in-flight request may finish.'. But over 12 s of 200 ms samples the /tasks plane stayed HOLLOW, the title stayed the online text, and the summary stayed 'Idle' ('Airplane mode' never appeared). The click handler's own refresh() immediately re-applies act.online (undefined) as online. Same root cause as T5."},
  {"id": "T9", "result": "not-measurable-here", "locales": ["en"], "screenshot": f"{D}/T-T9-vitals-system-en.png",
   "observed": "No collection pass can run here (no egress), so /api/scheduler/activity has collect_perf=null and there is no process_budget. toggleVitals() opened the in-app Task manager window. Its System subtab has NO 'COLLECTION SPEED' block, which is the correct no-pass state per the step. The only on-screen element calling toggleVitals is the window's own close button, which confirms the recorded 'no clickable entry point' finding. fr/ar and the budget/measured figures were not observable."},
  {"id": "T10", "result": "not-measurable-here", "locales": ["en"],
   "observed": "/api/jobs/history?limit=100 returned no runs and no 'crawl_delay_deferred'. The data folder has no host_schedule.json. Not observed on this corpus: nothing has ever been collected."},
  {"id": "375px", "result": "fail", "locales": ["en"], "screenshot": f"{D}/T-375-home-en.png, {D}/T-375-tasks-en.png",
   "observed": "Home at 375x812 (fresh profile): scrollWidth - clientWidth = 71. #home-tier ('EARLY CORPUS 24 articles · 509 days thin evidence — read with care') is 409 px wide and pushes its caveat past the right edge. Same in light and dark. The coach itself fits the viewport: buttons equal and unclipped, arrow 15 px from the plane. /tasks at 375: overflow 144 px, from the subtab row (the 'Schedule' and 'Sessions' buttons end at 428 and 519 px). The same page also showed the T5 defect (hollow plane, 'Idle' while offline)."}
 ],
 "page_errors": [],
 "http_errors": [],
 "junk_text": [],
 "defects": [
  {"title": "Task manager (/tasks) always shows ONLINE: plane never fills, offline title and 'Airplane mode' state unreachable",
   "severity": "P1", "step_ids": ["T5", "T8"],
   "repro": "Boot normally (airplane mode). Click the top-bar 'Tasks & system' icon, or open /tasks. Hover the plane. Or: boot with OO_NO_SCHEDULER=1 (online), open /tasks and click its plane once.",
   "expected": "While offline: plane filled and red, title 'Offline (airplane mode) — click to go online in the app; you'll be asked to confirm first.' (translated live), summary 'Airplane mode'. After the offline click, the same.",
   "actual": "While the server is offline (/api/system/network and /api/scheduler/status both online:false): plane hollow and not red, title 'Online — click to go offline (airplane mode); every new network request will be refused.', summary 'Idle'. Seen on 3 retries (6/12/20 s) and in fr/ar/zh. After the offline click the POST succeeds and #tm-conn shows the offline toast, but the plane, title and summary stay online-looking for 12 s+. The safety control's FILL (invariant #14) misstates the state, and Q1126's offline half is never shown.",
   "evidence": f"{D}/T-T5-tasks-while-offline-en-fr-ar-zh.png, {D}/T-T8-tasks-after-offline-click-en.png, walk1b.json T5_retries (api_activity_has_online:false). Cause: src/static/taskmanager.html:522-524 (and :392 renderSchedule) read act.online from GET /api/scheduler/activity. src/scheduler/runner.py:2282-2308 builds that payload from self.status() without 'online'; only src/api/scheduler.py:130 (_status_payload, used by the /status responses) adds it. So act.online is undefined and `act.online !== false` paints online."},
  {"title": "Task manager health pill always reads 'degraded' though /api/health says healthy",
   "severity": "P2", "step_ids": ["T5", "T8"],
   "repro": "Open /tasks on a healthy server and read the pill left of 'AI'.",
   "expected": "'healthy', as the app's own top bar shows for the same server",
   "actual": "'degraded' ('dégradé', 'متدهور', '已降级') in every run, while GET /api/health returns {\"status\":\"healthy\",...}",
   "evidence": f"{D}/T-T5-tasks-while-offline-en-fr-ar-zh.png vs {D}/T-T6-click1-en.png. src/static/taskmanager.html:746 tests h.status === 'ok' || h.ok === true || h.healthy === true, while src/api/main.py:701 returns status 'healthy'."},
  {"title": "Home's early-corpus strip overflows at 375 px and pushes its caveat off-screen",
   "severity": "P2", "step_ids": ["375px"],
   "repro": "Open the app at a 375 px viewport on a young corpus (24 articles) and look at the Home at-a-glance card.",
   "expected": "No horizontal page scroll (scrollWidth - clientWidth = 0); the caveat 'thin evidence — read with care' fully visible",
   "actual": "The page scrolls sideways by 71 px. #home-tier.corpus-tier.tier-early is 409 px wide, and its span.tier-caveat ends at 446 px, cut at 'thin evidence — r'.",
   "evidence": f"{D}/T-375-home-en.png; probe375.py output (light and dark identical)"},
  {"title": "Net-coach bubble does not re-anchor after a live language/direction switch",
   "severity": "P3", "step_ids": ["T3"],
   "repro": "While offline with the bubble showing, switch the top-bar language to العربية, then to 中文.",
   "expected": "The bubble follows the plane when the top bar mirrors",
   "actual": "In ar the plane moves to x=186 and the bubble stays at x=1162 (arrow 1019 px from the plane), over the sidebar brand and the Graphics subtab. A window resize re-anchors it. Back in zh/en it is left 986 px away on the left.",
   "evidence": f"{D}/T-T3-coach-ar.png; walk1.json T3.place. src/static/app-core.js:1017-1087: _placeCoach runs only on show and on window resize, with no oo:langchange listener."},
  {"title": "Task manager summary strip keeps the previous language after a live switch from a non-English locale",
   "severity": "P3", "step_ids": ["T5", "T8"],
   "repro": "In /tasks switch to العربية, then to 中文 (or back to English).",
   "expected": "The state label, metric labels and 'Live' in the new language at once, as the airplane title is",
   "actual": "After ar→zh: 'خامل', 'الذاكرة', 'الشبكة ↓', 'نشط', 'مباشر' on the Chinese page until the next poll (measured 2.3 s; up to 6 s idle, 15 s hidden). The same after zh→en (2.0 s). en→fr and fr→ar flip at once, because the i18n walker knows the English source.",
   "evidence": f"{D}/T-T5-tasks-while-offline-en-fr-ar-zh.png (zh panel); walk2.json T8.switches.*.samples. src/static/taskmanager.html:718 re-paints only paintAir on oo:langchange, and renderSummary runs only from refresh() (:589-610)."},
  {"title": "Task manager page overflows horizontally at 375 px",
   "severity": "P3", "step_ids": ["375px"],
   "repro": "Open /tasks at a 375 px viewport.",
   "expected": "scrollWidth - clientWidth = 0",
   "actual": "144 px of sideways page scroll. The Processes/Performance/Queue/Schedule/Sessions subtab row does not wrap or scroll in its own box; 'Schedule' ends at 428 px and 'Sessions' at 519 px.",
   "evidence": f"{D}/T-375-tasks-en.png; probe375.py output"}
 ],
 "not_measurable": [
  "T9: the per-process budget panel and /api/scheduler/activity process_budget. They need a running collection pass, which needs egress. Only the no-pass state (block absent, collect_perf null) was seen.",
  "T10: crawl_delay_deferred in /api/jobs/history and host_schedule.json. They need a corpus that has collected from a host declaring a Crawl-delay. Not observed on this corpus.",
  "Everything after a consent 'Go online' click (real collection). It was never clicked, per the sandbox rule.",
  "Q1132 model-weight digest values, Q1148's 100/hour non-loopback half, the third (AI-install egress window) airplane title, and the three i18n gates and behavioural tests. These are CI/operator items, not clicks.",
  "Whether this agent-run walk counts as Q1128's 'operator's own click-through' is a maintainer ruling. This walk is evidence, not closure.",
  "Known and not counted: the speed knob's 'KiB/s' vs Settings' 'kbps' (OPEN_QUEUE.md:697-712), seen in T6 in en/fr/ar/zh."
 ],
 "summary": ("The click-through clause does not close. Q1125 (coach buttons at equal weight in Ink, Paper, Solar and Mint, and in fr/ar/zh), Q1012's UI half (one gauge synced with the Settings slider, no consent popup, no per-download cap) and Q1148 (150/150 loopback calls allowed) all pass. "
             "Q1126 fails on its offline half. The /tasks page reads 'online' from /api/scheduler/activity, which never carries it. So in airplane mode the Task manager shows a hollow plane, 'Online — click to go offline…' and 'Idle', and after its own go-offline click it reverts to online at once (T5, T8). The online title and its live re-translation do work. "
             "T9 and T10 cannot be observed in the sandbox. The 375 px pass also fails on Home (a 71 px overflow that pushes a caveat off-screen) and on /tasks (144 px).")
}
json.dump(report, open(f"{D}/report.json", "w"), ensure_ascii=False, indent=1)
print("ok", len(report["steps"]), len(report["defects"]))
