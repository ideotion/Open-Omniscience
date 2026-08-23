# Autonomous session brief — the five unmerged tables

**Status:** Part 0 is buildable NOW (no ruling needed — a live-reproduced data-loss defect).
Parts 1–2 are BLOCKED on five maintainer decisions.
**Companion brief:** `AUTONOMOUS_SESSION_BRIEF_2026-08-03_SOURCE_QUALIFICATION.md` (disjoint files).

---

## Part 0 — A SECOND defect, found while writing this brief. No ruling needed; build it first.

The five tables below are not merged *at all*, which is at least visible. While verifying the
brief I ran a systematic diff — every `INSERT INTO ... (cols) SELECT` in `merge.py`, parsed with
Python's own AST (a naive grep gives false positives: inline `# nosec` comments break the string
concatenation), against each model's real column set. Then I confirmed the result **behaviourally,
through a real `merge_corpus` over two real corpora**:

```
articles.detected_language   'fr'                     -> None
articles.server_ip           '9.9.9.9'                -> None
articles.server_ip_reason    'socket'                 -> None
wiki_pages.latest_text       'THE LATEST TEXT'        -> None
wiki_pages.latest_text_revid 42                       -> None
wiki_revisions.full_text     'THE REVISION FULL TEXT' -> None
articles.language            'en'                     -> 'en'   <- the control: the merge DID run

law_documents.country        'kh'                     -> None
law_documents.language       'fr'                     -> None
law_documents.latest_text    'LATEST'                 -> None
law_revisions.full_text      'REV FULL TEXT'          -> None
external_sources.discovered_via 'wikipedia'           -> None
law_documents.jurisdiction   'fr'                     -> 'fr'   <- second control
```

Every row in the "carry these" table below except `articles.content_multihash`/`canon_version`,
`articles.ip_observed_at` and `article_analyses.prompt_text` was confirmed this way; those four
are AST-verified only, and the executing session should confirm them with the same reproducer
rather than taking the read on faith.

This is the **same defect class as the qualification-stamp bug** (CLAUDE.md, 2026-07-24): an
explicit column allowlist silently drops every column added after it, and a nullable column arrives
as a plausible `NULL` rather than an error. Every one of these was added *after* its INSERT was
written.

### The full list (AST-verified)

**Carry these — no ruling needed, the answer is "copy the column":**

| Table | Dropped | Why it matters |
|---|---|---|
| `articles` | `detected_language` | the entire deduced-language channel; a merge resets every article to unknown |
| `articles` | `server_ip`, `server_ip_reason`, `ip_observed_at` | the captured source-IP layer, unrecoverable after the fetch |
| `articles` | `content_multihash`, `canon_version` | the K1/K2 identity seams |
| `wiki_pages` | `latest_text`, `latest_text_revid` | the living-source payload |
| `wiki_revisions` | `full_text` | the per-revision text the maintainer explicitly ruled stored |
| `law_documents` | `country`, `language`, `latest_text`, `latest_text_revid` | `language` is the Cambodia-law-in-French case |
| `law_revisions` | `full_text` | as above, law side |
| `external_sources` | `discovered_via` | the Q4a discovery provenance |
| `article_analyses` | `prompt_text` | provenance of an AI output |

**Verified LEGITIMATE — leave alone, and say so in a comment so nobody "fixes" them:**
`sources.article_count` / `counter_reconciled_at` and `keywords.article_count` / `mention_count` /
`last_reconciled_at` are reconciled post-merge on purpose; `sources.last_crawled_at` is per-machine.

**Needs a look, not a ruling:** `keyword_categories.parent_id` and
`keyword_supergroup_members.ring_id` are self-referential ids that would need a remap — determine
whether they are handled elsewhere or genuinely dropped, and report which.

### Build it as

One commit per table group, each with a behavioural round-trip test asserting the value
**survives**. The reproducer that produced the evidence above is inlined here so it cannot rot —
plain SQLite, no encryption, no fixtures; run it, then re-run it after each commit:

```python
import sys, sqlite3, tempfile, pathlib
sys.path.insert(0, ".")
from sqlalchemy import create_engine
from src.database.models import Base
from src.backup.merge import merge_corpus

def make(p):
    e = create_engine(f"sqlite:///{p}", future=True)
    Base.metadata.create_all(e); e.dispose()

d = pathlib.Path(tempfile.mkdtemp()); inc, loc = d / "inc.db", d / "local.db"
make(inc); make(loc)

c = sqlite3.connect(inc)
c.execute("INSERT INTO sources (name, domain, enabled) VALUES ('S','ex.com',1)")
c.execute("INSERT INTO articles (url, canonical_url, source_id, title, content, hash,"
          " language, detected_language, server_ip, server_ip_reason)"
          " VALUES ('http://ex.com/a','http://ex.com/a',1,'T','body','h1','en','fr',"
          "'9.9.9.9','socket')")
c.execute("INSERT INTO wiki_pages (wiki, title, latest_text, latest_text_revid)"
          " VALUES ('en','P','THE LATEST TEXT',42)")
c.execute("INSERT INTO wiki_revisions (page_id, revid, timestamp, full_text)"
          " VALUES (1,7,'2026-01-01','THE REVISION FULL TEXT')")
c.execute("INSERT INTO law_documents (jurisdiction, url, title, country, language,"
          " latest_text, latest_text_revid)"
          " VALUES ('fr','http://l/1','T','kh','fr','LATEST',5)")
c.execute("INSERT INTO law_revisions (document_id, content_hash, full_text)"
          " VALUES (1,'h','REV FULL TEXT')")
c.execute("INSERT INTO external_sources (name, domain, discovered_via)"
          " VALUES ('X','x.com','wikipedia')")
c.commit(); c.close()

merge_corpus(inc, loc, {"artifact_id": "t", "created_at": "2026-01-01",
                        "app_version": "0.3.0"})

c = sqlite3.connect(loc)
# `language` and `jurisdiction` are the CONTROLS -- they must survive, or the merge
# never ran and every other None below would be meaningless.
print(c.execute("SELECT language, detected_language, server_ip, server_ip_reason"
                " FROM articles").fetchall())
print(c.execute("SELECT latest_text, latest_text_revid FROM wiki_pages").fetchall())
print(c.execute("SELECT full_text FROM wiki_revisions").fetchall())
print(c.execute("SELECT jurisdiction, country, language, latest_text,"
                " latest_text_revid FROM law_documents").fetchall())
print(c.execute("SELECT full_text FROM law_revisions").fetchall())
print(c.execute("SELECT discovered_via FROM external_sources").fetchall())
```

Two schema gotchas that cost a run each while writing this: `articles.canonical_url` is NOT NULL,
and `wiki_pages`' edition column is `wiki`, not `lang`. Then close the class permanently:
a test that walks `Base.metadata.tables`, extracts each merge INSERT's column list **via AST**, and
fails on any model column that is neither in the INSERT nor in an explicit
`_MERGE_COLUMN_INTENTIONALLY_OMITTED` map with a reason. That is the completeness check the
2026-07-24 lesson asked for, at column granularity — without it this recurs the next time anyone
adds a column.

---

## Part 1 — What the decision actually is (read this part; it is the whole ask)

### The one-sentence version

When you merge one corpus into another, the merge has to answer, for every single row it copies:
**"is this row I'm importing the SAME thing as one I already have, or a NEW thing?"** For most
tables the database schema already answers that question. For five tables nothing does, so a human
has to say.

### Why it matters

Get it wrong in one direction and every merge **duplicates**: merge your 8 instances and you have
8 copies of the same watch, 8 copies of the same AI summary, and it doubles again next time.

Get it wrong in the other direction and every merge **silently overwrites or drops** real data:
two genuinely different things get treated as one, and the second one vanishes with no error.

There is no safe default, which is why these five are currently **not merged at all** — a fresh
install restored from your backup loses them. That is a real hole, but it is a visible, reversible
one. Guessing an identity rule and shipping it would be neither.

### Why the other tables were fine

`sources` has a unique constraint on `domain`. So "same source" = "same domain" — the schema said
it, we did not invent it. `stat_figures`, `stat_subscriptions`, `hazard_event_details` and
`keyword_tags` all have their own unique constraints, which is exactly why those four could be
built on 2026-08-03 without asking you anything.

These five have **no unique constraint**. Nobody ever wrote down what makes two of them "the same".

---

### The five questions

Each is a straight either/or. I give you a concrete case from your own 8-instance setup, and my
recommendation. If you just say "your recommendations", that is a complete answer.

---

#### 1. `watches` — your saved alert conditions

A watch is: a **name**, a **search query**, a **threshold** (how many articles), and a **window**
(how many days).

> **Is a watch on machine A the same watch as one on machine B when the NAMES match, or when the
> QUERY + THRESHOLD + WINDOW match?**

- **By name:** you rename a watch on one machine → the merge sees a new name → you get two watches
  doing the identical thing.
- **By condition:** you set up "Sahel coverage" on two machines with slightly different windows
  (7 days vs 14) → the merge sees two different things → you get two watches, correctly, but you
  also get two if you merely tweaked one.

**My recommendation: by name.** A watch's name is the thing you gave it, it is how you recognise
it in the list, and a renamed duplicate is *visible and deletable in one click*. The condition
tuple is invisible — a stray window change would leave you with two identical-looking rows and no
way to tell which is which. Cost of my being wrong: one extra row you can see and delete.

*This one is worth ruling first: watches are content you authored by hand, they are lost on a
fresh-install restore today, and question 2 is blocked behind it.*

---

#### 2. `watch_matches` — the history of when each watch fired

This is **blocked on #1** and needs no separate decision. Once a watch has a stable identity, a
match is identified by (that watch, the timestamp it fired). Nothing else is plausible.

**No answer needed — it follows from #1.**

---

#### 3. `ai_custom_prompt` — your custom AI extractors

Each is: a **label**, an **output kind**, and the **prompt text**.

> **Same extractor across machines by LABEL, or by the prompt TEXT?**

- **By label:** you edited the prompt on one machine to improve it → the merge keeps whichever
  arrived first → **your edit silently disappears.**
- **By text:** every edit becomes a second row → you accumulate near-identical extractors named the
  same thing.

**My recommendation: by label, and take the LOCAL one on a clash** (the standing merge policy —
an existing local row is never overwritten). So: importing never destroys what is on the machine
you are importing *into*. If you edited the prompt on machine B and import B into A, A keeps A's
version. That is the same rule every other table already follows, and it is predictable.

*Caveat I want you to know: this means a prompt improvement made on a secondary machine does not
travel. If your prompts mostly live on one machine, that is fine. If you edit them on several, say
so and I will use the text instead.*

---

#### 4. `ai_keyword` — the AI-derived metadata layer (the largest of the five)

Each row is: an **article**, a **kind** (who / place / date), a **term**, and which **model** and
**prompt version** produced it.

> **Is "Angela Merkel, from article 412, kind=who" one row, or one row per model that said it?**

- **One row per (article, kind, term):** two models agreeing collapse into one — clean, small. But
  you lose the fact that two independent models agreed, which is genuinely useful evidence.
- **One row per (article, kind, term, model, prompt_version):** both answers survive. But re-running
  the same model under a new prompt version duplicates every term in the corpus, and this is the
  biggest of the five tables.

**My recommendation: (article, kind, term, model) — include the model, exclude the prompt version.**
Two different models' readings both survive (that is the evidence you actually want); re-tuning a
prompt on the same model updates in place rather than doubling the table. The provenance you lose
is "which prompt revision said it", which is the least load-bearing part of the record.

---

#### 5. `law_revision_summaries` — AI summaries of tracked law changes

Each is: a **law revision**, the **summary**, and the **model/prompt** that wrote it.

> **One summary per law revision, or one per (revision, model)?**

- **One per revision:** a second model's reading replaces the first.
- **One per (revision, model):** both sit side by side.

**My recommendation: one per (revision, model)** — same reasoning as #4, and this is a small table
so the cost is negligible. Two readings of the same legal change is exactly the kind of thing worth
being able to compare.

---

### Summary of what I need from you

| # | Table | My recommendation |
|---|---|---|
| 1 | `watches` | identity = **name** |
| 2 | `watch_matches` | follows #1 — no answer needed |
| 3 | `ai_custom_prompt` | identity = **label**, local wins on clash |
| 4 | `ai_keyword` | identity = **(article, kind, term, model)** |
| 5 | `law_revision_summaries` | identity = **(revision, model)** |

"Go with your recommendations" is a complete answer. Disagreeing with any one of them is also a
complete answer — none of the five depends on another except #2 on #1.

---

## Part 2 — The build, once ruled

Small and entirely mechanical. Everything it needs already exists.

### Shape

Each handler is one `_insert_tracked` call in `src/backup/merge.py` following the pattern the
2026-08-03 four already established, placed in FK-safe order, with `WHERE NOT EXISTS` expressing
the ruled identity, and the table moved from `_MERGE_NOT_CARRIED` (line 503) to `_MERGE_HANDLED`.

- `watches` — no FK; insert directly. Then `watch_matches` needs a `temp.map_watches` built from
  the ruled identity (mirroring `_build_map(con, "map_sources", ...)` at merge.py:626), because
  `watch_id` must be remapped to the local id.
- `ai_custom_prompt` — no FK; insert directly.
- `ai_keyword` — has `article_id` → **must** run after `_merge_articles` and use the existing
  `temp.map_articles`. Largest table: use the same batched pattern the mention merge uses.
- `law_revision_summaries` — has `revision_id` → runs after the law-revision step, needs the
  law-revision id map.

### Tests (the load-bearing part)

`tests/test_merge_completeness.py` already enforces that every model table joins one of the three
registries, so it will redden until each moved table is registered — that is the guard working.

Add behaviour tests **against the real `merge_corpus` over two real corpora**, exactly as
`tests/test_merge_source_qualification.py` does. A self-restore can never exercise a merge (every
row reads as a duplicate), so each table needs:

1. a row that exists only in the incoming corpus → **arrives**;
2. a row that exists in both under the ruled identity → **exactly one survives, and it is the local
   one**;
3. a row that differs only in the field the ruling says is *not* part of the identity → **collapses
   to one** (e.g. two prompt versions of the same ai_keyword under recommendation #4);
4. a row that differs in a field the ruling says *is* part of the identity → **both survive** (e.g.
   two models' ai_keyword rows);
5. for `watch_matches`: the remapped `watch_id` points at the correct local watch.

**Stash-verify each suite**: unregister the handler, confirm the tests fail in the predicted way,
restore, confirm green. State honestly in the PR which assertions cannot discriminate (a
"local wins" test proves nothing when nothing is copied at all).

### Also fix while here

`_MERGE_NOT_CARRIED`'s entries for these five currently state the open question. Once ruled, replace
each with the **ruled identity and the date it was ruled**, so the next session reads a decision and
not an archaeology exercise.

### Gates

`ruff check --select=F,B --extend-ignore=B008` · `python3 -m mypy src/backup/merge.py` (ratchet
≤127) · `bandit==1.9.4 -r src -ll -q` (new f-string SQL needs the `# nosec B608` convention) ·
full `pytest -q` with a baseline diff against clean `main`, checking the **pass-count delta**
matches the tests added.
