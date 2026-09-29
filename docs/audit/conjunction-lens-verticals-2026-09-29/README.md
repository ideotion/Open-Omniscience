# The Conjunction Lens across verticals, click-through — 2026-09-29 (S05-11 S3, gate 0.5 row K)

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`) against a real server started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1`, no proxy variables, on a data folder `seed.py`
prepared: eleven invented articles over three verticals carrying the same eight keywords (six press
articles from two `.invalid` newsrooms, three Wikipedia pages on `en.wikipedia.org`, two laws on
`law.fr.local`), four of them naming Zermatt, which is a Place.

**The walk goes offline on purpose and checks it.** A server started with `OO_NO_SCHEDULER=1` boots
ONLINE, so the walk engages airplane mode through `POST /api/system/network` and reads it back before
the first page, and the browser aborts every request that is not to the loopback server.

| Check | Result |
|---|---|
| Analysis window, whole corpus | `drought ∩ hydropower` · 3 articles; "Read in: The whole corpus · 11 articles"; each term's n (6, 5); the three panels drawn: the clustering articles (titles linking to the local reader), the weekly chart, the comparison |
| Scope switched to Law in place | The same combination re-read: "Read in: Law · 2 articles", each term's n within law (1, 1), an honest empty set |
| The comparison | `drought` against `glacier`, whole corpus: a table of A, B and A − B (n=6 and n=5 shown), the defining terms left out, the caveat under it |
| Living sources → Law → «Combine keywords in law» | The dialog opens with Law selected; `drought ∩ water permit` · 1 article, the law named in the cluster list |
| The near search | «Find them within 10 words of each other» closed the dialog, opened Search with `NEAR("drought" "water permit", 10)` |
| Living sources → Wikipedia → «Combine keywords in Wikipedia» | The dialog opens with Wikipedia selected; `glacier ∪ river` · 3 of the 3 Wikipedia pages |
| Place card → «Combine keywords in these articles» | The card closes, the lens opens fixed on "The articles naming Zermatt · 4 articles"; `drought ∩ reservoir` · 2; «Open 2 article(s) as a corpus» opens the analysis window labelled with the expression |
| Arabic | `dir=rtl`; no Latin left in the lens but the data (keywords, titles, Zermatt); no `undefined`/`NaN`/`{placeholder}` |
| 375 px, Arabic | No horizontal page scroll; the dialog inside the viewport; no overlapping text |
| Whole walk | **0 page errors, 0 non-loopback requests**; airplane mode still on at the end. The only responses ≥ 400 are `/static/osm_admin0.json` and `osm_admin1.json` (404), the border files row E leaves to the operator's build, which every map-loading page asks for |

`report.json` holds every value read; `seed.py` and `walk.py` reproduce it (`OO_WALK_BASE`, `OO_WALK_OUT`).

**Found and fixed by this walk, before it was recorded:**

- A leftover flex wrapper laid the lens out sideways: the scope, the keyword field and the whole
  result sat side by side, and at 375 px the result ran under the keyword field. The source-pinned
  tests all passed; only the page showed it.
- "N more in the corpus it opens" counted from the 50 rows the intensity view returns, not from the
  set; it counts from the set now.
- The overlap probe counted text scrolled out of the dialog's body as overlapping the Close button;
  it now skips text outside a scrolling ancestor.

**Seen and left:** a chart with ONE point labels its only tick with a time of day (`07-20 00:00`);
that is the shared chart toolkit's single-point axis, not this lens.

Chromium-verified (remote sandbox) · awaiting human UX pass.
