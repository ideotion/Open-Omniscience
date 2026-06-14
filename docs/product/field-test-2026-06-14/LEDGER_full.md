# Field-Test Ledger → v0.1 Alpha Baseline Prompt

Intake mode: NOT fixing anything; the parallel session owns 0.09 commits.
This is a durable scratch ledger of the maintainer's field-test remarks.
On "compile"/"done" → render the single consolidated baseline prompt.

Legend: [PLANNED] already ruled in CLAUDE.md (reinforcement) · [NEW] net-new finding.

---

## Backlog cross-reference (parallel session's BACKLOG_GROUPED.md, supplied 2026-06-14)

Full backlog saved verbatim → `/home/user/parallel_backlog.md`. Use it + this ledger to
detect duplicate remarks. Groups present: A foundations · B download/scraping · C
task-manager · D first-launch/install · E UI shell · F analysis window · G
markets/commodities · H Wikipedia · J Settings · L docs. (Groups jump A,B,C,D,E,F,G,H,J,L
— NO Agenda-content group appears — see Item 7.)

Items captured so far vs the backlog:
- Item 1 (installer no-DB-init / no-passphrase + auto-launch) → DUP of Group D
  ("Auto-launch the app" + "Encryption choice → app's first screen"). [PLANNED]
- Item 2 (stepped wizard lang→T&C→passphrase) → wizard = DUP of Group D ("Guided setup
  wizard"); the T&C STEP + authoring T&C content = NOT in backlog = [NEW].
- Item 3 (Ollama/LLM mgmt) → DUP of Group J ("In-app Ollama + model installer");
  Ollama-RUNTIME update detection + live "latest models" refresh = NOT in backlog = [NEW nuance].
- Item 4 (unlock wrong logo) → DUP of Group D ("Unlock screen canonical eye"); the
  FYI-log notes (create-db 400, favicon 404, WARNING noise) = NOT in backlog = [NEW].
- Item 5 (quit/lifecycle: browser↔terminal, no are-you-sure popup) → NOT in backlog = [NEW].
- Item 6 (one-logo-everywhere; app-icon PNG off-canon; favicon) → invariant #5 relates to
  Group D's unlock item, but app-icon/favicon/cross-surface sweep = NOT in backlog = [NEW].
- Item 7 (seed Wikipedia recurring holidays) → NO Agenda-content group in the supplied
  backlog ⇒ NOT represented = [NEW to their tracking]. (CLAUDE.md DOES carry a big
  agenda-content batch — likely a backlog-doc gap worth confirming, not lost work.)

Net so far: genuinely net-new pieces = T&C step+content (2), Ollama runtime-update +
latest-models refresh (3), the FYI-log micro-bugs (4), quit/lifecycle (5),
app-icon/favicon brand sweep (6), the entire Wikipedia-holidays seed (7). Everything
else duplicates Groups D/J and is already tracked.

---

## Item 1 — Installer must not init DB / not prompt for passphrase; must auto-launch app  [PLANNED]

**Verbatim:** "The database should not initialize here and users should not be
prompted for passphrase. This will be done at app launch. In addition, I would
like the installer to automatically launch the app."

**Surface:** `scripts/bootstrap.sh` + `install.sh` (curl | bash install flow).

**Observed in installed 0.09:** The "Initialising the database" step interactively
prompts the encryption choice `[1] encrypted / [2] plaintext / [3] decide at first
launch [default: 3]`. User chose [3]; init was deferred (worked). But the prompt
itself should not appear in the normal interactive install.

**Maps to existing ruling:** YES — CLAUDE.md "INSTALL-FLOW NEXT SLICE (2026-06-13)":
(a) install.sh AUTO-LAUNCHES the app on completion ("ends fluid, inside the running
app"); (b) the encryption choice MOVES to the app's initial in-browser screen — the
first-launch prompt becomes PRIMARY, the terminal prompt demotes to the
headless/env fallback. Also relates to FIRST-LAUNCH GUIDED SETUP wizard (#24).

**Status:** Reinforcement of an already-ruled, not-yet-shipped item.

**Action for v0.1:**
- Interactive (TTY) install: do NOT initialise the DB and do NOT prompt for
  passphrase/encryption. Always defer the encryption choice to first app launch
  (in-browser guided setup).
- Keep the terminal/env encryption prompt ONLY as the headless / non-interactive
  fallback (e.g. OO_DB_PASSPHRASE / OO_DB_PLAINTEXT), never in the normal path.
- install.sh auto-launches the app on successful completion (browser opens to
  http://127.0.0.1:8000), preserving zero-network / airplane-mode boot.

---

## Item 2 — First launch must be a STEPPED wizard: (1) language → (2) Terms & Conditions → (3) passphrase  [PLANNED order + NEW T&C step/content]

**Verbatim:** "When starting the app, a screen appears with 'create your corpus
passphrase'. I would like the installation to be stepped like this: 1) chose
language 2) agree with terms and conditions (We should write detailed terms and
conditions about this app, professional, in all available GUI language, deferring
all responsibility, reminding the open-source aspect and the fact that as it's been
entirely vibe coded, code is available for review but hasn't been reviewed by humans
at the moment and the true willingness of being honest and ethical) 3) Passphrase
creation (in the chosen language)"

**Surface:** First-launch / unlock create screen (`unlock.html`) → becomes the
FIRST-LAUNCH GUIDED SETUP wizard.

**Observed in installed 0.09:** App opens straight to "create your corpus
passphrase" — no language step, no T&C step before it (wizard not yet built).

**Maps to existing ruling:** PARTIAL — FIRST-LAUNCH GUIDED SETUP (#24, ruled
2026-06-13) already mandates a one-time stepped GUI: language selection →
encryption/passphrase choice → source-setup-by-theme → consented first collect,
replacing the #onboard card. So the stepped structure + language-first +
passphrase-inside-wizard = [PLANNED].

**Net-new:** [NEW] A Terms & Conditions ACCEPTANCE step inserted between language
and passphrase, PLUS authoring the T&C content itself. Not in any existing ruling.

**T&C content requirements (verbatim asks):**
- Professional tone.
- In ALL available GUI languages (×12 locales) — per the non-negotiable that every
  consent/caveat string ships ×12 (Arabic RTL).
- Defers all responsibility (liability disclaimer).
- Reminds the open-source aspect.
- Discloses honestly: the app has been ENTIRELY "vibe coded" — code is available for
  review but has NOT been reviewed by humans at this time.
- States the true willingness to be honest and ethical.

**Design notes / open points:**
- Order: language → T&C(accept) → passphrase. UI is already in the chosen language
  by the passphrase step (OOI18N.setLang, invariant #15).
- T&C acceptance is a blocking step, recorded once as a user-visible setting
  (T&C version + timestamp), consistent with the wizard's "one-time state is a
  user-visible setting, not a hidden flag" rule. Consider re-prompt on T&C version bump.
- Informed-consent-by-LAYERING: short visible terms + long form in hover/expand,
  never hidden (invariant #17 / informed-consent non-negotiable).
- Honest framing: the disclaimer is good-faith and is itself part of the
  "not human-reviewed" disclosure — not legal advice.

**Action for v0.1:** Build/finish the first-launch guided wizard with the front
sequence language → T&C(accept) → passphrase; author the professional T&C ×12 with
the clauses above.

---

## Item 3 — Settings: Ollama/LLM model management — install/manage, Ollama update detection, list latest models, download manager  [PLANNED + EXTEND]

**Verbatim:** "The app's settings tab, there should be an ollama / LLM model
management interface, and the app should integrate an ollama update detection tool
as well as a 'list the latest models' in addition to a model download management
interface."

**Surface:** Settings → LLM panel; task-manager window (downloads as jobs).

**Observed in installed 0.09:** No Ollama/LLM management interface present in Settings.

**Maps to existing ruling:** YES (mostly) — IN-APP OLLAMA/MODEL INSTALLER + APP
SELF-UPDATE (ruled 2026-06-13, designed in FUTURE_DEVELOPMENTS): Settings → LLM panel
installs Ollama + pulls models, catalog picker (size/RAM/license shown, NEVER a
score), pulls are task-manager jobs, checksum-verified through the guarded factory,
clearnet a stated prerequisite, hardware fit MEASURED. Plus non-negotiables: no
bundling of Ollama/models in repo; date-stamped catalog (CATALOG_AS_OF + freshness
test). So the management panel + download manager = [PLANNED].

**Net-new nuances [NEW/EXTEND]:**
- OLLAMA RUNTIME update detection — the ruling covers Ollama INSTALL + APP
  self-update, but NOT detecting/offering updates to the Ollama binary itself. Add:
  consented check for a newer Ollama version, surfaced honestly, update via the
  guarded path as a task-manager job.
- "List the LATEST models" — the ruling's catalog picker is the bundled date-stamped
  catalog; "latest" implies a refreshable/live list of newest models. Add a
  consented, guarded refresh of the model list (Ollama library) with honest freshness
  labeling (catalog AS_OF vs live-fetched); never auto-fetched at boot.

**Guardrails (carry from non-negotiables):** all network via the guarded socket
factory (kill switch / robots / proxy / honest UA) + ONE consent popup + a VISIBLE
task-manager job; checksum-verify pulls; show size/RAM/license never a score;
hardware fit MEASURED not asserted; no models/Ollama bundled in the repo.

**Action for v0.1:** Build the Settings → LLM management panel: install Ollama,
list/refresh latest models (freshness honesty), pull/remove models, Ollama-runtime
update detection — with all downloads as managed task-manager jobs.

---

## Item 4 — Unlock/passphrase screen shows the WRONG logo (+ FYI-log notes)  [PLANNED + minor NEW]

**Verbatim:** "When I got prompted for a passphrase through the graphical interface,
the open-omniscience logo wasn't correct." (plus a launcher terminal copy-paste
shared FYI.)

**Surface:** `unlock.html` (the in-browser passphrase create/unlock screen).

**Primary issue — logo:** The eye logo on the graphical passphrase screen is not the
canonical brand eye.
**Maps to existing ruling:** YES — INSTALL-FLOW NEXT SLICE (c): "The /unlock screen
must carry THE canonical eye (invariant #5, exact same vector as the GUI top-left) —
today it draws a DIFFERENT double-arc eye (unlock.html:44 vs index.html:578); extend
the invariant-#5 test to unlock.html when fixed." [PLANNED] reinforcement. (The
terminal ASCII eye looked correct; only the unlock.html SVG is wrong.)
**Action:** Replace the unlock.html eye with the canonical pointed-oval + grid-iris
SVG (assets/icon.svg / index.html); extend test_ui_invariants #5 to cover unlock.html.

**Secondary notes from the FYI terminal log (not explicitly complained about —
flag/verify):**
- `POST /api/system/create-db → 400 Bad Request` during passphrase creation,
  immediately before alembic stamps head c8d9e0f1a2b3. [NEW — verify] Could be a
  benign rejected first attempt / validation, or a real create-db flow bug. Worth
  confirming first-launch passphrase creation has no spurious 400.
- `GET /favicon.ico → 404 Not Found` — no favicon served; minor polish (serve the
  eye as favicon). [NEW minor]
- `Could not seed default sources: open_omniscience.db does not exist yet ...` logged
  at WARNING — this is EXPECTED deferred-init behavior (sources seed at first unlocked
  start). Benign; consider downgrading the log level / softening wording so it doesn't
  read as an error. [NEW cosmetic]

---

## Item 5 — App-quit UX: browser-close vs terminal lifecycle; NO "are you sure?" quit popup (no data loss)  [NEW]

**Verbatim:** "Should closing the web browser also close the terminal? If there's no
dataloss, then there's no need for an 'Are you sure?' pop-up asking whether the user
really wants to quit the app or not."

**Surface:** App lifecycle — launcher terminal (uvicorn server) ↔ browser client;
scripts/launch.sh; web chrome unload handling.

**Current behavior:** Terminal runs the server; "To stop the app: close this window
(or press Ctrl-C)." Browser is just a client — closing it does NOT stop the server.

**Verified (grep, no fix):** NO beforeunload/onbeforeunload or quit-confirmation popup
exists today. The existing confirm() dialogs are all GENUINE destructive/consequential
actions (panic wipe, uninstall, delete source/rule/super-group, clear draft, big-dump
download, external-link guard, network-task arbitration) — those SHOULD keep their
confirmations. So "no are-you-sure-to-quit" is a FORWARD GUARD, already satisfied —
keep it that way (never add a beforeunload quit confirmation).

**Open design decision [needs ruling]:** Should closing the browser also stop the
server/terminal?
- TENSION: the CONTINUOUS-COLLECTION ruling ("scraping never stops; background
  auto-collect after first-run approval") implies the SERVER should keep running
  without a browser so background collection continues ⇒ browser-close should NOT kill
  the server.
- CONSENT/expectation angle: if the server keeps collecting after the browser closes,
  the user must UNDERSTAND it's still running (honest, visible) — closing a tab
  shouldn't silently leave network activity the user thinks they stopped.
- RECOMMENDATION (veto-able): keep browser and server DECOUPLED; provide an explicit,
  FRICTION-FREE Quit (no "are you sure") for a full stop; make the "still
  running / collecting in background" state honest and discoverable. No
  quit-confirmation popup ever (no data loss to protect).

**Action for v0.1:** Decide the lifecycle model (recommend decouple + explicit
frictionless quit + honest background-running disclosure); guarantee no spurious
quit-confirmation popup; keep genuine destructive-action confirmations.

---

## Item 6 — One canonical logo EVERYWHERE; the APP ICON (launcher PNG) is off-canon  [PLANNED principle + NEW concrete instances]

**Verbatim:** "As well, the app icon logo is not correct. There should only be one
single logo everywhere." (+ pasted the canonical ASCII eye = assets/logo.txt.)

**Surface:** App/desktop launcher icon; all brand-mark surfaces.

**Verified (read assets, no fix):**
- CANONICAL (invariant #5) = `assets/icon.svg` = `assets/logo.txt` ASCII = index.html
  top-bar SVG: pointed-oval eye + FLAT rectangular grid iris + 4 corner rays, NO round
  pupil.
- WRONG — `assets/icon.png` (the desktop/menu launcher icon; install.sh:403 uses
  icon.png, falls back to icon.svg) is a DIFFERENT design: a globe/sphere iris WITH a
  round central pupil. Does not match the canonical SVG → this is "the app icon is not
  correct."
- WRONG — no favicon is served anywhere (no rel="icon" in index.html/unlock.html) →
  the GET /favicon.ico 404 from Item 4.
- WRONG — unlock.html eye is a different double-arc eye (Item 4).

**Maps to existing ruling:** invariant #5 mandates ONE brand mark (the eye);
INSTALL-FLOW NEXT SLICE (c) covers unlock.html. So the PRINCIPLE = [PLANNED]; the
icon.png divergence + missing favicon = [NEW concrete instances].

**Action for v0.1 (brand-mark consistency sweep — CONSOLIDATE with Item 4):**
- Single source of truth = assets/icon.svg (the canonical eye); generate ALL
  raster/derived assets FROM it.
- Regenerate assets/icon.png from icon.svg (drop the globe+pupil variant).
- Add a favicon (served + linked in index.html/unlock.html) rendered from the
  canonical eye; add a PWA-manifest icon set when the PWA path lands.
- Fix unlock.html to the canonical eye (Item 4).
- Extend test_ui_invariants #5 to assert the canonical eye on EVERY surface:
  index.html (have), unlock.html, the favicon link, and icon.png↔icon.svg parity
  (regenerate-and-compare or assert provenance) so "one logo everywhere" can't regress.

**Cross-ref:** Item 4 (unlock logo) — group together in the compile under a single
"brand-mark consistency" action.

---

## Item 7 — Seed the DEFAULT agenda with the Wikipedia recurring-holidays list  [PLANNED batch + NEW concrete content]

**Verbatim:** "Here's a list of calendar holidays extracted from Wikipedia. I'd like
them to be incorporated into the app's default agenda/calendar database. Mark each of
them as sourced from Wikipedia. They are recurring events, and as such should be shown
for whatever year."

**Raw seed data preserved verbatim:** `/home/user/seed_wikipedia_holidays.md`
(re-attach when executing; maintainer also holds the original).

**Surface:** Agenda/calendar default DB; recurring-event model; astronomy engine.

**Maps to existing ruling:** YES — AGENDA CONTENT remaining: "PRELOADED worldwide bank
holidays + religious calendars ... recurring-event model unifying rules + per-year
instances + origin year ... month-span banners ... every entry sourced, movable dates
marked, subscribe-default stays off-flood." Plus the SHIPPED astronomy layer (Meeus
equinoxes/solstices/full+new moons, verified). So the capability = [PLANNED]; this is
[NEW concrete seed content] driving it.

**CRITICAL correctness caveats (the value-add — honesty-by-construction):**
- DO NOT hardcode MOVABLE feasts to the example dates in the list. Entries like
  "Ramadan 20 March 2026", "Eid-Ul-Fitr 9 April 2024", "Eid al-Fitr 30/31 March 2025",
  "Easter typically April" are single-year EXAMPLES, not fixed recurrences. Storing
  them as fixed = fabricated dates = violates the ethics.
- Classify EACH entry by recurrence TYPE and store accordingly:
  (A) FIXED Gregorian M-D (New Year 1 Jan, Epiphany 6 Jan, Valentine's 14 Feb, Pi Day
      14 Mar, Earth Day 22 Apr, Halloween 31 Oct, Christmas 25 Dec, …) → recurring fixed.
  (B) NTH-WEEKDAY rule (World Kidney Day = 2nd Thu Mar; US Labor Day = 1st Mon Sep;
      US Thanksgiving = 4th Thu Nov; CAN Thanksgiving = 2nd Mon Oct) → weekday-rule.
  (C) MULTI-DAY SPANS → month-span banners (Twelve Days of Christmas 25 Dec–6 Jan;
      Las Posadas 16–24 Dec; Advent; Nativity Fast 40d; Samhain 31 Oct–1 Nov; All
      Saints/Souls + Día de Muertos 1–2 Nov; Mandala Vratham mid-Nov–mid-Jan; Lent).
  (D) ASTRONOMICAL → REUSE the shipped Meeus engine, computed per year (Ostara/Nowruz
      spring equinox ~21 Mar; Midsummer/Longest-Night solstices; Inti Raymi/We Tripantu
      S-hemisphere winter solstice; Vesak = Vesak full moon; Asalha Puja = first full
      moon in Ashadha). Do NOT pin these to 21 Jun etc.
  (E) MOVABLE computed/tabular per tradition — mark MOVABLE, dates from sourced tables
      or computed, NEVER fabricated, honest caveat:
      • Christian Easter cycle (Western + Orthodox) — Easter is computable (computus);
        Ash Wed/Lent/Good Friday/Holy Saturday/Easter key off it.
      • Jewish (Hebrew calendar, deterministic/computable): Purim, Pesach, Shavuot,
        Rosh Hashanah, Yom Kippur, Sukkot, Simchat Torah, Lag BaOmer, Yom HaShoah,
        Yom HaZikaron.
      • Islamic (Hijri lunar): Ramadan, Eid al-Fitr, Eid al-Adha — computed tabular
        dates WITH the ruled honest ±1-day moon-sighting caveat.
      • Hindu (lunisolar panchanga): Holi, Ram Navami, Diwali, Navratri, Raksha Bandhan,
        Krishna Janmashtami, Ganesh Chaturthi, Onam, Ratha Yatra, Kartik Purnima, Guru
        Purnima, Devshayani Ekadashi, … — per ruling, SOURCED published tables, NEVER a
        fabricated panchanga.
      • Tibetan Buddhist: Losar (~Feb) movable.
- "Shown for whatever year": the recurring model must materialize the instance for any
  browsed year; for movable entries where no per-year value is available, show as
  MOVABLE with the approximate window + caveat, never a false exact date.

**Provenance + honesty of the list itself:**
- Mark every entry "sourced from Wikipedia" (provenance ≠ veracity — a stated app
  principle). Bundling as DEFAULT DB content also sidesteps the dead/robots-disallowed
  calendar feeds from field-log #E.
- STRIP POV/editorializing wording before storing as fact (e.g. "Gandhi Jayanti: an
  indoctrinated festival" → neutral description).
- FLAG dubious / [citation needed] / likely-vandalism entries for a maintainer
  decision (include-with-honest-provenance+verification-flag vs exclude): "World Klassik
  Day / Klassikanity / DON SANTO's Birthday", "International Pianist Day [cn]",
  "Raib-Shain Paavein [cn]", "International/World Dates Day (Mouhab Alawar)",
  "Sapta-Bipta", "World Knowledge Day" appended to Ambedkar Jayanti.
- Preserve the tradition/region tags from the list's headers (Christianity, Islam,
  Judaism, Hinduism, Buddhism, Sikhism, Paganism, Satanism, Secular + regional:
  Tamil Nadu, Punjab, Wales, US/CAN, Albania…) as filterable groups → natural
  off-flood SUBSCRIPTION groups (subscribe-default stays off per the ruling). Supports
  de-US-centring.
- Dual-calendar notes where present (Orthodox Christmas 7 Jan Julian ≡ 25 Dec Greg
  until 2100; Christmas "25 December and 7 January").

**Action for v0.1:** Build/extend the recurring-event model (fixed / nth-weekday /
span / astronomical / movable-tabular), seed it from the Wikipedia list with
per-entry Wikipedia provenance + correct recurrence type + tradition/region tags;
reuse the Meeus engine for astronomical entries; mark movable entries movable with
honest caveats; strip POV wording; surface the dubious entries for a keep/exclude
ruling; group by tradition for off-flood subscription.

---

## Item 8 — Transversal CHANGE-TRACKING / PROVENANCE / AUDIT tool anchored to ALL data (its own universal subtab)  [PLANNED core (Wikipedia) + NEW transversal elevation]

**Verbatim:** "I had previous thoughts about tracking database related sources changes.
Specifically for Wikipedia pages, and also because it is a very fast moving content.
However, I believe this should be a complete, transversal tool. It could become so
important to deserve its own tab in the redesigned universal subtabs system. I don't
know if this affects the database architecture. But we should address this as an
important transversal tool, which should consistently be anchored to all data (here are
my preliminary thoughts : date of initial scrapping / date of verification / Audit
trail / List of changes / impact on keywords / initial data or article / current or
revised version / version history etc.). This should not affect performance."

**Surface:** TRANSVERSAL — universal subtab system (Group E, in progress), analysis
window sub-tabs (Group F), Wikipedia living-source (Group H), law versioning,
reliable-memory vintages, and the DB architecture.

**Maps to existing rulings:**
- Group H "Dedicated tracked-changes tab" — but WIKIPEDIA-PER-ARTICLE scoped.
- WIKIPEDIA AS A LIVING SOURCE: amendable like the law, every change traceable,
  version-anchored analytics, audit control; per-revision full text already stored.
- Law versioning; Official-statistics VINTAGES (parked, "the law/wiki versioning
  model"); reliable-memory pillar (VINTAGES never overwrites, audit/transparency).
So the CHANGE-TRACKING CORE = [PLANNED] for Wikipedia/law.

**Net-new [NEW]:** ELEVATE change-tracking from Wikipedia-specific to a COMPLETE
TRANSVERSAL tool: anchored to ALL data objects (every article/source/market/law/wiki),
its OWN sub-tab in the universal subtab system ("Changes / Provenance / Audit" facet on
every object + in the Group-F analysis window), with a consistent anchored-field schema.

**Anchored fields (maintainer list → mapping):** initial-scrape date (mostly have) ·
verification date (NEW transversal "last-verified" anchor; cf. VERIFICATION-PENDING,
audit-07 fixity) · audit trail (append-only who/what/when; ties to custody + reliable-
memory transparency log) · change list (wiki revisions / article re-scrape diffs /
market vintages) · impact on keywords (NEW delta analytic: which keywords/mentions/WWW
changed across versions) · baseline (as-first-scraped) vs current/revised · version
history timeline.

**Open architectural question (maintainer raised) — likely YES affects the DB:**
- Need a UNIFIED revision/provenance substrate OR a thin transversal interface over the
  per-domain stores (wiki WikiRevision full_text; law; market time-series vintages).
- SEPARATE version-BLOB storage from anchor METADATA (codec-drag lesson — never drag
  full version blobs through SQLCipher for a metadata/audit list).
- Diffs vs full versions: wiki chose PER-REVISION FULL TEXT (truncated diffs were
  non-reconstructable); reconcile cost via content-hash DEDUP of unchanged versions.

**Hard constraint — "should not affect performance":** tracking APPEND-ONLY + OFF the
critical write path (async), given SQLCipher single-writer contention (field-log A);
audit/history reads on a READ SNAPSHOT (Group A) + covering indexes; metadata views
never load blobs; dedup unchanged versions so fast-moving Wikipedia doesn't explode IO.

**Recommendation:** flagship-scale + cross-cutting → author a dedicated ARCHITECTURE
DESIGN DOC (like DB_RELIABILITY docs) BEFORE building; decide alpha vs V0.1+ scope
(minimum alpha = the Group-H wiki tab implemented THROUGH a transversal-ready substrate
+ anchored-field schema, so the general tool grows from a sound base, not a wiki silo).

**Cross-ref:** Item 9 shares the transparency-log / provenance substrate — design together.

---

## Item 9 — Federated DB merge between journalists + automatic tamper-evidence (ISO-style) + durable schema  [SHIPPED CORE + NEW federation/auto-fixity framing] — maintainer asked for CONCEPT IDEAS

**Verbatim:** "Regarding database management, two journalist from different parts of the
world should be able to merge their entire databases without loosing trust in their own.
Database aggregation should be something that survives the long term app updates, we
need need a database structure that won't change over time, that is reliable, and we
need the app to produce al necessary yet automated database integrity tools, to verify
they could not have been tampered with, the same way we use when downloading linux ISO
files from trustworthy sources. This should be completely automatic. I'd prefer you to
develop concept ideas for this to help me see through a robust, durable, reliable, long
term, performative, open source and ethical solution."

**Concept memo developed (maintainer request):** `/home/user/concept_federated_corpus_exchange.md`

**Surface:** DB-reliability / backup-restore / merge engine; reliable-memory pillar;
custody; shares substrate with Item 8.

**Maps to existing (much is SHIPPED/PLANNED):**
- oo-backup-2 signed artifact (sha256 + Merkle + signed manifest) + v2 ADDITIVE merge
  engine (conflicts keep-local + report-both; custody verified-not-trusted; idempotent;
  torture 10/10) + RESTORE-IS-ADDITIVE ruling → ask 1 foundation EXISTS.
- Reliable-memory pillar (content addressing, signed manifests, RFC-6962 transparency
  logs, OpenTimestamps anchoring, LOCKSS, fixity, VINTAGES) → ask 3 design EXISTS
  (currently sister-project-leaning).

**Net-new framings [NEW]:**
- Journalist-to-journalist FEDERATED EXCHANGE as a first-class workflow (peer-to-peer,
  signed per-contributor origin attribution, mine/theirs/both filter) — beyond "restore
  a backup."
- FULLY AUTOMATIC integrity verification surfaced like ISO checks (auto hash+signature
  verify on import with a plain verdict; peer keyring/TOFU; continuous background
  fixity) — zero manual steps.
- Durable INTERCHANGE format decoupled from the volatile internal schema (self-describing,
  forward-compatible, content-addressed, legacy-forever as a TESTED contract).

**Honest reframe to confirm:** "a database structure that won't change over time" can't
mean a frozen internal schema (features need schema growth) — it means a STABLE,
FORWARD-COMPATIBLE INTERCHANGE FORMAT + content-addressed identity. Flagged for agreement.

**Decisions to settle (in memo):** per-journalist key/identity UX for non-cryptographers;
v0.1 scope line (local fixity + auto-verify in-app vs anchoring/witnessing in the
mirror); out-of-band key verification; conflict-review UX at scale.

**Action:** Promote the memo into a proper design doc (alongside DB_RELIABILITY docs);
confirm the schema reframe; decide the v0.1 scope line; implement on the existing
merge/manifest foundation. Design together with Item 8.

---

## Item 10 — Refine Pillar A: multi-attestation on dedup + changes-only storage + a Difference-Explorer tool in Settings→DB management  [SHIPPED dedup + NEW attestation/diff-tool]

**Verbatim:** "About Pillar A, just one comment : at database import/merge, identitical
data should not be duplicated. However, there should be a way to store that another
signed and authentic database had the same data. In addition, in case of database
differences, only the changes should be stored. We should think of a new tool
specifically designed to explore, analyze and take action upon database differences. As
this is a rare case scenario, it should be accessible from with the settings' database
management tab."

**Refines:** Item 9 Pillar A (merge) + Item 8 (change tracking). Concept memo updated
(Pillar A bullets + new Pillar E).

- (1) No duplication of identical data → [SHIPPED] bit-for-bit dedup (merge engine).
  Reinforcement.
- (2) Store that ANOTHER signed/authentic DB had the same data → [NEW] MULTI-ATTESTATION:
  dedup attaches an attestation (signer + hash match + import date) instead of discarding;
  becomes a corroboration counter + tamper-evidence multiplier. HONESTY: anti-false-
  triangulation independence caveat (record each corpus's own source; shared upstream =
  one source in two hats; corroboration only if paths independent; never auto-inflate).
- (3) On differences, store only the changes → [PLANNED-via-mechanism] content-addressed
  storage = each unique version once (changes-only without naive diffs; reconstructable
  per the wiki lesson); differing versions = vintages (Item 8).
- (4) NEW TOOL to explore/analyze/act on differences → [NEW] the DIFFERENCE EXPLORER
  (= Item 9 decision #5 made concrete): explore (only-mine / only-theirs /
  identical-attested / differing) · analyze (provenance, keyword-impact, independence) ·
  act (accept-theirs=ADD / keep-mine / keep-both default / investigate / split).
  RESTORE-IS-ADDITIVE: never silent replace/delete; keep-both default; removals explicit +
  snapshot-reversible.
- (5) Placement → [NEW] Settings → Database management tab (rare-case; invariant #8;
  reuses the T6 restore-preview area).

**Action:** Fold into the Item-9 design doc; build the Difference Explorer in
Settings→DB management on the merge/manifest + Item-8 substrate; implement
multi-attestation enrichment in the dedup path; content-addressed changes-only storage.

---

## Item 11 — Field-log analysis (PR≤110 build, 2026-06-14): perf corroborations + elevated severities  [PLANNED corroboration + NEW severity data]

**Source files:** ooperfreport, oonetworkpreflight, oodebugbundle, oo keyword log; .db
backup NOT opened (encrypted corpus — privacy). Corpus: ~1201 articles / 3177 sources /
55885 keywords / 111566 mentions / 13483 price points; 2-core/6 GB Qubes VM,
unlocked-encrypted, over Tor; LLM qwen2.5:0.5b installed; scheduler continuous
round-robin, collect_parallelism:1, max_sources_per_run:0 (cap already 0).

**Useful? YES.** Findings:
- CATASTROPHIC keyword_export: selftest = 353s then 276s (~5–6 MIN) for ~15 MB, while a
  collect pass ran (contention). Far beyond T1's 7.8s synthetic. ELEVATES Group A
  "keyword_export under contention" — single SQLCipher connection serialization +
  concurrent collect = pathological. [corroborated + worse]
- BLOCKING market import-all: 1 request = 878.7s (14.6 min) — FRED Read-timeout 30s × 2
  attempts (wti/brent/natgas/eurusd/nasdaq) + 28 serial feeds over Tor. = Group B
  parallel-downloads + official-endpoint direction. [corroborated]
- POLLING STORM (~86 min): scheduler/activity 2519 req / 288 CPU-s (!), vitals 3536,
  status 1050, network 1022, db/stats 481, countries 111, coverage 111. = Group A "UI
  polling storm". [strongly corroborated]
- Analytics reads slow under collect contention: insights_map 5.2→7.8s (slower run2 =
  contention), insights_trending 2.7→3.2s. [watch]
- Kill-switch mid-import: index batch nasdaq100/dow/vix/nikkei225 = "network kill switch
  active" → verdict offline = CORRECT honest behavior (user toggled airplane mid-import),
  not a bug.
- Dedup working: 2nd commodity import skipped_existing 413 (no duplication).
  gold/silver/sawnwood = dead-series 404 (catalog needs verified replacements — known).
  No "database is locked" store-loss visible this run (PR107 retry may be helping;
  earlier field-log loss stands separately).
- Preflight corroborates field-log #E: every google-hol-* robots-disallowed; webcal.guru
  religious disallowed; raw.githubusercontent/space.floern/cantonbecker undetermined →
  refused; WORKING = worldpublicholiday (wph-*), monkeyness-moons (2623 ev), ose-calendar
  (159). → Group B "drop dead default feeds" + supports Item 7 (bundle holidays as default
  DB to sidestep dead feeds). Tor 403s on premium news = known T4 reality.

**Net:** mostly corroborates Groups A/B with HARDER severity numbers (export ~5 min,
import-all 14.6 min, activity-poll 288 CPU-s). No new bug class; elevates Group A (status
consolidation + export read-snapshot) and Group B (parallel + official endpoints).

---

## Item 12 — Language-independent keyword analytics for a monolingual analyst (maintainer question + my recommendation)  [PLANNED layer + NEW framing] — asked "what do you think?"

**Verbatim:** "I'm wondering if keywords should not be assembled per language so that
analytics allow language independent keyword analytics. If the analyzer / reporter only
speaks one language, our app should allow the analytics to be made across all available
languages. What do you think?"

**Data check (keyword log):** keywords ALREADY carry `language` (en/es/sr… seen) + `kind`
(entity|term) + mentions/articles/sources + `language_mismatch`. So per-language assembly
is ALREADY the substrate. Export = 32453 diagnostic records of 55885 keywords; en-dominated.

**Maps to existing:** "Trans-language equivalence — LIVE analytics layer (elevated)" —
rings merge equivalent terms inside grouped trends/trending/associations/graph; guards
(language-qualified members, signature-supported joins, per-language counts visible, user
can split); groundwork shipped (signatures + curated rings + first 10 rings). So CONCEPT =
[PLANNED]; the maintainer ELEVATES it to a first-class GOAL: monolingual analyst →
analytics across ALL languages.

**My recommendation (asked):** STRONG YES — TWO-LAYER design:
- L1 (truth, HAVE IT): keep keywords language-qualified — never conflate at storage
  (frequencies/meanings are language-specific; false friends).
- L2 (analytics, BUILD): cross-language CONCEPT nodes merging equivalent terms on demand;
  per-language members + counts ALWAYS visible + splittable.
- Cross-language link sources (offline-first, ranked):
  (1) ENTITIES → Wikidata Q-IDs / Wikipedia langlinks = language-independent concept
  anchors (many keywords are kind:entity; app already ingests Wikipedia → strongest, most
  ethical, offline backbone). (2) common terms → curated equivalence rings (have) +
  bundled multilingual lexicon. (3) OPTIONAL local-LLM / multilingual-embedding "deduced
  equivalence" (a model is installed but qwen2.5:0.5b is too small — needs the planned
  Ollama installer's bigger model); always labeled deduced.
- Honesty guards: equivalence is DEDUCED (false friends/polysemy) — show original
  term+language+source; per-language counts visible; user split/override; DISCLOSE
  contributing languages (never silent English-pivot — anti-anglicisation; per-language-
  stoplist + de-US-centring lessons).
- Coverage caveat: "across ALL languages" gated by EXTRACTION coverage — audit-07: CJK
  (zh/ja) segmentation absent → zh/ja keywords nonfunctional today; L2 can only include
  languages actually extracted. State honestly.

**Action:** Build L2 (trans-language concept layer) on the existing L1 + a Wikidata-Q-ID
entity anchor; keep guards; disclose contributing languages + extraction-coverage gaps.
Flagship analytic for the mission (a monolingual journalist sees a story surging in
foreign-language sources).

---

## Item 13 — LLM bulk translation → derived "foreign" corpus + isolated translation-keyword sub-analytics  [NEW] — maintainer asked "what do you think?"

**Verbatim:** "LLM translation capability should be made available through the search
result / corpus UI, it should allow bulk foreign languages to be translated, thus creating
a new corpus of articles for the user to read, analyse, and so forth. The bulk corpus
foreign language translation (foreign means all other languages except for the one the
user's UI is in) should open up a new window with an additional LLM related tab synced
with ollama : LLM model picker for the translation, ongoing status (translated articles vs
remaining in queue, estimated time based on average previous translations/time/word
ratio...). One question I'm wondering is with keywords. My guts tell me to stick to
existing, original language related keywords, but I'm not sure our engine will be good at
merging keywords from different languages without making mistakes. So maybe we could offer
the user the possibility to make keyword analysis from this fabricated corpus, without
influencing the overral keyword engine, like a temporary sub-keyword analytics tool,
discrete to the user, leveraged by the unified tab approach. A mention stating that the
analyzed keywords are made from a hybrid direct keyword extraction and an indirect - per
translation - keyword exctract. What do you think ?"

**Surface:** corpus/analysis window (Group F); Ollama/LLM (Group J + Item 3); task-manager
job (Group C); complements Item 12.

**Feature (maintainer spec):** entry from search-result/corpus UI → BULK-translate all
FOREIGN-language articles (foreign = every language ≠ the UI language) via local LLM → a
NEW DERIVED corpus to read/analyze. Opens a NEW window + an Ollama-synced LLM tab:
translation MODEL PICKER; ongoing STATUS (translated vs remaining in queue; ETA from avg
words/time ratio). Keywords: an ISOLATED, TEMPORARY, DISCRETE sub-keyword-analytics on the
fabricated corpus that does NOT influence the main keyword engine (unified-tab approach);
disclose keywords are HYBRID direct + indirect(per-translation).

**My recommendation (asked):**
- Translation feature: YES, honesty-by-construction: the translated corpus is a
  FABRICATED/DERIVED artifact — label every article machine-translated (model+version+
  params+date, original language), keep original text one click away, never present
  translation as the source's words; DISTINCT FILTERABLE provenance class (like
  DDG-discovered / wiki editions), never blended into trust-sensitive views; local-LLM
  (Ollama) job with model picker + queue + MEASURED ETA (measure words/time, don't assert)
  + visible task-manager job; reproducible (store model+params).
- Keyword question — I AGREE with the maintainer's gut + endorse the isolation: KEEP the
  canonical keyword engine on ORIGINAL-language keywords (never let MT-derived keywords
  pollute corpus-wide analytics — translation errors would corrupt them); the translated
  corpus gets its OWN isolated, temporary, non-destructive sub-keyword-analytics in the
  unified tab. REFINE the disclosure: mark EACH keyword direct (UI-language original) vs
  indirect (from MT) + let the user filter to direct-only — richer than a blanket "hybrid".
- Reconcile with Item 12 (two routes COEXIST, both non-destructive): Route B (this:
  translate→extract; unification by TRANSLATION; user-driven, lower-risk, great for reading
  + ad-hoc) vs Route A (Item 12 equivalence/concept layer; unification by MEANING-MERGE =
  the merge-mistake risk; keep a non-destructive VIEW with per-language counts + split).
  Both honor "never corrupt canonical per-language keywords."
- CAVEATS to state in UI: local-LLM translation has errors (worse for low-resource langs +
  named entities) → derived corpus is a reading/orientation + exploratory aid, NOT ground
  truth, never for quote-level/trust-sensitive claims; for ENTITIES the Wikidata-Q-ID
  anchor (Item 12) beats translation; bulk translation on a 2-core VM is SLOW (Item 11) —
  ETA/queue UI matters, qwen2.5:0.5b is unusable for translation (needs the Ollama
  installer's bigger models).

**Action:** Build the bulk-translation feature in the analysis window (Ollama-synced LLM
tab: model picker + queue + measured ETA) → labeled, filterable derived corpus; add an
isolated non-destructive translation-keyword sub-analytics with per-keyword direct/indirect
provenance; keep canonical keywords untouched; coexist with Item 12's equivalence overlay.

---

## Item 14 — Persist + cache translations as TYPED DERIVATIONS (never as articles); reuse the Item-8 audit/version substrate  [NEW] — refines Item 13; maintainer asked "honest expert opinion"

**Verbatim:** "OK, now something else I'd like : avoiding translating the same articles over
and over. Include translated articles in the database. Don't mix translated and
untranslated articles. Why not add translations as a separate form of version control /
audit trail ? I'm not sure. But I'm sure that avoiding to retranslate will be usefull both
in terms of performance, compute/time, and energy. As long as translations can never
overlap / pollute the original database. Translations should be readily available with each
translated article. Same, what's your honest expert opinion vabout this ?"

**Refines:** Item 13 (bulk translation) with STORAGE; ties to Item 8 (provenance/version
substrate) + Items 9/10 (content-addressed derived artifacts, never pollute canonical).

**My honest expert opinion (asked): YES to all — the "version control / audit trail"
intuition is the elegant unifying answer.**
- Store a translation as a TYPED DERIVATION attached to the canonical original — NOT a row
  in `articles`. So "don't mix / never pollute" holds BY CONSTRUCTION: translations aren't
  articles → cannot enter article counts, the canonical keyword engine, trends, WWW,
  exports. canonical `articles` = originals only; translations in a separate store
  (article_translations / the Item-8 derivation substrate) FK→ original; the "translated
  corpus" (Item 13) = a VIEW joining originals + their target-language derivations, not a
  parallel article store.
- CONTENT-ADDRESSED cache key = hash(original_text) + target_lang + model_id +
  model_version + params ⇒ never re-translate the same content with the same model
  (idempotent dedup = the performance/compute/energy win). Content change (re-scrape) or
  model change ⇒ NEW derivation; old marked stale/superseded with provenance.
- Item-8 substrate FITS: a translation is a DERIVED VERSION — but TYPE it transform-
  derivation (language transform), DISTINCT from temporal-revision (source changed). Same
  substrate, typed edges → honest (a translation never claims the source changed). Audit
  fields: model+version+params, when, word count, time taken (feeds Item-13 ETA), reproducible.
- Bonus: version history across MODELS — re-translate later with a better model, keep both,
  user compares quality.
- Guards: canonical analytics run over originals ONLY; translations feed ONLY the isolated
  sub-analytics (Item 13); add a test/guard (crown/absorption-style) that no canonical query
  includes translation derivations.

**Honest caveats to flag:**
- STALENESS: a translation is bound to an original content-hash; if the article is
  re-scraped/changed the cached translation is STALE → invalidate/mark stale (re-translate
  on demand), never show old translation against new content (content-addressing handles it).
- STORAGE: translations ~double text per translated article (per target lang per model) —
  compress (zstandard already a dep), dedup by hash, scope bulk translation (opt-in, user
  picks a corpus). Bounded: a UI-language-X user needs translations INTO X only (not N×N).
- Keep it SIMPLE: one cached translation per (hash, lang, model, params); allow multiple
  models for comparison; don't build a heavy revision graph — Item-8 fields give the audit
  cheaply.
- Shareable (bonus, not required): a translation derivation could ride a backup/merge
  (Item 9) labeled machine-translated + model, verified-not-trusted.

**Action:** Persist translations as content-addressed, typed (transform-derivation) entries
in the Item-8 provenance/version substrate, FK-attached to canonical originals; cache to
avoid recompute; surface per-article + as the Item-13 read view; feed only the isolated
sub-analytics; stale-invalidate on content/model change; guard canonical queries against
inclusion.

---

## Item 15 — Installer must work cross-distro (Fedora failed; git check + all prereq messages are Debian-only)  [NEW]

**Verbatim:** "I just tryed to install the project on Fedora. ... ERROR: git is required.
Install it (Debian: sudo apt-get install git) and re-run. ... Can you make the installer
work on the most famous linux distros?"

**Surface:** scripts/bootstrap.sh (curl|bash entry) + install.sh (--template, venv/pip).

**Verified (read bootstrap.sh, no fix):**
- Line 37: `command -v git || die "git is required. Install it (Debian: sudo apt-get install
  git)..."` → Debian-only guidance; Fedora needs `sudo dnf install git`.
- Lines 38–42: python3.13 check → "On Debian/Qubes, run the TemplateVM step first... or
  install by hand" → Debian/Qubes-only. Fedora user hit git first; would hit python3.13 next.
- install.sh adds venv + pip (needs python3-venv [Debian splits it], pip/ensurepip) — not
  pre-checked; another cross-distro gap. `--template` path is Qubes/Debian-template-centric
  (audit). launch.sh already handles xdg-open/open cross-platform (good).

**Maps to existing:** [NEW] — cross-distro Linux prereqs are NOT in the backlog/CLAUDE.md.
The V0.1 RC mandate has a 3-OS CI matrix (win/mac/linux) but tests ONE Linux, not multiple
DISTROS.

**Recommended design:**
- DETECT distro / package manager: parse /etc/os-release (ID, ID_LIKE) + probe binaries
  (apt-get/dnf/yum/zypper/pacman/apk).
- For each missing prereq, print the CORRECT per-distro install command. Package-name map:
  git; python3.13 (+ venv + pip). Names differ (Debian `python3.13-venv` separate; Fedora
  `python3` bundles venv+pip; Arch `python`; openSUSE `python313`; Alpine `python3`).
- OPTIONAL CONSENTED auto-install: offer to run the detected package manager (sudo, NAMED
  packages only, explicit consent — never silent privilege escalation; matches the consent
  ethics).
- HARDER WRINKLE — Python 3.13 hard requirement: not in all distro repos (older Ubuntu LTS
  / Debian stable). Guide per distro (deadsnakes PPA / pyenv) OR adopt a DISTRO-AGNOSTIC
  Python provider (uv / python-build-standalone) to sidestep distro Python entirely — flag
  as a decision (small + clean; mild tension with no-bundling-large-things).
- CI: add Fedora/Arch/openSUSE (+ Ubuntu) installer SMOKE lanes (container) — distro-level,
  not just OS-level ("the matrix IS the definition of supported").

**Action for v0.1:** Make bootstrap.sh + install.sh distro-aware (detection + correct
per-distro commands minimum; optional consented auto-install); resolve the 3.13-availability
story (per-distro guidance or uv-managed Python); add distro smoke lanes to CI. Famous
distros to cover: Debian/Ubuntu/Mint/Pop, Fedora/RHEL/Rocky/Alma, openSUSE, Arch/Manjaro,
Alpine.

---

## Item 16 — Derived translation-analytics must count ONE translation per article (no double-count); scope to a chosen model+version, never auto-pick by size  [NEW] — refines Items 13/14; maintainer asked "are you sure?"

**Verbatim:** "Concerning translations... In case you keep multiple translations of the same
articles, are you sure you won't pollute translation enriched language focus derived
analytics ? for example, an article is translated twice, won't the keywords be accounted
for twice ? I think a simple solution to that would be to have only the latest translation
be accounted for, or the one made by the strongest models (we should be careful about this
as recent smaller models largely outperform older, larger models...)"

**Valid concern — YES.** Item 14 caches MULTIPLE translations per article (per model, for
comparison); if Item 13's derived sub-analytics joined ALL of them, an article translated
twice would double-count its keywords (and the two translations differ → distortion). So
the derived view MUST select exactly ONE translation per (article, target lang).

**My recommendation:**
- SCOPE the derived sub-analytics to a SINGLE (target-language, model_id+version+params) —
  "the corpus as translated by model X v.Y." By construction: one translation per article →
  NO double counting. Matches Item 13's per-run model picker (a run = one model = one
  derived corpus). Content-addressing (Item 14) already gives one translation per (hash,
  lang, model, params), so within a scope it's idempotent.
- Precedent: mirrors the Wikipedia living-source rule (analytics use the LATEST version by
  default, history beneath). Same here: ONE active translation feeds analytics; others stay
  cached, uncounted.
- DEFAULT when unspecified: LATEST (deterministic, simple) OR user-pinned — and EXPOSE/switch
  which model's translations are analyzed.
- HEED the caveat: NEVER auto-pick "strongest" by model SIZE (recent small models beat older
  large ones — size ≠ quality). Don't assert a model-quality ranking we can't justify
  (anti-fabrication). "Strongest" only if the USER defines a preference order; honest default
  = latest or user-pinned.
- Article-version interaction: select (CURRENT article content) × (chosen model); a re-scrape
  (new hash) → use the new version's translation, consistent with latest-version-default.
- TRANSPARENCY: the sub-analytics header states "keywords from N articles as translated by
  model X v.Y (+ M direct, UI-language originals)" — extends Item 13's direct/indirect
  provenance with model identity; reproducible.
- GUARD/TEST: extend the canonical-isolation guard (Item 14) with a
  one-translation-per-article-per-scope assertion so no derived view can double-count.

**Action:** Make the translated-corpus view + its sub-analytics MODEL-SCOPED (one translation
per article per chosen model+version; default latest/user-pinned; never size-based
auto-pick); state the model in the header; keep all translations cached but count only the
active scope; add the no-double-count test.

---

## Item 17 — Relocatable/external data store (one mechanism serves the 20GB-disk user + Tails + Qubes); Tails packaging  [NEW — architecture ALREADY supports it] — maintainer asked "stance / better idea?"

**Verbatim:** "Regarding the distros, There's a side project I'd like to work on, it consists
in making the app available for Tails. ... the app would have to be installed on the
permanent encrypted partition. However, the app's database could be stored elsewhere, on
another drive for example. This raises the question of having external drive / memory
support for the app's entire database (I'm not sure you've noted that database should
include everything the app downloads, right ? Including commodities, wikipedia, EVERYTING).
a user says : 'I have only 20gb here, and I'd prefer the app to store everything on my
external hard drive.'. I think addressing this will address also the specificity of Tails.
It would also address some of the specificities of Qubes. What's your stance on this, have
better idea ?"

**Surface:** src/paths.py (data_dir + OO_DATA_DIR), database/session.py, all state under
data_dir; install/packaging; Tails Persistent Storage; Qubes volumes.

**KEY FINDING (read src/paths.py + greps): the architecture ALREADY supports this.**
- `data_dir()` honors `OO_DATA_DIR` env override ("always wins"), else $XDG_DATA_HOME/...
- EVERYTHING the app stores is under data_dir(): corpus DB, wiki_dumps/, keys/,
  custody_log.db, backups (pre-restore-*.db), weather_context cache, scheduler settings/runs,
  keyword_filter, preflight/error/field-test/import jsonl, annotations/, app_settings. So
  "the database = EVERYTHING downloaded (commodities, Wikipedia…)" is ALREADY TRUE — one
  relocatable root. `OO_DATA_DIR=/mnt/external/oo` already stores it all externally (power-user).

**What's MISSING (the actual work):**
- USER-FACING location picker (first-run wizard + Settings) — today env-only.
- Safe MOVE/migrate tool (relocate existing data_dir; don't just repoint at an empty dir).
- REMOVABLE-MEDIA safety: identify volume by UUID/label (not fragile mount path); drive
  MISSING at boot → STOP loudly, NEVER silently re-init an empty DB on internal disk
  (split-brain); "safely eject" guidance; WAL/atomic-swap help vs yanked-USB but surface risk.
- FILESYSTEM warnings: FAT32 4GB file cap BLOCKS big wiki dumps; exFAT/NTFS/network-FS unsafe
  SQLite locking → recommend ext4/btrfs/APFS or a LUKS/VeraCrypt volume.
- ENCRYPTION note: corpus DB is SQLCipher-encrypted, but companion files (wiki_dumps/, caches,
  keys/) are PLAINTEXT → on external/removable media (seizable/copyable = exactly the at-rest
  threat model) recommend a LUKS/VeraCrypt volume or encrypt companions. Decide keys-with-data
  (self-contained) vs keys-on-host.
- PERFORMANCE: slow USB2 worsens the already-pathological SQLCipher perf (Item 11) — note;
  recommend USB3/SSD.

**Tails (the side project):**
- GREAT FIT: Tor-by-default → the app's Tor-first stance needs no extra setup; Tails users =
  the privacy-conscious investigative audience.
- Install on the PERSISTENT (LUKS) storage (system partition is amnesic/read-only); data_dir
  on the persistent partition OR external drive (maintainer's split). NEVER on the amnesic
  system partition.
- Debian-stable Python → the 3.13 requirement (Item 15) bites; uv-managed/standalone Python
  (Item 15) solves Tails too.
- HONEST: Tails enforces Tor → clearnet-for-Tor-hostile sources won't work (Tails doing its
  job; surface via T4 verdicts). Amnesic RAM wipe on shutdown HELPS the compromised-running-
  session threat.

**Qubes:** relocatable data_dir → corpus in a chosen private volume / data qube / USB qube;
aligns with the network-compartmentalization rulings. Same one mechanism.

**My stance:** STRONG YES — the maintainer's intuition is right: ONE mechanism (configurable
+ relocatable data_dir, already ~90% built) serves the 20GB-disk user, Tails, and Qubes. It's
mostly UX (picker + move tool) + safety guards, not a rebuild.

**Better ideas:** UUID/label volume identity (not mount path); "PORTABLE ENCRYPTED CORPUS"
framing (carry the drive between machines — ties to federation Items 9/10 + reliable-memory:
a copy outside any single machine); keys-with-data vs keys-on-host decision; uv-Python solves
Tails 3.13; loud-stop-on-missing-drive guard test.

**Action:** Add a GUI data-location picker (first-run + Settings) over the existing
OO_DATA_DIR/data_dir; a safe move/migrate tool; removable-media + filesystem + encryption
guards (UUID identity, loud-stop-on-missing, FAT32/exFAT warnings, LUKS recommendation); a
Tails install path (persistent storage + uv Python + data on persistent/external); document
Qubes data-volume placement.

---

## Item 18 — Reverse link: when corpus/article keywords mention a tracked commodity, surface the related commodity in the analysis window  [NEW direction on PLANNED substrate]

**Verbatim:** "I'd like that on search, when article's or corpus of articles keywords mention
any of our commodities, then a related commodity appears somewhere, maybe in on of the
existing tabs, or a new one."

**Surface:** analysis/corpus window (Group F) + search results; markets/commodities (Group G);
the curated symbol↔keyword-family table.

**Maps to existing:** the REVERSE of an already-ruled link. CLAUDE.md corpora system has
commodity→corpus ("commodity-click → the commodity's keyword-family corpus with the article
timeline OVERLAID on the price curve; co-occurrence NEVER causation; needs a curated
symbol→family seed table"). Group G "click a graph → analysis window." So the SUBSTRATE
(curated symbol↔keyword-family table) + the overlay chart + the corpora window are [PLANNED];
this CORPUS→COMMODITY surfacing direction is [NEW].

**Design / my light recommendation:**
- Detection: scan the corpus's keywords/families against the curated symbol↔keyword-family
  table; matches = related commodities.
- ONE table serves BOTH directions (DRY) — reinforces the need to actually BUILD the curated
  symbol↔family seed table (a known gap).
- Placement (recommend): a dedicated "Related commodities / Markets" sub-tab in the analysis
  window showing each matched commodity's price curve with the corpus's ARTICLE TIMELINE
  OVERLAID (the same ruled overlay, entered from the reverse direction — "what was written
  when the price moved") + mention/article counts. ALSO badge commodity-keywords in the
  Keyword tab (click → the commodity corpus = the forward direction). Reuses ooChart + the
  symbol↔family table.
- HONESTY guards: co-occurrence ≠ causation (state it — mentioning a commodity doesn't explain
  its price); precise matching to avoid false positives (gold the name vs metal, oil cooking
  vs crude, tin can vs metal — use the curated table + keyword kind entity/term +
  disambiguation); MULTILINGUAL table (copper/cuivre/cobre/Kupfer…) so foreign-language
  commodity mentions match (ties Item 12 + de-US-centring); n shown + early-corpus caveat.

**Action:** Build the curated, multilingual symbol↔keyword-family table (serves BOTH
directions); add a "Related commodities" surface in the analysis window (dedicated sub-tab
with the price-curve × article-timeline overlay + commodity-keyword badges on the Keyword
tab); enforce co-occurrence-not-causation + precise-match guards.

---

## Item 19 — Energy = Intelligence: massive commodity expansion + first-class energy analytics + global datacenter map  [PLANNED-partial + NEW + REPEAT-ledger-gap] — maintainer asked for an ambitious plan

**Verbatim:** "I'd like the list of commodities to be extend as much as possible. I'm not
sure how we can do that. And I'd like to incorporate energy related analytics. I'm not sure
how. We've already discussed this before, and I don't think it got through. Most of the
energy markets should be incorporated, we're in the era of Artificial intelligence, meaning
that despite compute capacity, energy IS intelligence. We need to come up with an ambitous
plan to address this. Still concerning the energy = intelligence, I'd like to have a tool
that aggregates datacenters in the world map, with size (energy, amount of GPUs / CPUs,
technology, oewner, and so forth"

**Concept memo developed (ambitious plan, maintainer request):**
`/home/user/concept_energy_and_datacenters.md`

**META:** energy analytics is a REPEAT the maintainer says "didn't get through" → per the
protocol a repeat = ledger failure; captured firmly now so it lands.

**Three asks + mapping:**
- (1) Extend commodities → [PLANNED] Group G "expand feeds" + parked OFFICIAL-STATISTICS
  ingestion. The "how" = add World Bank Pink Sheet (~70), IMF PCPS SDMX (~60), exchange open
  data (LME/CME/ICE/SHFE/MCX/DCE), UN Comtrade; ingest as controversial sources + vintages +
  comparability + official endpoints + per-continent coverage. Current ~28 via FRED
  (US-centric, Tor-hostile, dead series) is the ceiling. Each new commodity extends the
  Item-18 symbol↔family table.
- (2) Energy analytics THEME → [NEW/REPEAT] prices + production/consumption + capacity/mix +
  grid (ENTSO-E/EIA) + carbon + the AI-energy nexus; EIA/IEA/Ember/ENTSO-E/Energy Institute/
  OWID; SI units; provenance/vintages; corpus article-timeline overlay (Item 18).
- (3) Datacenter world map → [NEW flagship] geospatial registry on the existing map substrate;
  attributes (power MW / GPU-CPU / tech / owner / date / PUE) each marked disclosed vs
  estimated vs deduced (NEVER fabricated); sources = OSM seed + hyperscaler disclosures +
  grid/permit filings + CORPUS-DRIVEN WWW extraction ("deduced from N articles") + agency
  reports; sensitivity note (public-source-only, dual-use, provenance-forward, ToS/robots stand).

**Reuses:** world map, When×Where×Who, official-statistics design, Item-18 symbol↔family +
overlay, ooChart, corpora window.

**Action:** ALPHA slice = World Bank/IMF commodity breadth + an energy theme tab on those
feeds; V0.1+ flagship = the datacenter map (OSM + corpus extraction, honesty-tiered). Promote
the memo to a design doc; settle data-licensing + estimation-method + sensitivity-review.

---

## Item 20 — Should EVERYTHING (corpus + Wikipedia dumps + companion files) live inside ONE database file?  [REFINES 17/9/10/14] — maintainer asked honest opinion

**Verbatim:** "Regarding database and external hard drives, can't the databse contain
EVERYTHING, not only the corpus, but also the wikipedia and all companion files ? It would
allow user to simply copy and paste a database to allow another app's instance to import it,
and import would test for duplicates as we've already agreed ? I'm not sure about this, again,
your honest opinion is welcomed."

**My honest opinion: partly yes, partly no — and the part you actually want is already the design.**
- ALREADY TRUE: all STRUCTURED data (corpus, commodities, prices, events, keywords,
  annotations, settings, translations-as-derivations per Item 14) already lives in the ONE
  SQLite/SQLCipher DB file. "The DB contains everything except the big binaries" holds today.
- DON'T put multi-GB Wikipedia DUMPS (+ large caches) INSIDE the DB as BLOBs — solid reasons:
  - SQLite single-BLOB cap ≈ 2 GB → a 20 GB dump must be chunked (complexity).
  - SQLCipher re-encrypts page-by-page → the codec-drag lesson gets far worse on a
    dump-bloated file; everything else slows.
  - You LOSE the multistream SEEK (T14 dumpread: seek + one-block decompress to read one page
    without loading the whole dump) — the whole point of the dump format.
  - Hot/cold mixing: corpus DB is HOT (constant r/w), dumps are COLD (write-once), caches
    regenerable; one file drags cold/ephemeral data through every backup/VACUUM/merge.
  - Corruption blast radius + slow integrity-check/VACUUM/copy on a 50 GB+ encrypted file.
- The "copy-paste the DB" simplicity is partly ILLUSORY for a LIVE DB: copying a running
  SQLite file (WAL/locks/partial writes) risks a CORRUPT copy. The SAFE form of "copy the
  database" is a consistent snapshot = an EXPORT.
- ⇒ The ACTUAL goal (one copy-pasteable, self-contained, encrypted, dedup-on-import object)
  IS the oo-backup-2 ARTIFACT (already designed): ONE signed container bundling the corpus DB
  + companion files + (per the dumps ruling) wiki_dumps deduped by checksum + manifest;
  import = the additive merge engine (Items 9/10) which "tests for duplicates as agreed." It
  also CLOSES the Item-17 encryption gap (dumps/caches plaintext on disk → ride the encrypted
  artifact envelope) AND is the right unit for the federated merge.
- KEY DISTINCTION (keep two objects distinct): (1) the LIVE store (data_dir: hot DB + cold
  seekable dump files; relocatable per Item 17; LUKS for at-rest) vs (2) the PORTABLE artifact
  (oo-backup-2: one signed/encrypted/dedup-importable file = "copy-paste one thing"). Forcing
  #1 to also be #2's single monolith causes the pain; the artifact is the bridge. A data
  FOLDER for the live store is normal/good; one-file cleanliness is for transport (the artifact).

**Verdict:** keep structured data in the one DB (already so); keep dumps/large caches as
external seekable files in the (relocatable) data_dir; deliver "copy-paste + dedup-import" via
the oo-backup-2 artifact (the safe snapshot form), which already includes dumps
(checksum-deduped) and merges additively. Don't BLOB the dumps into SQLCipher.

**Action:** Don't move dumps/large binaries into the DB. Make the oo-backup-2 artifact the
first-class "share/copy your whole corpus" object (one file, signed, encrypted, dumps
included + checksum-deduped, additive dedup import) — surface it as the user-facing
"export/import everything" UX; keep the live data_dir hot-DB + cold-dumps split (Item 17).

---

## Item 21 — Crash/hot-unplug resilience: salvage-import that skips corrupted content + per-record fixity ("verified")  [PLANNED substrate + NEW salvage/recovery] — Tails hot-unplug; maintainer asked honest opinion

**Verbatim:** "Still concering database : imagine a user on tails need to clickly unplug their
USB / shutoff their machinne. You mentioned that it would create half finished writes and
other corrupting stuf.. Maybe we should have an approach so that while importing a database
[does] not take into consideration corrupted content, and that the current database marks
data that was successfully written as 'verified' ? I't be sad to loose a database because of
a hot unplug."

**Honest opinion + grounding (grep):**
- REASSURANCE (truth): SQLite WAL (on) already makes a single hot unplug NON-fatal in the
  normal case — recovery rolls back the incomplete transaction; you lose at most the last
  UNcommitted write, NOT the corpus. The real risk is removable/cheap media + non-journaling
  FS + write-back caches that lie about fsync. So the fear is largely mitigated by the engine;
  MEDIA is the weak link.
- (a) "import ignores corrupted content" → YES, buildable + PARTIALLY EXISTS: artifact import
  already hash-verifies each member and flags "sha256 mismatch (corrupted or altered)"
  (artifact.py:398-399); per-article content_hash already stored (merge.py dedup). Extend:
  SKIP corrupted records, import the intact ones (additive salvage), report the lost. For a
  damaged RAW DB, add a salvage path (PRAGMA integrity_check + .recover + hash-verify → import
  good rows).
- (b) "mark written data as verified" → reframe honestly: SQLite already guarantees COMMITTED
  rows are complete (atomicity), so a boolean "written-OK" flag is redundant with the engine.
  The useful form = the content_hash you ALREADY store → FIXITY (re-hash vs stored) tells you
  a row is intact at any time. "Verified" = "content matches its hash" = computed fixity =
  Item-8 "date of verification" anchor + Item-9 auto-fixity. Add a fixity audit (background +
  on import) flagging corrupted rows.

**Layered defense (recommended order):**
1. ROBUSTNESS config: WAL (have) + synchronous=FULL on REMOVABLE media (recommend;
   speed-for-safety, right for Tails USB) + busy_timeout (have, PR107) + small txns/frequent
   checkpoints + journaling FS (Item 17) + a prominent "Safe eject / flush now" control.
2. DETECTION: per-record content_hash (have) + fixity audit → know which rows are intact.
3. SALVAGE IMPORT: hash-verify each record, import only intact (additive), skip+report
   corrupted (extend the artifact path to skip-and-continue + raw-DB salvage).
4. RECOVERY UX on corrupt boot: NEVER silently fail/reinit — offer salvage (recover good rows
   → fresh DB) + restore from keep-3 snapshots / last artifact (extend torture-suite
   resilience to the live-store boot).

**Honest caveat (no fabricated security):** no software makes hot-unplug 100% safe on lying
hardware. Honest promise = "at worst you lose the last few seconds of writes, never the whole
corpus; if media corrupts pages we DETECT and SALVAGE the intact records." Backstops: artifact
export to a 2nd location (on Tails the USB may be the ONLY copy — encourage it) + the corpus
is reconstitutable from the web.

**Tails emphasis:** hot unplug is FIRST-CLASS there → synchronous=FULL default on removable,
the safe-eject control, periodic artifact export to a 2nd drive.

**Action:** Set synchronous=FULL on removable-media data_dir; add a fixity audit (per-record
content_hash verification, background + on-import) surfacing "verified" honestly; build
salvage-import (skip+report corrupted, import intact additively) + a raw-DB recover path;
corrupt-boot recovery UX (salvage + snapshot/artifact restore, never silent reinit); "Safe
eject/flush" control. Reuses content_hash + artifact sha256 verify + Merkle/provenance +
keep-3 snapshots.

---

## Item 22 — Offline OSM data as a geographically-anchored analytics substrate (+ map version/change-tracking)  [NEW — feeds Item 19; ties Item 8] — maintainer asked honest opinion

**Verbatim:** "Concerning the datacenter map. Imagine a user already downloaded entire pans of
mwm data, let's say from apps like Organic maps (free open source app that allows offline
download of openstreetmaps). Could we create a plugin to allow for data analytics to be made
with these files ? The file sizes are comparable to wikipedia downloads. I'd like you to think
as if disk space would not be an issue for that specific thing. Give me your honest opinion. I
think having a way to download maps and track the changes when downloading a new versino of it
could enable even further, geographically anchored analytics."

**My honest opinion: STRONG YES to the idea — with one format course-correction.**
- The CONCEPT (offline OSM as a rich geo-analytics substrate + version tracking) is powerful
  and is the natural DATA BACKBONE for Item 19 (datacenters/energy), the gazetteer, When×Where×
  Who place resolution, and the temporal map.
- COURSE-CORRECT the FORMAT: DON'T target Organic Maps' MWM files — MWM is a rendering-
  optimized, generalized, LOSSY binary (built for fast mobile draw/routing), hard to parse
  outside Organic Maps and stripped of rich OSM tags. The "reuse what the user already
  downloaded" appeal is weak because MWM ≠ analyzable.
  - Target OSM PBF / standard OSM extracts: FULL tagging (every node/way/relation + tags +
    multilingual names), open documented format, mature tooling (osmium/pyosmium, SpatiaLite/
    R-tree, GDAL). Source: Geofabrik per-country/region extracts (robots-OK), downloaded by
    the app itself (same UX as wiki dumps) — not reused from Organic Maps.
- WHY it's powerful: datacenters (OSM `man_made=data_center`) seed Item-19 offline+globally;
  energy infra (`power=plant/substation/line`, pipelines, ports) = geographic backbone for the
  energy theme; gazetteer enrichment (every place name in every language → better place
  extraction + temporal-map mention layer + corpus place→feature resolution with coords/admin
  hierarchy/nearby infra).
- VERSION/CHANGE-TRACKING (2nd idea) = PERFECT fit with Item 8: OSM is another LIVING source
  (like Wikipedia/law); Geofabrik publishes extracts + OSC diffs. New version → diff → record
  geographic changes in the Item-8 substrate (typed: geographic-revision). Enables NOVEL
  analytics: new datacenter/power-plant/construction tags appearing over time ("what got built
  where, when") that CORROBORATE corpus signals (co-occurrence ≠ causation).
- HONEST constraints (AMENDED by Item 23 — maintainer prefers RELIABILITY over speed, NO
  feature-class cap): ingest ALL OSM feature classes + tags (no curated subset — feature
  classes are "like keywords", avoid capping; dynamic if ever needed); accept slowness and
  SURFACE it ("crunching" indicator + task-manager job). Efficiency comes from INDEXING the
  COMPLETE set (SpatiaLite R*Tree) + incremental/lazy compute + optional regional processing
  by USER choice — never by dropping data. "Ignore disk" granted; hardware (RAM/cores) is
  scalable on the user's side. Keep raw PBF as cold files (Item 20). OSM provenance =
  crowd-sourced contributors (changesets carry contributor+timestamp → auditable) — NOT ground
  truth; mapping LAG means an OSM edit date ≠ real-world change date (provenance ≠ veracity).

**Action:** Build an opt-in geographic-data module ingesting OSM PBF extracts (Geofabrik, via
the guarded fetcher, task-manager jobs) → selective SpatiaLite spatial layer feeding the
gazetteer + Item-19 datacenter/energy seeding + place resolution; version + OSC-diff change-
tracking via the Item-8 substrate (typed geographic-revision); regional/feature-class scoping
for compute; OSM-provenance + mapping-lag caveats. NOT MWM.

---

## Item 23 — Map-analytics UI: complete world-map REVAMP + reliability-over-speed (no feature-class cap) + UI propositions  [NEW; GATED — needs maintainer input before implementation]

**Verbatim:** "About compute limitations, I'm not sure I agree. I can increase the amounts of
ram and cores of my VM. Plus: if it's slow, the UI can let the user now it's crunching numbers
in the back. I don't want our app to limit geographic analytics to a single list of feature
classes. They're like keywords, I'd try to avoid capping. We're in a tradeoff : reliability vs
speed. I prefer reliability. We need to think of a smart UI to power up user experience with
this addition (map analytics). I'm not sure how we'll get there yet. Make propositions for now.
The current app's world-map quite un-useful now, so it needs a complete revamp. I'm not sure
the parallel session tried to address that, but we'll see. Mark that this needs additional user
input before entering implementation. The backbone, we agree. For example, if this is
successfully implemented, there should be a simple search engine like in regular map software
through a dedicated UI. Maps could also appear like an additional tab in search results when
the corpus or article contains geographic data, etc."

**Directives recorded:**
- COMPUTE: maintainer DISAGREES with my feature-class scoping → reliability > speed; NO
  feature-class cap (feature classes "like keywords", avoid capping, dynamic if ever needed);
  hardware (RAM/cores) scalable on user side; surface slowness honestly ("crunching" indicator).
  AMENDS Item 22. (Accepted; my scoping caveat withdrawn — indexing the COMPLETE set ≠ a cap.)
- The current world-map is "quite un-useful" → COMPLETE REVAMP needed (parallel session may/may
  not have touched it — uncertain from here; verify later).
- **GATE (binding):** the map-analytics UI NEEDS ADDITIONAL MAINTAINER INPUT BEFORE
  IMPLEMENTATION. Backbone (OSM PBF ingest, Item 22) = AGREED/GO; the UI/UX layer = PROPOSE-ONLY
  now; do NOT implement until the maintainer gives input.

**UI PROPOSITIONS (maintainer asked "make propositions"; NOT for implementation yet):**
- A. Revamped MAP TAB — a real slippy map over the OSM-derived spatial layer (local
  vector/raster), with the ruled in-map overlay controls (Google-Maps "inside the map"): layer
  toggles, the shared TIME-SCOPE control, legend, and a MAP SEARCH bar (geocoding — "like
  regular map software", their example) federated with omnisearch.
- B. MAP as a conditional SUB-TAB in the analysis/corpus window (their example) — appears when a
  corpus/article contains resolved geographic data (like Item-18 related-commodities); plots the
  corpus's places + density + timeline + feature links.
- C. TEMPORAL × SPATIAL fusion — the map carries the time dimension (time-scope control); scrub
  time to animate corpus mentions AND OSM changes (Item 22 diffs): "what was written / what
  changed, where, when."
- D. FEATURE inspection — click a feature → OSM tags + provenance + change history (Item 8) +
  related corpus articles (bidirectional: feature↔corpus).
- E. GEOGRAPHIC corpus entry — draw a region / pick an admin area → the corpus of articles
  mentioning places there (a SPATIAL entry into the corpora system).
- F. HONESTY layers — every analytics layer states method/provenance/caveat (OSM crowd-sourced,
  mapping lag, deduced mentions "from N articles never confirmed"); co-occurrence ≠ causation; n
  shown; legend long-form in hover bubbles (invariant #17).
- G. PERFORMANCE-honesty UI — big ingest/query shows a "crunching" indicator + task-manager job
  (reliability-first, slowness surfaced not hidden) — directly per the maintainer.

**Action:** Backbone (Item 22) proceeds. Map-analytics UI = PROPOSALS ONLY; do NOT implement
until the maintainer reviews and adds input. Revamp the existing (un-useful) world-map as part
of this. Reliability over speed, no feature-class cap.
