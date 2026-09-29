# Claim workspace click-through, steps ④ and ⑥ — 2026-09-28 (S05-11 S2, gate 0.5 row K)

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`) against a real server started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1`, no proxy variables, on a data folder
`seed.py` prepared: S1's corpus, plus two articles naming a drought at Zermatt (the place
extractor's point) and one naming a flood in France (no point, so the gazetteer's stand-in city).
The flood's weather slice is held in the local cache; it is INVENTED and says so in its own
provenance. All hosts are `.invalid`.

**The walk goes offline on purpose and checks it.** A server started with `OO_NO_SCHEDULER=1`
boots ONLINE (the boot kill switch sits inside the same block as the scheduler), so the walk
engages airplane mode through `POST /api/system/network` and reads it back before the first page,
and the browser aborts every request that is not to the loopback server.

| Check | Result |
|---|---|
| ④ en | 2 offers: Zermatt (not held, button "Ask archive-api.open-meteo.com") and France (held, "Show the slice held on this machine"); each names the exact request URL and what it tells the host; the France offer says its point stands in for the country |
| The consent popup | Opened by "Ask …" with the reason and the new shadow line: *the point 46.0207, 7.7491 (for Zermatt) and the dates 2026-08-24 to 2026-09-03*; answered "Stay offline": **no POST** to the weather or network endpoints |
| The held slice | Drawn without the consent popup (it asks nothing); variables labelled "Daily precipitation (mm)", "Daily rain (mm)" |
| ⑥ en | Export saved `20260928-claim-trail-2f95a0ac.zip` (15 members, 7 articles, 1 weather slice); `scripts/verify_claim_trail.py` exit 0, **VERIFIED**; the page's "Check a bundle" says verified; a copy with `articles/4.json` edited says *Changed since it was signed: articles/4.json* |
| Arabic | `dir=rtl`; the offer slice and the export result survive the language switch; the consent shadow line in Arabic; the only Latin left in ④ is the source's name "Open-Meteo" |
| 375 px | No horizontal page scroll; no overlapping text |
| Whole walk | **0 page errors, 0 responses ≥ 400, 0 non-loopback requests**; airplane mode still on at the end |

`report.json` holds every value read; `seed.py` and `walk.py` reproduce it.

**Found and fixed by this walk, before it was recorded:**

- The chart headings showed raw variable names (`precipitation_sum`); they are labelled ×12 now,
  on the Home weather card too, which draws through the same function.
- The consent line said "a point near France" for a country, which hides that the host is sent
  the coordinates of the stand-in city. It now names the coordinates sent.
- The verify result listed the checker's English lines on the Arabic page; the server now sends
  a code and the file it names, and the page words them ×12.
- "corroboration/ 1 files": singular keys now.
- In Arabic the saved file name read out of order around the colon; it is isolated now.
- The two ④ buttons were drawn as ghost buttons that read as plain text; they are secondary
  buttons now.

Chromium-verified (remote sandbox) · awaiting human UX pass.
