# The dossier seed, click-through — 2026-09-29 (S05-11 S4, gate 0.5 row K)

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`) against a real server started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1`, no proxy variables, on a data folder `seed.py`
prepared: one invented item, "Zermatt" under the synthetic id `Q999999101`, reached by all three
routes (two press articles naming it as a place, a French Wikipedia page carrying it as a keyword,
a law naming its municipal council as an organisation), a Wikipedia lane page and an OpenStreetMap
lane object carrying it; and a name, "Matter", that two synthetic items share. The rings are the
data folder's own local ring file.

**The walk goes offline on purpose and checks it.** It engages airplane mode through
`POST /api/system/network` and reads it back before the first page, and the browser aborts every
request that is not to the loopback server.

| Check | Result |
|---|---|
| Place card → «Open the dossier» | The card closes and the dossier opens titled "Zermatt" with its id |
| The passport (A-1), one line under the title | `4 articles · 4 sources · 2 countries · 2 languages · 2026-06-03 – 2026-08-20 (1 without a country · 1 without a language)`, visible by default; the method and the per-country and per-language counts on hover |
| How articles join | A person or organisation they mention: 1 · A keyword that is a name of this item: 1 · A place they mention: 2, each with what it matched on |
| Joined on this page | News and web 2 · Wikipedia 1 corpus article plus the lane's page · Law 1 · Places: Zermatt, mentioned in 2 articles · Map: the lane's object tagged with the item |
| Not joined yet | Markets, Agenda and Tracked law texts, each with why |
| The Places row's name | Opens the place card again |
| Analysis window → When/Where/Who | The Who chip "Zermatt" carries the dossier button; "Matter", which two items share, carries none; the button opens the same dossier |
| «Open these 4 articles in the analysis window» | The dossier closes; the window opens labelled "Zermatt · Q999999101" |
| Arabic | `dir=rtl`; the title is the item's Arabic label (تسيرمات); the date span kept in reading order inside the right-to-left line; no `undefined`/`NaN`/`{placeholder}` |
| 375 px, Arabic | No horizontal page scroll; the dialog inside the viewport; no overlapping text |
| Whole walk | **0 page errors, 0 responses ≥ 400, 0 non-loopback requests**; airplane mode still on at the end |

`report.json` holds every value read; `seed.py` and `walk.py` reproduce it (`OO_WALK_BASE`, `OO_WALK_OUT`).

**Found and fixed by this walk, before it was recorded:**

- In Arabic, the ISO date span was reordered around its hyphens by the right-to-left line. It is
  its own isolated left-to-right run now.
- In Arabic, the bullets of the lists inside the rails table sat at the far side of the cell from
  their text. Those lists have no bullets, and the cells align to the start.
- The Places row drew the Place's name as a large filled button. It is a link-style button now.
- The news row repeated its only channel ("Press and web 2" beside "2 articles"); the split is
  shown only when there is more than one channel.
- The map row printed the lane's internal kind code ("place"); it shows the object and its
  country only.

**Seen and left:** the Place's kind ("village") is OpenStreetMap's own tag value, shown as data in
every language, as the place card shows it.

Chromium-verified (remote sandbox) · awaiting human UX pass.
