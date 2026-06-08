# Known gaps — the coverage ledger

> The mission is "understand the world as it really is." A tool that takes that
> seriously must be honest about **what it does not see**. This ledger names our
> blind spots and labels each one **voluntary** (a deliberate scope / ethics /
> resource choice) or **involuntary** (a limit we don't fully control — or don't
> yet measure). Turning unknown unknowns into *known* unknowns is the point.
>
> A smaller corpus whose gaps are documented is more trustworthy than a huge one
> whose biases are hidden. The count of sources is a vanity metric; **this page is
> the real one.**

---

## How to read this

- **Voluntary** = we chose to exclude it. The right response is to *state it*, not
  hide it. Reversible if priorities change.
- **Involuntary** = we can't fully capture it (medium, access, language, or the
  limits of the registries we enumerate from). The right response is to *measure
  its size* so the user can weigh it.

Where a rule is enforced in code, the location is cited so the claim is auditable.

---

## Voluntary exclusions (deliberate)

### Images & all visual/binary media — *excluded by design*
**We do not collect, download, store, or analyse images, video, or audio.** Only
**text and structured metadata** are ingested. A record may reference an image
*URL* (a short string), but the binary is never fetched or stored.

- **Why (owner's decision):** (1) **storage** — this is a single-user, offline-first
  tool that must fit on one machine the owner can afford; media binaries would
  balloon the database. (2) **Honesty at scale** — credible image work (provenance,
  manipulation/deepfake detection, reverse search) is *not feasible to do well at
  scale here*, and a half-working "image analysis" feature would violate the
  project's core promise (nothing faked, nothing guessed). Better to not pretend.
- **Enforced today:** the crawler skips image/audio/video/binary extensions —
  `_SKIP_SUFFIXES` in `src/ingest/crawl.py` (`.jpg .jpeg .png .gif .svg .webp .ico
  .mp3 .mp4 .avi .mov …`). RSS/article extraction keeps text; any `og:image` is at
  most a URL string, never a download.
- **If ever wanted:** image handling would be a deliberate, clearly-bounded
  **opt-in** (with its own storage budget), never a silent default.

### Social media & messaging platforms — *excluded for now*
X/Twitter, Facebook/Instagram/Threads, TikTok, YouTube, Reddit, Telegram,
WhatsApp, etc. are dropped. Enforced: `SOCIAL_HOSTS` in `src/catalog/normalize.py`.
Rationale: ToS/scraping friction, ethics, and signal-to-noise. *Cost to note:* a
lot of breaking news and primary-source material now originates there.

### Paywalled content — *respected, not bypassed*
We do not defeat paywalls or logins. Some major outlets are therefore captured
only by headline/teaser, not full text.

### robots.txt-disallowed paths — *fail-closed*
If a site disallows crawling, we don't fetch it (per `ETHICS.md`). A deliberate
trade of coverage for legitimacy.

### Broadcast audio/video & print-only outlets — *out of scope*
No speech-to-text of TV/radio; outlets with no web presence can't be reached at
all. (Overlaps the images/media exclusion above.)

---

## Involuntary gaps (blind spots we should *measure*)

- **Register-bounded enumeration.** We can only seed what some registry lists.
  Wikidata (our generator's backbone) skews Western/English/large-language, so the
  catalog inherits that skew. We can't miss what no register names.
- **Language & script under-coverage.** Smaller languages and non-Latin scripts are
  thinner — both in the registries and in RSS availability.
- **Censored / exile media.** In repressive environments the real reporting may live
  only on blocked, exiled, or social/messaging channels we exclude.
- **The unknown unknowns.** Sources that appear in *none* of the registries we use.

### How we plan to size the gap (roadmap)
Honest measurement, not a bigger number:
1. **Triangulate registries** — cross-reference Wikidata against GDELT / Media Cloud
   / national press directories / MBFC / AllSides; the *non-overlap* is the gap.
   Tag each source with the register that found it (provenance).
2. **Capture–recapture estimate** — if register A has Nₐ, B has N_b, overlapping in
   N_ab, estimated total (incl. never-seen) ≈ Nₐ·N_b / N_ab. This estimates the dark
   matter: "we hold Y; estimated unseen ≈ Z."
3. **Real denominators** — replace the current "country has ≥1 source = covered"
   measure (`src/catalog/coverage.py`) with coverage *ratios* per country ×
   language × medium × political lean, and surface them in the World-coverage view.

---

## Status at a glance

| Gap | Type | Enforced in code? |
|---|---|---|
| Images / video / audio / binaries | Voluntary | ✅ `crawl.py` `_SKIP_SUFFIXES` |
| Social media & messaging | Voluntary | ✅ `normalize.py` `SOCIAL_HOSTS` |
| Paywalls | Voluntary | ✅ fetcher respects them |
| robots.txt-disallowed | Voluntary | ✅ fail-closed fetcher |
| Print-only / broadcast | Voluntary | ✅ (nothing fetches them) |
| Register skew / languages | Involuntary | ⏳ measurement planned |
| Unknown unknowns | Involuntary | ⏳ capture–recapture planned |

*This is a living document. When scope changes, update the ledger in the same
commit — the limits ship with the product.*
