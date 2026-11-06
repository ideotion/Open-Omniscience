## 2026-11-06 — a scroll box inside a grid track still sets the track's width unless it opts out (OSM trends and profile panels)

**What was found.**

`overflow:auto` on a wrapper makes the table scroll inside it, but the wrapper's MIN-CONTENT contribution to its parent is still the table's width. The World map tab is a CSS grid whose track is `auto`-sized, so one 17-column table (contact channels, 8 services x gained/lost) widened the track, then every panel in the tab: the section measured 1369 px in a 990 px column and the page scrolled sideways at 1280 px. At 375 px it did not show, because the phone layout is a different box. A string test of the markup cannot see this; a measurement can: `document.documentElement.scrollWidth > innerWidth` after opening each tab, and the section's own width against its neighbours'.

The fix is on the scroll box, not the table: `width:0; min-width:100%` takes the table out of the parent's sizing and leaves the box full width. The node test pins the style on every box the renderer makes, and was seen to fail on the old markup.

Also found by walking, and invisible to the node tests: a date in a table cell broke at its hyphens at phone width ("2026-" over "10-02"), and under a right-to-left page `ooIsoDate` wraps the date in direction isolates (U+2068/2069), so a check that matches `^\d{4}-` misses exactly the pages it was written for.
