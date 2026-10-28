## 2026-10-28 — a follow-on that leaves the shipped PR dishonest is not a follow-on

**What was found (#1616, R377 and R378).** R377 split OSM's markets fix into the `src` change now and the page as a follow-on. The full read of the PR then showed what the split shipped: after a Stop, the import-all status read «Imported X across N feeds» with an empty verdict box, so a partial load read as complete. The `src` side was correct and the page, left for later, made the user-visible answer false in exactly the case the PR exists for.

**The rule.** When a change moves what a screen can say (here: unasked feeds are no longer counted as failures, so the verdict box can be empty on a Stop), the line that tells the user what was NOT done ships in the same PR, even when the mechanism and the page have different owners. A follow-on is for what the PR leaves unchanged and still honest, never for the sentence that keeps it honest. The one line used an existing key in all 12 locales («{n} not fetched (airplane mode)»), so the fold cost no new string.

**How it was settled.** The line folded into #1616 under R307 (`app-markets.js` is OSM's), with one R222 delta read of the `src` fold, which was clean.
