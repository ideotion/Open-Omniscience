# Field-Test Ledger — 2026-06-15 session

Continues the 2026-06-14 intake (`../field-test-2026-06-14/`). This session is
intake **+ implementation** (the maintainer said "continue implementing"). Each
item records the verbatim observation, the mapping to existing rulings/docs, what
**shipped this session**, and what **remains**.

Legend: [PLANNED] already ruled · [NEW] net-new · ✅ shipped here · ⏭ remaining.

---

## Item A — Installer must not prompt for a passphrase; defer DB init to first launch; auto-launch the app  [PLANNED — Item 1 / Group D]  ✅

**Verbatim (07:11):** "the terminal installer still asks for a passphrase. I'd
like the installer not to ask this. I think it's linked to database
initialization. Can't the database be initialized later? This could be done
during the app's launch. … I'd like the app to launch automatically when
(promptless) the installation ends. Remember the order of the first
initialization screen: ask for language, then a screen with terms and
conditions, then ask for passphrase."

**Maps to:** field-test-2026-06-14 **Item 1** (installer no-DB-init / no-passphrase
+ auto-launch) and **Item 2** (first-launch wizard order language → T&C →
passphrase); BACKLOG_GROUPED **Group D**; CLAUDE.md "INSTALL-FLOW NEXT SLICE".
Was ruled, not yet shipped.

**✅ Shipped this session (`install.sh`):**
- `init_database()` no longer prompts. It initialises **only** when the choice is
  already made — an existing store, or an explicit headless env choice
  (`OO_DB_PASSPHRASE` / `OO_DB_PLAINTEXT`, handled by `_try_db_init`). In every
  other case it **defers silently** to the app's in-browser first-launch setup.
  The interactive `_prompt_db_protection` function was removed entirely (the env
  vars are the only headless fallback, per the ruling).
- `maybe_launch()` ends an interactive install **inside the running app**: it
  `exec`s `scripts/launch.sh console` (starts the loopback server, waits for
  health, opens the browser at http://127.0.0.1:8000). Interactive only — never
  `--unattended` / `--appvm` / CI / `OO_SKIP_PIP`; opt out with `OO_AUTOLAUNCH=0`.
  Zero-network / airplane-mode boot preserved.
- Deferral is safe by construction: encryption is on by default, a blind init on a
  fresh store would crash (field-tested 2026-06-12), and the deferred-startup path
  seeds sources at the first unlocked boot. `/api/system/create-db` + the in-app
  `/unlock` create flow already own the passphrase choice.

**Verified:** `bash -n` clean; `tests/test_installer.py` green (incl. the
curl|bash no-leak path and unattended-launcher tests); full suite 1165 passed.

**⏭ Remaining (Item 2, larger — own slice):** the first-launch **wizard** with the
ruled order **language → Terms & Conditions (accept) → passphrase**. Wizard slice 1
(language + finish) shipped #150; the **T&C step + authored ×12 T&C content** and
the **encryption-choice step** are the remaining wizard slices. The installer now
hands straight to that in-app setup, so the order the maintainer wants is owned by
the app, not the terminal.

---

## Item B — One search entry (the top one); icon-only, no "Ctrl K"; translate the hover; Enter → analysis window; remove the Search sidebar tab  [PLANNED — Group E/F + "SEARCH = ONE CENTRAL ANALYTICAL TOOL"]  partly ✅

**Verbatim (07:19):** "The app's UI still has two search entries. I'd prefer that
there is only one. The top one. … this top search should be filled with text such
as 'Search everything - data, tools, actions, docs…' it takes too much space.
Remove the Ctrl K information. Just a search icon. Instead of having a bubble while
hovering … saying 'command palette' (not translated by the way!), you should
probably put there … (ie. Search everything - articles, dates, locations,
settings, etc.). Whatever the user searches, clicking 'enter' opens a search
related window with all the agreed subtabs … advanced search tools and the list of
results. There should not be a search button in the tabs. The top icon will
suffice."

**Maps to:** BACKLOG_GROUPED **Group E** (minimal top bar; remove visible "Ctrl K";
bigger always-on search) + **Group F** (Enter → corpus-of-articles analysis window
with sub-tabs + Advanced-search tab — "the single most-requested piece"); CLAUDE.md
"SEARCH = ONE CENTRAL ANALYTICAL TOOL" and "UI SHELL REDESIGN §4/§5".

**✅ Shipped this session (chrome, the safe/ungated part):**
- Removed the visible **`Ctrl K`** badge from the top omnibar (the Ctrl/⌘-K
  shortcut still works; it's just no longer shown).
- The omnibar **hover bubble** (invariant #17 `#oo-tip`, fed by the translated
  `title`) was **untranslated English "Command palette"**. Replaced with
  **"Search everything — articles, dates, locations, settings, etc."**, keyed and
  translated ×12 (RTL Arabic included; AI-drafted, flagged for native review).
  The omnibar `aria-label` now matches.
- Killed the **last** untranslated "Command palette" string: the palette dialog's
  `aria-label` is now the keyed **"Search everything"** ×12. `--audit-chrome` is
  clean of "Command palette"; i18n coverage stays 100% (610 keys ×12).
- The visible placeholder already read "Search everything — data, tools, actions,
  docs…" (keyed) — kept, so the surface layers a short placeholder + a longer hover.

**Verified:** `node --check` of the inline script block OK; all 12 locales
JSON-valid; i18n `--min 100` green; `--audit-chrome` clean; full suite 1165 passed.

**⏭ Remaining (the flagship — own dedicated PR, GATED):**
1. **Enter → the analysis window** with the agreed sub-tabs (keyword · mindmap ·
   link · source · When/Where/Who · sentiment · related) **+ the Advanced-search
   tab** (filters, sort, dates, the result list). This is the Group F flagship /
   keystone #4; partially built (palette T13 s1; keyword→corpus window T10 s1 =
   Trend/Articles/Links only).
2. **Remove the Search sidebar tab** (`data-tab="search"`) so only the top icon
   remains. **This is the "two entries → one" the maintainer wants**, but it is
   **gated by the project's own rule**: the Search tab is removed only **after** the
   Enter→window absorbs **every** Search-tab capability — Boolean query, Source /
   Language / From / To filters, Export CSV/JSON, **Methods appendix**, **Synthesize
   results**, **Export signed evidence** ("never silently lose a tool", the Desk
   lesson). Those live in `#tab-search` today. So the tab stays until (1) lands;
   removing it now would drop signed-evidence export and the methods appendix.

**Recommendation:** do (1)+(2) as the **next** PR (the promoted Group F flagship);
the chrome shipped here is the down-payment.
