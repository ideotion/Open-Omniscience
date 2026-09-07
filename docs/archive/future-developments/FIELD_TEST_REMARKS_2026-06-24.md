> **Archived 2026-09-07 from `docs/FUTURE_DEVELOPMENTS.md`, verbatim and unedited.** It is an embedded
> HISTORICAL LEDGER — the maintainer's verbatim remarks from a live ~60K-article test — and it was displacing the design-intent material that document exists
> for. Nothing was condensed or dropped in the move. Its still-open items live on the live boards
> (`CLAUDE.md`'s Open queue and `docs/ROADMAP.md`); read this file as a record of what was observed and
> when, not as a status.

## FIELD-TEST REMARKS 2026-06-24 (maintainer; PARKED — the diagnostics fix comes first)

> Captured VERBATIM from a live test of the ~60K-article corpus. These are FEATURE / UX
> directions to address LATER. Maintainer instruction this session: *"capture all my
> preliminary remarks into future developments, we'll address them later on, and focus on
> the debugging now"* + *"we just want the diagnostics to be resolved for now."* So nothing
> here is built yet; the log-DIAGNOSED bugs are the active work (CLAUDE.md shipped-log /
> queue 2026-06-24). Two of the remarks (7, 8) are ALSO diagnosed performance bugs and are
> being fixed, not merely parked — noted inline.

**A. Local LLM / Ollama**
1. *"Add an ollama installer into the settings / AI subtab, with hardware based scenarios
   for user messages and model download choice. We want to prioritize Mistral open-models
   (mistral-small:latest, mistral:7b)."*
   — Builds on the existing read-only Settings → Models subtab (pull/remove shipped; the
   binary-installer half is the open Q7=B work). Add hardware-tiered scenario messaging + a
   guided model-download choice; lead the catalog with `mistral-small:latest` + `mistral:7b`.

**B. ONE unified import / export / backup section**
2. *"Merge all import types and all export / backup types to have just a single import /
   export (or backup) section and user interface ; for each (import and export) there would
   be a follow-up user interaction (like a pop-up ?) to gather necessary information such as
   import / export options."*
5. *"Can we fuse both types of newsletter import in the same coherent way we will do for
   import/export backups ? one UI with pop-up with options ending up with a file/folder
   selection ?"*
6. *"All import / export should be a visually appealing experience, we should see a progress
   bar very clearly. If it could be possible, show analytics such as live amount of data
   imported/exported."*
   — **Build on the NEW backup direction (read PR #449/#450, 2026-06-24):** the backup layer
   is mid-migration to **OOENC2 streaming volumes** (`src/safety/crypto.py`
   `encrypt_file`/`decrypt_file`; `src/backup/volumes.py` = <600 MB independently-authenticated
   volumes + a signed manifest; Reed–Solomon parity = slice 2; wiring into create/restore =
   slice 1b). The unified UI MUST sit on the OOENC2/volumes path (NOT the legacy OOENC1 2 GiB
   path) and reuse the folder-backup + folder-import job progress for the "clear progress bar +
   live data-volume readout" ask. Fuse the TWO newsletter import paths (the small-file upload
   `POST /api/newsletters/import` + the server-side folder job) behind one pop-up → file/folder
   selection.

**C. Performance / freezes at scale (ALSO diagnosed — being fixed, not just parked)**
7. *"At 60K articles, the home tab seems to not launch \"Loading the briefing…\" indefinitely.
   If there's a lot going on in the background, we should show it to the user, same as import
   export, there should be a pleasing progress bar."*
8. *"All insights are freezed, content analysis either takes too long or is broken. When
   searching for a keyword, the analysis screen says \"Loading...\" indefinitely."*
   — Root-caused 2026-06-24: the briefing recompute + the grouped keyword aggregation
   (`top_terms(group=True)` measured **17 s for 50 rows** on the live 61,635-article /
   932,031-keyword corpus) run SYNCHRONOUSLY on the request with no background offload / cache /
   progress. Fix = background warm + cache + statement deadline + a real progress UI (the
   shared "pleasing progress bar" deliverable). In the debug queue.

**D. Search → new analysis window**
9. *"Searching for a term then clicking enter does not open a new browser window / tab. It
   should."*
   — Ties to the analysis-window-per-query work (spawned, named, closeable tabs).

**E. Library world map**
10. *"The world coverage in the \"library\" tab should be a world map with per country amount
    of articles. All \"no country\" articles should be shown with a circular graph with per
    language quantity, language names should be written fully."*
    — Reuse `ooMap` (choropleth) for per-country article counts; a per-language donut for the
    uncountried bucket, FULL language names via `ooLangName`/CLDR.

**F. Settings layout**
11. *"i Settings, both Appearance and GUIs should be assembled together into one, unified
    single subtab named Graphics"*
12. *"In each of the Settings subtabs, there's a top box with \"Settings / Everything that
    shapes how the app looks and behaves on this machine. Pick a section — your choices stay
    local.\" Remove it everywhere, it will bring all content up and increase display space."*

**G. AI prompt localization (added 2026-06-24)**
13. *"The prompts in the AI setting tab don't translate while changing language. Two points
    there: 1) they should, and 2) verify that the AI engine does use the translated prompts.
    Synthesis, summaries and translation should be made in the UI language."*
    — TWO asks: (a) the editable prompt textareas in Settings → AI (the summary / translate /
    synthesis / keyword system prompts) must re-render in the active UI language on a language
    switch; (b) VERIFY the engine actually applies the translated prompt AND emits output in
    the UI language. Context: an `output_language` / `_NATIVE_DIRECTIVE` mechanism already
    forces the OUTPUT language for summary/synthesis/bulk (shipped) — but a PRIOR decision
    deliberately kept the English prompt BODY (translating multi-sentence prompts risked
    degrading a weak local model's compliance). This remark re-opens that: localize the prompt
    UI, and re-confirm end-to-end that synthesis/summaries/translation come out in the UI
    language. Reconcile with the body-translation trade-off when built.

**H. Chrome — status bar + left tab bar (added 2026-06-24)**
14. *"The status bar is currently transparent. As a consequence, we can see content when
    scrolling down. Taskbar should have the same background color as the left tab bar."*
    — Give the top status bar / taskbar an opaque background matching the left sidebar's
    background colour (theme-aware across all 17 themes) so scrolled content never shows
    through it.
15. *"Clicking on the empty space of the left tab bar should minimize / maximize it. Add a
    maximize button for clarity when the bar is minimized, equivalent to the existing minimize
    button that is shown when the bar is maximized."*
    — Make the sidebar's empty area a click target that toggles collapse/expand, and ensure a
    clearly-visible expand (maximize) affordance in the collapsed rail mirroring the existing
    collapse button. Context: the rail already ships two CSS-toggled buttons (`#sb-collapse`
    when expanded / `#sb-expand` when collapsed); this asks for the empty-space click-toggle +
    making the expand affordance as clear as the collapse one.

**I. Library tab = the central view of everything downloaded + extrapolated (added 2026-06-24)**
16. *"The library tab should show statistics about everything downloaded and about secondary
    metadata. It should show maps, wikipedia, amount of summaries / translations / synthesis, as
    well as indices, laws, and so forth. This should be the central view for everything downloaded
    and everything extrapolated."*
    — Make Library the at-a-glance DASHBOARD for the whole local corpus + its derived layers:
    counts + sizes for downloaded MAPS (OSM regions) and WIKIPEDIA dumps; the AI artifacts
    (summaries / translations / synthesis counts from `article_analyses`); market INDICES +
    commodities; LAW documents/revisions; official statistics; events/agenda; etc. — i.e.
    EVERYTHING downloaded (the public/raw layer) AND everything EXTRAPOLATED (the derived /
    secondary-metadata layer). Pairs with remark 10 (the per-country world map + per-language
    donut for uncountried articles) as the same tab's content. Most counters already exist (the
    database-stats endpoint + the per-domain download managers); this is a presentation /
    aggregation surface — honest counts only, never a score.
