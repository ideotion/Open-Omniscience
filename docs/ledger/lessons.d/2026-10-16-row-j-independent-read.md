## 2026-10-16 — A RATIO MUST COUNT ONE UNIT ON BOTH SIDES; A "DONE" LIST IS NOT A "SUCCEEDED" LIST; A SCAN FOR A SHAPE MISSES THE OTHER SHAPE

An independent read of row J's J1+J2 head found no data loss and these defects, each now fixed with a test that fails without the fix:

(1) **Moving a numerator to outlets while the denominator stayed per-source-row made the language-ubiquity ratio depend on which sibling feed was oldest.** The numerator counted outlets carrying a term in any feed; the denominator counted each outlet once, in its oldest feed's language, so a Spanish service of an English-first outlet inflated the ratio and hid a real story (3 of 8 read as 3 of 5). `outlets_per_language` counts distinct `(language, outlet)` pairs, so both sides are one unit. **Rule: when you change what a count counts, change every ratio it appears in.**

(2) **`done_sources` also holds a failed enumeration and a backfill cut short, so "a sibling is in done" did not mean "the archive was read".** The sibling skip now reads `completed_outlets`, written only when a run reached the end of its URLs.

(3) **The default-deny scan found `distinct(x.source_id)` and sets, and was blind to `query(x.source_id).distinct()` and to counts keyed on a source NAME.** It now sees the method form (13 more sites, each classified, nine as `NOT_A_SOURCE_COUNT` with a reason), and the Observatory's breadth, disputed chronology and framing split were converted. A count keyed on a display name is still invisible to it (stated in its docstring); the leads chips say they count feeds.

(4) **A table rebuild that copies only the columns the old and new table share drops every other column silently**; it now refuses and names them (local data never gives way). A later migration that adds a `sources` column must check the column exists first, because the rebuild builds the new table from the current model. **(5)** The additive column and backfill must run BEFORE any refusal, or a refused store fails every query on its table. **(6)** A caller that may create a second feed of a domain asks `composite_key_active`: the merge refuses a multi-feed backup by name, and the seeder holds the sibling back and counts it.

Measured, not fixed: the outlet join made a synthetic story-propagation candidate query about 55% slower (4.8 s to 7.5 s, 2M mentions, 7k sources); no SQL-only alternative was faster. Judgment call left to the coordinator, pinned by a test: an old domain-keyed backup whose one feed matches none of a multi-feed local outlet lands as an extra sibling.
