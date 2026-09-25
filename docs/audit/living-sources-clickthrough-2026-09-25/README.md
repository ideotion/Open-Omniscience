# Living sources click-through — 2026-09-25 (S04-08 S6, gate row O)

Chromium (Playwright, `/opt/pw-browsers/chromium`) against two real servers started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0` and no proxy variables in their environment:

- port 8745 on a data folder `seed.py` prepared: a Wikipedia lane with four changes on two
  followed pages (one with its text and a diff, one only counted, one of a kind the lane does
  not know, one creation), one change on a page nobody follows, two feed cursors and an open
  gap; two tracked pages (one never checked); two law documents (a flagged change and a
  re-check with no change); three map regions (done, paused by airplane mode, failed);
- port 8746 on an EMPTY data folder, where nothing has ever run.

Both boot in airplane mode and nothing went online: the view reads loopback only. The tab was
opened through the real sidebar, its sources through the real subtabs (invariant #18), the
diff through its own button, a tracked page through its own button, and the language through
the real top-bar switcher (invariant #15). The deep link the article reader carries
(`/?wikitc=<page id>`) was followed once.

| View | Result |
|---|---|
| Wikipedia, en / fr / ar | Pages followed 2; changes reported 4; text stored for **2 of 4**; changes on pages you do not follow 1; complete through the feed that is BEHIND (06:30, not the current one's 12:28); open gaps 1. Tracked pages 2, never checked 1, newest and oldest check as UTC dates. Storage: Settings → Storage's own cells without the budget input |
| The timeline | Newest first, `Showing 4 of 4 changes`. The counted change reads `Counted only: its text was not stored.` with no diff button; the unknown kind shows as `log`, verbatim, with a hover saying so; the creation says there was no earlier text to compare with |
| The stored diff | Opened in place through `Show diff`; `<b>` in the stored text drawn as text, not markup; the note under it says it is the diff stored when the change arrived, not a live re-diff |
| Tracked changes | The former dialog, now a section of the tab: the page's two revisions, the flag, the method line in the visible caveat style |
| Law | Documents 2, jurisdictions 2, changes in 30 days **1** (the re-check with no byte change is not counted), flagged 1; the tracker's own caveat visible above the list; each change links to the LOCAL stored copy (`/api/law/documents/1/view`) and to nothing outside |
| Maps | Regions 3, downloaded 1, paused 1, **failed 1**; the paused row says airplane mode paused it and the failed row gives the error, in the task manager's own words; the date of the map data reads `Not recorded` |
| Deep link `/?wikitc=<id>` | Lands on the Living sources tab with the page's history open; no dialog exists |
| 375 px, en | No horizontal page scroll (`scrollWidth - clientWidth = 0`); the figures stack in one column |
| Fresh folder | The stream reads `Not run yet` and draws no figure; the timeline says the stream has not run and how to turn it on; law and maps say nothing is tracked or downloaded yet. **The reads did not create the lane file** (`size_state: absent` afterwards) |

`report.json` holds every value read; `seed.py` and `walk.py` reproduce it. **0 page errors,
and no `undefined`, `null` or `NaN` anywhere in the tab**, in all three languages and on the
fresh folder. The only errors were `GET /api/briefing` answering 500, below.

**Found and fixed by this walk, before it was recorded:**

- **In Arabic, every diff line was drawn backwards.** `+An added line` read `An added line+`,
  and a size change of `-3000` read `3000-`, in the new timeline and in the tracked-changes
  view it absorbed (that view had the same fault as a dialog). Each diff line now takes its
  direction from its own text (`unicode-bidi: plaintext`) and the size change is isolated
  left to right (`tests/test_living_sources.py::test_diff_lines_take_their_direction_from_their_OWN_text`).
- **"Pages you track" was printed twice**, as the group's title and as its first label. The
  label now reads `Pages` (a node test pins that the title appears once).
- **French and others could not agree a count with its noun.** `{added} lines added,
  {removed} removed` gave `2 lignes ajoutées, 1 supprimées`. It is now `Lines added:
  {added}, removed: {removed}`, which needs no plural in any of the twelve languages.
- **"Last change recorded" was later than the newest row of the timeline** (12:28 against
  12:25), because it counts the stream's changes on every page and the timeline shows only
  followed ones. Both are right; the figure's hover now says it covers every page.

**Found by the tests before the walk, also fixed:** the map count read failures under the
word `failed`, which the download manager never writes (it writes `error`), so every failed
download would have counted as zero; the diff route read the revision after its session
had closed, which raised on the first real request; and the stream's language and the law
row's jurisdiction were printed raw, which the repository's Q302 guard refused (they now go
through the display helpers: `eng` and `FRA` on screen, the name in the hover). All three are
pinned (`test_the_map_states_are_the_WORDS_THE_MANAGER_WRITES`, `test_a_long_diff_is_CUT_and_says_so`,
`test_alpha3_display_surfaces.py`).

**Handed to another thread:** `GET /api/briefing` answers 500 on this build when there is at
least one card (`src/api/briefing.py:74`), which is why the fresh folder, with none, showed no
error. It is fixed in its own thread (PR #1181).

**Seen, not this slice's to change:** the law and map rows of the Storage group read `Not built
yet`, beside a law tracker holding two documents. That is Settings → Storage's own answer: those
lanes have no file yet, and the documents live in the corpus, whose row counts them. The region
name `Antarctica` has no French key (Asia and Africa have); it is the OpenStreetMap catalogue's
string, shared with Settings. Flag codes such as `large-removal` are shown as stored, as the Law
tab shows them.

**Still owed:** the maintainer's click-through (Q1128 = a).
