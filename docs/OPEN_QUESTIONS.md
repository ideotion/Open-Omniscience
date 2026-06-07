# Open Questions & Design Notes (for the next work session)

> **Read me first if you're picking this project back up.** This file captures
> in-flight design discussions and decisions that were *not* finalised before a
> session ended, so the thinking isn't lost. Each item states the goal, my current
> understanding, the open questions, and (where useful) a proposed direction —
> clearly marked as a proposal, not a decision. Resolve an item → fold it into the
> real docs and delete it from here.

Last updated: 2026-06-07.

---

## 1. Chain of custody: make it dummy-proof, and automate it into the background

**This is the big one.** Status: **discussed, not yet designed or built.**

### What the user asked for (paraphrased, preserve the intent)

The **Chain of custody** tab is currently expert-facing. The user wants two things:

1. **Make it understandable and dummy-proof for novices.** *Why* chain of custody
   exists and *how* to use it should be obvious from the interface — either
   self-evident or interface-guided (onboarding, plain-language explanations,
   guided flow), not requiring the user to read `CHAIN_OF_CUSTODY.md`.

2. **Automate it / move it to the background.** The framing the user gave:
   *"Investigative journalists don't want to tamper with the boring stuff; they
   want their sources to be automatically trustworthy. This app and its database
   could become 'the' trustworthy source — but only if chain of custody is
   guaranteed, automated, and in the background."*

In other words: chain of custody should become an **always-on guarantee of the
corpus**, not an optional panel the user has to operate. The aspiration is that
"it's in Open Omniscience" comes to *mean* "its provenance and integrity are
cryptographically established."

### My current understanding of the goal

- Every ingested item should be **automatically** entered into the signed,
  hash-chained custody log at capture time — no manual step.
- The UI should mostly **report a reassuring, plain-language trust status**
  ("✓ All 12,431 items in this corpus are signed and tamper-evident") rather than
  expose knobs. Advanced controls move into an "Advanced" disclosure.
- Verification, anchoring, and export stay available but become secondary.

### The real tension to resolve (important — don't just bulldoze it)

The existing design made some of this **deliberately opt-in for honest reasons**,
documented in `docs/CHAIN_OF_CUSTODY.md`:

- **Auto-log on ingest is off by default** because each entry has a real
  **per-article signing cost**, and turning it on is framed as "an explicit
  evidentiary choice, not silent always-on behaviour." It is also **fail-open** (a
  custody error never breaks ingestion).
- The doc explicitly lists **"no always-on background integrity daemon"** under
  *"What we deliberately did not build."*

So "automate it / always-on background" **directly revisits two prior deliberate
decisions.** That's allowed — the product vision may have moved — but the next
session should reconcile this consciously, not silently contradict the doc. The
honesty invariant ("never show a trust light you can't back up") must survive any
redesign: an automated green "everything is signed" badge must be *true*, including
through restores, imports, and partial/failed signings.

### Open questions for the user (answer these next session)

1. **Default on?** Should auto-log-on-ingest become the **default** for new
   installs (a setup choice during `install.sh` / first run), or stay opt-in but
   far more prominent and one-click?
2. **Performance budget.** Signing every item costs CPU/time at ingest. Is a small
   per-article cost acceptable always-on, or do we want **batched/Merkle-tree
   signing** (sign a batch root per scheduler run) to keep it cheap? Batching
   changes the granularity of the proof — acceptable?
3. **What exactly is "guaranteed"?** Integrity + provenance + local time are cheap
   and local. Independent *time* proof needs **OpenTimestamps (network egress,
   privacy trade-off)**. Should the "trustworthy" guarantee include third-party
   time by default, or is local-time-by-default fine with OTS as an opt-in upgrade?
   (Note the privacy warning: OTS reveals IP/timing.)
4. **Imports & restores.** A restored or CSV-imported corpus didn't come through
   *our* ethical fetch path. How should the trust badge represent items whose
   custody starts at import rather than original capture? (Proposal: an honest
   "imported, integrity-from-here" provenance class — never claim original capture
   we didn't witness.)
5. **Novice UI shape.** Is the desired end-state a single **trust banner + "verify
   this corpus" button**, with everything else behind "Advanced"? Or a short guided
   wizard the first time?
6. **Scope of "source."** Reconfirm: in this tool a "source" is a *news outlet*,
   not a confidential human source. The trust claim is about *our record of public
   material*, not source protection. Keep messaging from over-promising.

### Proposed direction (NOT yet approved — a starting point)

- Flip the mental model: custody is a **property of the corpus**, surfaced as a
  calm trust status, with the panel's knobs demoted to "Advanced."
- Default new installs to **auto-log on ingest = on**, using **per-scheduler-run
  batched Merkle signing** to keep the cost negligible, with local time by default
  and OpenTimestamps offered as a clearly-explained, privacy-warned upgrade.
- Add **first-run onboarding copy** on the tab: a one-paragraph "what this is and
  why it matters to a journalist," a live trust badge, and a single **"Verify
  entire corpus"** action.
- Represent imported/restored items with an **honest, distinct provenance class**
  so the badge never overclaims.
- Update `docs/CHAIN_OF_CUSTODY.md` to record the reversal of the "no always-on
  daemon / opt-in only" stance *with its rationale*, preserving the honesty
  invariants.

**Before building:** get the user's answers to Q1–Q6 above (use `AskUserQuestion`),
because several touch deliberate prior decisions and a performance/privacy budget.

---

## 2. Language pickers grouped by continent — done for Wikipedia; note on the rest

**Status: largely done.** The user asked to sort *all* language pickers (article
languages, Wikipedia languages, etc.) **by continent** to ease scrolling long
lists, then to **add type-to-filter search** and **more editions**.

- **Done:** the **Wikipedia offline-baseline picker** (the only real `<select>` of
  languages) is now grouped into `<optgroup>`s by continent of origin
  (`src/wiki/languages.py` gained a `region` field + `languages_by_region()`;
  `/api/wiki/languages` returns a `groups` form; the UI renders optgroups). The
  curated catalogue was expanded to **~147 editions** covering all continents
  (incl. Americas/Oceania and a "Constructed" bucket for Esperanto et al.), and the
  picker gained a **type-to-filter box** (matches name, autonym or code) rendered as
  a list box.
- **Deferred (needs a decision):** a *fully dynamic* list of **all 300+ Wikimedia
  editions** pulled live from the dump server / sitematrix. Not done because it adds
  **runtime network egress**, which conflicts with the offline-first default — the
  ~147 curated editions plus the always-available free-text code entry already reach
  any edition. Revisit if comprehensive auto-discovery is wanted despite the egress.
- **Open:** the other "language" inputs — **Search → Language** (`f-lang`),
  **Sources → Language** filter (`src-language`), and **Ingest/scheduler →
  Languages** (`sch-langs`) — are currently **free-text inputs, not dropdowns**, so
  there's no list to group. 

  **Question for the user:** do you want those converted into proper
  continent-grouped dropdowns too (populated from the same region-aware catalogue)?
  That's a reasonable follow-up but it's a behavioural change (free text → picker)
  and the scheduler field accepts multiple comma-separated codes, so it'd need a
  multi-select. Left as-is pending confirmation.

---

## How to use this file

- Add an entry whenever a session ends with an unresolved design decision.
- Keep entries action-oriented: **Goal → Understanding → Open questions →
  Proposal**.
- When resolved, migrate the outcome into the canonical docs and remove the entry.
