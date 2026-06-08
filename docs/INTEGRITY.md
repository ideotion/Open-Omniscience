# Source integrity & anti-amplification

> **Status:** `0.06` Phase C — shipped and tested. The keystone of the intelligence
> layer (FUTURE_DEVELOPMENTS §6). Pairs with [`BRIEFING.md`](BRIEFING.md) and
> [`ANNOTATIONS.md`](ANNOTATIONS.md).

The other tools surface signals; **this one decides whose signal counts** — *without
becoming an arbiter of truth*. It is the answer to the "garbage in" problem.

## The surprise: treating every source equally is **not** neutral

Trending, prominence, synchrony and "what's covered" all **count outlets and volume**.
So equal-treatment-of-outlets, applied to a volume metric, has a built-in bias:
*whoever produces the most wins.* A well-resourced actor who spins up 40 outlets (or
troll farms, or content mills) converts capital directly into apparent consensus and
**dilutes** honest single-source stories into nothing. Doing nothing is not neutral —
it subsidises the flooder.

The resolution is not to *score* sources. It is to define neutrality over the right
**unit**: equal treatment of *independent actors weighted by the new information they
contribute*, not of *outlets*. **Counting sock-puppets as voices is a measurement
error, not neutrality.**

## What is measured (and what is forbidden)

We live strictly in the **allowed** half of the §6 distinction:

- **(A) Veracity / quality scoring** — "is this source truthful / good?" — is
  **forbidden to automate.** It bakes the scorer's worldview into a false-objective
  number and *will* eventually score a good-but-unusual source down too.
- **(B) Authenticity / structure signals** — "is this source what it claims to be? one
  node of a coordinated network? does it *originate* or only *echo*? is its output
  within human capacity? is it transparent about who runs it?" — these are, to a real
  degree, **measurable structural facts.** All design lives here.

### The shared engine (`src/signals/`)

| Primitive | Measures | Powers |
|---|---|---|
| `concentration` | Gini + top-N share | ownership/diet concentration, prominence |
| `near_dup` | MinHash + LSH near-duplicate clusters | echo / syndication detection |
| `coordination` | actor graph from near-dup + lockstep timing + shared host | actor-collapse |
| `novelty` | share of word-shingles new to the corpus | originates-vs-echoes weighting |

All four are **pure** (no DB, no network), property-tested, and carry method + caveat.

## Anti-amplification is **user-guided** (propose → you dispose)

Anti-amplification is **never** a silent transform the app performs and you merely
*undo* — that would make the app the arbiter §6 forbids.

- **Default = "equal but aware."** The raw equal-treatment view is the baseline; a
  coordinated flood is **annotated on it** (the *echo-chamber* card), not collapsed.
- **You apply a collapse**, per-cluster or globally. Only then does a coordinated
  network fold into **one voice** in any count that measures consensus (how many
  independent voices carry a story).
- **Every applied collapse stays flagged and reversible.** One click expands it to its
  members; reverting reproduces the raw equal counts **exactly**. *No collapse is ever
  applied without your explicit action* — enforced by a test.

This is the **Source integrity** tab: *Scan for coordination* lists proposed actors
with their evidence (shared text, lockstep timing, shared host); *Apply collapse* /
*Expand (revert)* are yours to choose. The echo-chamber cards on Home carry the same
*Collapse to one actor* action.

## The source profile — measured dimensions, **no composite score**

Per source, a panel of *measured* signals — and **deliberately no single trust
number** (the forbidden "B"). A 0–100 score is false precision over incommensurable
dimensions, Goodhart-gameable, a single point of capture, and *will* misclassify
small / foreign / new / dissident sources. The ban is enforced in code (the profile
returns `no_composite_score: true` and a test asserts no aggregate `*score*` key).

Dimensions (each with its own method + caveat):

- **Coordination** — actor membership, with whom, how many shared stories.
- **Novelty** — does this source originate or mostly echo? (relative to *your* corpus).
- **Output capacity** — articles/day vs the corpus median (a *question*, not a verdict;
  wire agencies and big newsrooms are legitimately prolific).
- **Transparency** — country, language, ownership/leaning tags (reputational,
  contestable, editable), and the operator-set `reliability_score` (not computed here).
- **Track record** — what this source has contributed to your corpus.

You weight which dimensions matter into *your* view — off by default, reversible, the
raw equal view always one click away.

## New briefing cards from this layer

- **Echo chamber** (overtold) — one story carried across N coordinated sources.
- **Lonely signal** (undertold) — a substantive single-source story that did not echo.
- **Capacity implausible** (investigate) — a source publishing far above the corpus norm.

## API

| Method & path | Purpose |
|---|---|
| `GET /api/integrity/profile?source=` | the no-composite measured-signal panel |
| `GET /api/integrity/actors` | proposed coordinated actors, each flagged applied/not |
| `GET /api/integrity/prominence` | story prominence in independent voices, raw vs collapsed |
| `POST /api/integrity/collapse/apply` · `/revert` | apply / undo a collapse (per actor) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | collapse / reset globally |

## Honest limits (named)

- **Arms race / Goodhart** — every published signal is an optimisation target; this is
  defence-in-depth, never a claim of completeness.
- **False merges hurt the innocent** — detection is high-precision, biased to
  *under*-merge, always evidence-shown, always reversible.
- **Capture** — we ship *mechanisms, not verdicts*; the default is the transparent
  equal view; you override everything.
- **The goal** is not "detect all garbage" (impossible, and claiming it would be the
  dishonest move) but to **strip garbage of its mechanical advantage** so the 40-agency
  play *stops paying off*.
