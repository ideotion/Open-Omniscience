# Next version — action plans for Themes 2–5

> **North star.** The app is `0.0.6` pre-alpha with strong foundations and **no
> real-world validation**. The next version does not chase "more features"; it earns the
> right to be *seen and safely used* by the people who most need it — investigative
> journalists, including those at risk — on the road to a defensible `0.1` public alpha.
> The themes below are **safety, usability, sense-making, and governance**. Each plan is
> phased; the **first increment of each ships in this branch** and is marked ✅ below.
>
> **Discipline that constrains every plan:** local-first (no server, no accounts, no
> telemetry); surface signals, never verdicts; **never ship fake security** — a feature
> that *claims* a protection it does not deliver is worse than its absence; and hold the
> dual-use red lines in [GOVERNANCE.md](GOVERNANCE.md).

---

## Theme 2 — At-risk-user safety

**Why.** An investigative journalist may work under surveillance, face device seizure,
or endanger a source merely by *announcing interest* in a target. The same architecture
that makes the app private (local-first) must be extended so that **the data at rest,
the data in transit, and the act of researching itself** can be protected — honestly,
with each guarantee and its *limits* stated plainly.

**The honest-crypto rule.** Every protection reuses audited primitives (the
`cryptography` AES-256-GCM + scrypt scheme already used for custody keys) and is
labelled with exactly what it does and does **not** guarantee. We never imply anonymity
or at-rest secrecy we cannot deliver. Full-disk encryption remains the host's job
(Qubes/LUKS/Tails); we add *application-level* protections on top, not instead.

### Phase 1 (✅ ships now)
- ✅ **Encrypted, portable backup.** Export the whole corpus as a single
  passphrase-encrypted file (AES-256-GCM, scrypt-derived key); restore by passphrase.
  A wrong passphrase fails loudly; the format self-describes its KDF params. *Use:* carry
  or stash the corpus across a border or a hostile network without exposing it.
- ✅ **Panic wipe.** A deliberate, confirmed action (`open-omniscience panic --yes`, and a
  guarded GUI control) that best-effort-overwrites then deletes the data dir (DB, keys,
  caches), honestly noting that on SSDs/CoW filesystems only full-disk encryption
  guarantees unrecoverability.
- ✅ **Ephemeral mode.** `OO_EPHEMERAL=1` / `--ephemeral` runs against a throwaway temp
  data dir that is wiped on exit — nothing persists. *Use:* a quick, leave-no-trace look.
- ✅ **Protected fetch.** A per-app *fetch mode*: **Transparent** (default — identifying
  UA, robots fail-closed, for broad ethical collection) vs **Protected** (route through a
  user-supplied proxy, e.g. Tor at `socks5://127.0.0.1:9050`, and send a generic UA), so a
  journalist investigating a powerful target need not announce themselves from their real
  IP. The UI states the tradeoff honestly: we *use* your proxy and *verify it is set*; we
  **cannot** guarantee anonymity — you must run and trust the proxy yourself.

### Phase 2 (planned)
- **Encrypted-at-rest live DB** (SQLCipher or equivalent) behind a session passphrase,
  only if it can be done without a fragile native dependency and *honestly* audited.
- **Decoy / hidden-volume** and **duress-passphrase** patterns — *only* if they can be
  made genuinely sound (these are easy to get dangerously wrong; default to "don't ship
  unless provably correct").
- **First-class Tails / Qubes-Whonix integration** (Tor-routed Protected mode by default
  in those environments), with a hardened distribution profile.
- **Auto-lock / inactivity wipe of in-memory secrets.**

**Non-goals / red lines.** No silent network egress; no cloud backup; no telemetry; no
claim of anonymity. Protected mode is opt-in and never the silent default (announcing a
bot is the *ethical* default for general collection).

**Risks & self-criticism.** Crypto/anonymity are easy to get subtly wrong, and false
assurance endangers the very users we mean to protect. Mitigation: reuse audited
primitives, label limits, keep Phase-2 deniability features behind a high "provably
correct" bar, and seek an external review before the `0.1` alpha.

---

## Theme 3 — Usability, accessibility & onboarding

**Why.** An accountability tool that only experts can install, or that excludes disabled
journalists, fails its own values. Reach matters: the audience is global and non-technical.

### Phase 1 (✅ ships now)
- ✅ **Accessibility pass on the GUI:** a skip-to-content link; ARIA landmarks
  (`navigation`/`main`/`complementary`); `aria-label`s on icon-only buttons; `aria-current`
  on the active nav; an `aria-live` region for toasts; visible focus rings; and
  `prefers-reduced-motion` support. (Static a11y; a full screen-reader audit is Phase 2.)
- ✅ **Gentler first-run / empty states:** the briefing, search and library empty states
  now *teach* — one clear next action ("Seed sources & run a first ingestion") and a plain
  explanation of what will happen, so a new user is never staring at a blank panel.
- ✅ **i18n completeness report** (`scripts/i18n_report.py`) so translators can see exactly
  which strings each locale is missing; new Safety/Lineage chrome strings added to the
  maintained locales (en/de/es/fr).

### Phase 2 (planned)
- **One-click packaging** for non-technical users (AppImage/Flatpak) — clearly *separate*
  from the hardened Qubes build, with the security tradeoff documented (convenience ≠
  maximum safety).
- **Full screen-reader + contrast audit** against WCAG 2.1 AA; keyboard-only end-to-end.
- **Finish the stub locales** (ar, zh, ru, ja, hi, bn, pt, id) with reviewed translations,
  including RTL polish for Arabic.
- **Guided tours / contextual help** for the analytical tabs.

**Risks & self-criticism.** Packaging-for-everyone pulls against the Qubes security
center; the resolution is *two clearly-labelled distributions*, not one muddled compromise.
I cannot verify screen-reader behaviour from here, so Phase 1 is honest static a11y, not a
claim of full accessibility.

---

## Theme 4 — Content sense-making & the publishing loop

**Why.** The honest "more useful" is **not** more detectors. It is: help users get *good
coverage in*, make *sense* of it, and get *publishable, verifiable journalism out* — all
in the structural/measurable lane, never as verdicts.

### Phase 1 (✅ ships now)
- ✅ **Story lineage ("trace to the primal source").** For a near-duplicate cluster, order
  by earliest publication, detect **wire attribution** ("according to Reuters/AFP/AP/…",
  "Reuters reported") and explicit citations, and present **primary → first report →
  echoes** as a chain. A briefing **Story-lineage** card surfaces it. Honest caveat:
  *"earliest we saw" ≠ the truth*; it shows lineage and structure, the human judges.
- ✅ **Coverage advisor.** A gentle, dismissible **Diet imbalance** signal: when recent
  collection (or a result set) is dominated by one owner/country/language, surface the
  concentration *with* a few concrete under-represented sources from the catalog to
  consider — *suggestive, explained, overridable; never enforced* (§3 of the design memory).

### Phase 2 (planned)
- **Publish-ready bundle:** the card→draft→Markdown export, plus an attached **signed
  evidence bundle** of every cited article and the relevant annotation bundle — so an issue
  ships *with* its reproducible receipts.
- **Cross-language divergence** and **deal-lineage** cards (existing engines, new framing).
- **Reading ergonomics:** a calmer, faster triage/reading flow for the briefing.

**Risks & self-criticism.** Lineage is genuinely hard (event-clustering + citation tracing);
Phase 1 starts with the cheap, honest signals (wire/near-dup/earliest-timestamp) and says so,
rather than over-claiming "the original source". I must keep "more useful" from smuggling in
unreliable AI fact-checking — the project's refusal to fake detection is its integrity.

---

## Theme 5 — Governance & acceptable use

**Why.** If the app gets popular it becomes a target and a dual-use risk. A short, public
statement of *what it is for*, the *red lines*, and the *governance intent* is cheap and
disproportionately protective — and is itself an ethical act.

### Phase 1 (✅ ships now)
- ✅ **[GOVERNANCE.md](GOVERNANCE.md)** — the statement of purpose, the **dual-use red
  lines** (no individual-person tracking / face-voice recognition / private-message
  ingestion / automated trust score / central server / silent filtering — *absent by
  construction, not configurable*), the legal/ethical posture, funding-independence intent,
  and a misuse-resistance note. Registered in the in-app docs reader.
- ✅ **Red-lines guard test** — a CI test asserting the forbidden capabilities are absent
  from the codebase (no face/voice-recognition or individual-tracking modules), turning the
  promise into an enforced invariant alongside the existing no-trust-score guard.

### Phase 2 (planned)
- **Independent governance** (multi-maintainer, transparent decisions) before any funding.
- **An external security & ethics review** ahead of the `0.1` public alpha.
- **A clear contribution covenant** aligning contributors with the red lines.

**Risks & self-criticism.** A red-lines test can only check for *known* forbidden patterns;
it is a tripwire, not a proof. The real guarantee is culture + review. Stated plainly so no
one mistakes the test for completeness.

---

## Sequencing & what ships in this increment

This branch delivers **Phase 1 of all four themes** — a coherent foundation, each piece
tested and honestly labelled — without over-claiming any theme as "done". The phased
remainder, the validation pilot (Theme 0 from the strategy memo), and the external audit
are the path to the `0.1` alpha. Nothing here weakens the existing guarantees; everything
new is opt-in, reversible, and stated with its limits.
