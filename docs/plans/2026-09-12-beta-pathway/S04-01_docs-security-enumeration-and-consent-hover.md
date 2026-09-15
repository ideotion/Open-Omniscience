# S04-01 — `docs/SECURITY.md` enumerates every host; the consent hover lists them per lane · 0.4, `RELEASE_0.4_GATE.md` row H

> **Scope:** `docs/SECURITY.md` (the "full set of endpoints the app can reach" section), the `#net-consent`
> dialog in `src/static/index.html`, `ensureOnline` in `src/static/app-core.js`, `src/static/locales/*.json`,
> one new repo test beside `tests/test_network_consent.py`. Must NOT: add a host, change any fetch path, touch
> the kill switch or the SSRF guard, or build lanes (row O, `S04-08`).
> **Implements:** Q1001, Q1002.
> **Gated on:** nothing pending. The per-lane "which lanes are on" body composes with `S04-08`; this slice
> ships the hook against the surfaces that exist today.
> **Sequencing:** the docs half first, as its own PR (Q1001 "now"); the hover + the test next; both before any
> brief that adds a host (`S04-06`, `S04-08`, `S04-09`, `S04-10`, `S05-04`) — those extend the list and the
> hover in the same diff.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
section is §11 (cross-cutting); the CLAUDE.md non-negotiables on consent (invariant #14, #14e, #14f) apply.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1001** — **(a)** «Complete it now as a docs-only PR; from then on every PR adding a host adds it there
  and to the consent popup's hover in the same diff (a repo test greps the fetch sites against the list).»
- **Q1002** — **(a)** «The one popup stays; its hover lists, per lane, the hosts it will contact (Wikimedia
  ×4, the OSM mirrors, the law authorities of the countries chosen); the popup's body names the lanes that are
  on.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §11 context (VERIFIED): "`docs/SECURITY.md` §"the full set of endpoints the app can reach"
  (re-verified 2026-09-08) **omits** the Wikidata Query Service the default-on discovery ride-along reaches
  (`discover.py:36–41`), the Wikipedia Action API, ORES, the Wikimedia dumps host and the OSM mirrors."
- grep-verified in this brief: `docs/SECURITY.md:23–63` is that list (lead-in at `:25`: "the full set of
  endpoints the app can reach beyond article ingestion, re-verified against the current tree (last checked
  2026-09-08)"): DuckDuckGo, Open-Meteo, the official-statistics endpoints, the GitHub releases API, Ollama's
  own pulls, USGS + GDACS, IMAP/POP3, OpenTimestamps.
- grep-verified in this brief: `grep -rhoE "https?://[A-Za-z0-9._-]+" src/ --include=*.py | sort | uniq -c`
  — hosts the section omits, and where they live: `query.wikidata.org` (`src/catalog/wikidata.py:23`
  `WDQS_ENDPOINT`, queried by `src/catalog/discover.py:30–45` through `guarded_session`),
  `www.wikidata.org/w/api.php` (`src/catalog/wikidata_enrich.py:33`), `https://{code}.wikipedia.org/w/api.php`
  (`src/wiki/mediawiki.py:26`), `ores.wikimedia.org/v3/scores` (`src/wiki/ores.py:22`), `dumps.wikimedia.org`
  (`src/wiki/dumps.py:140`), `download.geofabrik.de` and `planet.openstreetmap.org`
  (`src/geo/osm_downloads.py:61–62`), `huggingface.co` (`src/llm/weights_pin.py:30`,
  `src/llm/vllm_lifecycle.py:241`), `publicsuffix.org` (`src/catalog/publicsuffix.py:63` — a comment; whether
  it is a runtime fetch or a bundled list is for the session to read). Display and licence literals
  (`www.gnu.org` ×27, `ollama.com` ×10, `github.com`, `example.com` fixtures) are not fetch sites.
- grep-verified: no test names `SECURITY.md` (`grep -rln "SECURITY.md" tests/` → none). The ratchet family the
  new test joins, in `tests/test_network_consent.py`: `_ALLOWED_HTTP_IMPORTERS` (`:100`),
  `test_no_new_socket_importers` (`:112`), `_ALLOWED_SOCKET_IMPORTERS` (`:153`),
  `test_no_new_socket_capable_importers` (`:184`), `test_every_socket_importer_allowance_states_a_reason`
  (`:211`) — every allowance states a reason.
- grep-verified: the popup is `<dialog id="net-consent">` (`src/static/index.html:3133–3149`): a reason slot
  (`#net-consent-reason`), the local interfaces (`#net-consent-ifaces`, filled from the loopback
  `/api/system/interfaces`), two hints, "Stay offline" / "Go online" — and NO `title` attribute anywhere in it
  (no hover today). It is opened only by `ensureOnline(reason, opts)` (`src/static/app-core.js:787–815`);
  `_postGoOnline` stays the ONE place that POSTs `/api/system/network` (invariant #14).
- grep-verified: the fetch entry points a test greps from: `src/safety/fetcher.py:154 guarded_session`,
  `src/ingest/__init__.py:529 class EthicalFetcher`, `:1185 _guarded_redirect_get`;
  `src/custody/timestamp.py:40 DEFAULT_CALENDARS` (the OTS hosts, already listed).
- The hover mechanism is invariant #17 (`#oo-tip`, a translated `title`); the i18n ratchets sit at
  `ci.yml:191` `--max-untranslatable 470` and `:209` `--max-unkeyed-t-calls 231` (grep-verified; zero slack).
- Lanes as a first-class object arrive with row O (`S04-08`: "lanes replace the scheduler mode"); today the
  on/off facts are scheduler settings (`src/scheduler/settings.py`, `PUT /api/scheduler/config` — the
  SECURITY.md hazards entry names them).

## 3. Slices — what to build, in order

### S1 — The enumeration (docs-only draft PR)
- **What:** rewrite the SECURITY.md section so it names EVERY host `src/` can reach, grouped by the lane it
  will belong to: press collection (the enabled sources' own domains — a class, never enumerable); Wikipedia /
  Wikimedia (the per-edition Action API, `www.wikidata.org`, WDQS, ORES, dumps); OSM (Geofabrik, planet); laws
  (the authorities' hosts carried by `configs/legal_sources*.yml`, a class today); AI (the GitHub releases
  API, `ollama.com`, `huggingface.co`); statistics; hazards; mail; OTS; Open-Meteo; DuckDuckGo. Each entry
  carries its trigger (click / opt-out setting / default-on ride-along), its module:line, and — where a host
  is reached outside the ethical fetcher, as the list already states for mail and OTS — the transport rule
  (Q1014: never a silent Tor → clearnet fallback). Keep the "last checked <date>" convention.
- **Why (ruling):** Q1001 = a "Complete it now as a docs-only PR".
- **Acceptance:** the section, with the grep command that produced it quoted in the PR body.
- **May not decide:** which of the tree's five Wikimedia-operated hosts the sheet's "Wikimedia ×4" counts
  (§6).

### S2 — The repo test (Q1001's parenthesis)
- **What:** a test beside `test_network_consent.py` that extracts host literals from `src/` — the `https?://`
  literals AND f-string hosts such as `f"https://{code}.wikipedia.org/w/api.php"` — and asserts each is named
  in the SECURITY.md section; an allowance dict for non-fetch literals, each entry stating WHY (the
  `_ALLOWED_SOCKET_IMPORTERS` shape). Mutation: add `https://example.invalid/` to a fetch module and the test
  must redden by name; restore.
- **Why (ruling):** Q1001 = a "(a repo test greps the fetch sites against the list)".
- **Acceptance:** the test green on the tree; the mutation record in the PR body.
- **May not decide:** nothing.

### S3 — The hover and the body (Q1002)
- **What:** `#net-consent` gains a translated `title` (rendered by `#oo-tip`) listing, per lane, the hosts
  that lane will contact — the same list as SECURITY.md (one source of truth is a design choice, not a ruling;
  say why in the PR). The body names the lanes that are ON: today read from the scheduler settings; from
  `S04-08` on, from the lane registry — the seam is ONE function answering "which lanes are on", nothing else
  changes. The press entry reads "the domains of your enabled sources" (a class); the law entry renders the
  countries the law-sources config carries today. Every string ×12 (ar is RTL); the existing hint that the
  public IP is never checked stays visible — caveats are never moved into the hover.
- **Why (ruling):** Q1002 = a; invariant #14 (one popup, one `ensureOnline`); invariant #17 (the hover).
- **Acceptance:** the Chromium click-through record of the popup and its hover (Q1128 = a) — en, ar, fr.
- **May not decide:** what a "lane" is before `S04-08` lands (§6).

### S4 — The same-diff rule, enforced both ways
- **What:** the section head states "a PR that adds a host adds it here and to the consent hover in the same
  diff"; the S2 test gains a second assertion — every host the section names appears in the hover's list — so
  the two cannot drift apart.
- **Why (ruling):** Q1001 = a "from then on every PR adding a host adds it there and to the consent popup's
  hover in the same diff".
- **Acceptance:** the second assertion, mutation-checked (drop one host from the hover → red by name).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the new
test with its two mutations; `node --check` on `app-core.js` and every touched `<script>` block; the three
i18n gates for every new string (the ratchet numbers read from `ci.yml`); the whole-tree guard set; the
Chromium click-through (Q1128 = a) — airplane mode on, the top-bar plane toggle → `#net-consent` → the host
hover, in en, ar and fr, recorded under `docs/audit/` per surface; the consent fixture —
`test_interfaces_endpoint_is_local_only` (`tests/test_network_consent.py:49`, grepped) stays green, and the
PR states that this slice adds NO fetch (nothing under the kill switch changes).

## 5. Operator steps

1. The maintainer's click-through of the popup hover (Q1128 = a), on their machine, recorded per surface in
   `docs/audit/`. Artifact: the record.
2. The maintainer's word on the lane grouping names used in S1/S3 (a design note; it binds nobody until said).

## 6. What this slice may not decide

- What counts as a lane before `S04-08` lands; the hook answers "which lanes are on" from the scheduler
  settings until the registry exists.
- The "Wikimedia ×4" of Q1002 against the tree's five Wikimedia-operated hosts (the per-edition Action API,
  `www.wikidata.org`, WDQS, ORES, dumps): the hover lists what the tree reaches; the count is the sheet's.
- Whether `publicsuffix.org` is a runtime fetch (then listed) or a bundled list (then an allowance).
- The law lane's hosts before `S04-10` picks its adapters (Q925 ⛔ is not touched here — it blocks only the
  adapter order on row Q).
- No ASSUMPTION and no CONFLICT is built on here.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
