# V1-7, second round — the four remaining storage rulings

**Status: DECISION BRIEF. No ruling is taken here.** Written 2026-09-07 in the PROMPT 23
planning session, because the maintainer's V1-7 answer was *"ratify 16384 and rule all four
now"* and the second half of that needs evidence in front of it rather than four opinions.
Owner doc: [`STORAGE_5TB_PLAN.md`](STORAGE_5TB_PLAN.md) §8, whose rows 3–6 these are.

**What the first round settled** — and one thing it got wrong, corrected here the same day.
§8 row 1 (`auto_vacuum=INCREMENTAL`) was ruled 2026-07-17. Row 2 (`page_size=16384`) **was
already ruled too, and this brief's first version said otherwise.**

> **⚠ CORRECTION.** The V1-7 question put to the maintainer described 16384 as shipping on a
> *"FIRM recommendation, never a ruling"*. That is false. Merging **PR #749** was the
> ratification under the §4.1.5 self-labeling convention, and the maintainer made it
> **explicit on 2026-08-13** — *"Let's consider this as finished"* — recorded in
> `docs/ledger/OPEN_QUEUE.md` as 0.3 gate **row 6 IS CLOSED**. The claim came from
> `src/database/connect.py`'s own comment, which still read *"FIRM recommendation"* three
> weeks after the ruling; the ledger was never checked. **A maintainer decision was spent
> re-ratifying a settled ruling.** The comment is corrected in `connect.py`, because it is
> the artifact that went stale. The rule it cost: *a code comment may state the EVIDENCE for
> a decision; whether the decision was TAKEN is the ledger's to say.*

Both create-time seams are therefore closed — and were before this session started — so
**V1-7's "urgent, create-time irreversible" framing is spent**: none of the four below is
create-time irreversible, so none of them is on a clock.

## What could and could not be measured here

This session had no egress beyond `pypi.org` and `github.com`, and no live corpus. So the
brief separates three things it would otherwise be tempting to blend:

| | |
|---|---|
| **Measured here** | the ChaCha/AES ratio on an AES-NI CPU; that `apsw-sqlite3mc` and `pyrage` are live on PyPI; that OOENC2 ships with six suites around it |
| **In the record already** | the duplication rate the field corpora show; the OOENC2 container's own test surface |
| **Needs a machine this is not** | anything on a no-AES-NI CPU, and anything at corpus scale |

Every number below says which of the three it is. A recommendation resting on the third
category is marked as such rather than presented as settled.

---

## Row 3 — blob-store dedup: ON?

**The question.** Phase C's packed content-addressed text store can fold exact duplicate
article bodies. Turning it on is a real space win and a real, if narrow, information leak.

**Evidence.** *In the record* (`docs/ledger/LESSONS.md`, the metadata-on-duplicate-articles
entry — both figures re-read there rather than recalled): the restore-merge work measured a
field corpus at roughly a **90% duplicate rate** across **~617k** duplicate articles — wire and syndication duplication is
the dominant shape of this corpus, which is exactly the case dedup is for. *Structural:*
`articles.hash` is already `unique=True` (`src/database/models.py:625`, plus a unique index),
so the corpus ALREADY dedups at the row level;
row 3 is about the BLOB layer beneath it, not about introducing deduplication as a concept.

**The leak, stated precisely.** Content-addressing means two identical plaintexts get one
address, so anyone who can read the addresses learns "these two things are equal" and
learns each blob's length. Row 5 (below) is what confines that to passphrase holders: under
keyed HMAC addressing plus opaque pack names, a person who copies the disk sees neither.

**The recommendation stands (YES),** and the reason to take rows 3 and 5 together is that
row 3's honesty depends on row 5 being ruled the same way. Ruling 3 YES and 5 NO would ship
the leak without its confinement.

**What it does NOT decide:** NEAR-duplicate folding (different bytes, same story) stays a
separate measure-gated decision. Content-addressing gives exact-duplicate folding for free
and says nothing about near-dups.

## Row 4 — pack AEAD: OOENC2, or `age`?

**The question.** Phase C encrypts whole packs. Reuse our shipped streaming AEAD, or adopt
an audited external format.

**Evidence.** *Measured here:* `pyrage` is live on PyPI at **1.4.0**, so `age` is a real,
maintained option rather than a hypothetical — the fallback in §8 is not vapour. *In the
record:* OOENC2 is shipped (`src/safety/crypto.py`, magic `OOENC2\x00\x00`) and carries six
suites around the streaming/volume path (`test_crypto_streaming`, `test_backup_volumes`,
`test_volume_backup_roundtrip`, `test_volume_job`, `test_import_scan_volume_restore`,
`test_crypto_erase`). It is the format the backup engine already writes at volume scale.

**The honest asymmetry.** `age` is externally audited and OOENC2 is not; that is a real
argument and it should not be waved away. Against it: adopting `age` adds a dependency to
the corpus's *decryption* path, which is the one path where a dependency that stops being
maintained does not degrade — it makes data unreadable. OOENC2 is already load-bearing for
backups, so choosing it here adds no new such dependency, and the framed construction
exists precisely to avoid the ad-hoc-nonce cliff.

**The recommendation stands (OOENC2, `age` recorded as fallback)** — but the argument that
carries it is *no new dependency on the decryption path*, not *ours is better*, and it is
worth ruling in those words so a future session does not read it as a quality claim.

## Row 5 — keyed HMAC blob addressing + opaque pack names

**The question.** Address blobs by `HMAC-SHA-256` under a passphrase-derived key, with
random on-disk pack names, rather than by a plain content hash.

**Evidence.** *Structural, and checkable by reading the design:* with plain content-hash
names, someone who copies the disk can test **"is this specific leaked document in this
journalist's archive?"** by hashing their copy and looking for the name. That is a
confirmation attack against the exact threat model this project states — a seized or copied
machine — and it needs no passphrase. Keyed addressing preserves deterministic dedup while
making that test impossible without the key.

**This is the one row I would call uncontroversial**, and §8 says so too. It strengthens a
stated guarantee, costs an HMAC per blob, and changes no user-visible behaviour. Its only
real coupling is row 3: it is what makes dedup's residual leak defensible.

**The recommendation stands (YES).**

## Row 6 — sqlite3mc: authorize the benchmark trial

**The question.** Authorize a *benchmark only* — no migration, no format change — of
sqlite3mc, whose ChaCha20-Poly1305 removes the AES-NI dependency for the aging-laptop case.

**Evidence, and the honest limit of it.** *Measured here, on this box:*

| | 8 MiB pack | throughput |
|---|---|---|
| AES-256-GCM | 2.0 ms | 4,172 MB/s |
| ChaCha20-Poly1305 | 4.0 ms | 2,099 MB/s |
| ratio | | **1.99× slower** |

**This CPU has AES-NI, so this is AES's best case and it CANNOT settle the ruling.** It is
still informative in one direction: both ciphers run thousands of MB/s, orders of magnitude
above any disk this app will meet, so on a modern machine **the choice is not a throughput
decision at all**. The decisive measurement is the one the watch list already names — a
no-AES-NI CPU, where AES drops to software speed while ChaCha does not — and it needs a
machine this is not. *Also measured here:* `apsw-sqlite3mc` is live on PyPI at **3.53.4.0**,
so the trial costs an install rather than a build.

**The recommendation stands (YES, benchmark-only),** and the measurement above is a reason
it is cheap rather than a reason it is urgent: nothing about the modern-hardware case is
pressing, and the whole value is in the old-hardware case nobody has measured yet.

---

## What a ruling on these four does and does not unblock

None of the four is create-time irreversible and none blocks a release currently on the
train. Rows 3–5 are **Phase C** primitives, so ruling them buys a settled design for the
spike that precedes any real store, not an earlier ship date. Row 6 unblocks a benchmark
whose result is itself the gate for anything further.

> **⚠ PHASE C'S OWN PREMISE WAS RETIRED THE SAME DAY, by a parallel session** —
> [`STORAGE_5TB_REFRESH_2026-09-07.md`](STORAGE_5TB_REFRESH_2026-09-07.md), merged as
> **#1032** while this brief was being written. v1's central justification was *"a
> default-page SQLCipher file caps at ~17.5 TB ⇒ Phase C is MANDATORY"*; at the ruled page
> size the cap is **64.00 TiB**, so the 5 TB milestone sits at **7.1%** of one file rather
> than 28%. **Phase C is now ruling-gated rather than mandatory**, and the refresh's §8
> re-scopes the sequencing v1 §9 set. That makes these four rulings *less* pressing than
> this brief's first version implied, not more — and it is the second time in one day that
> a storage claim turned out to rest on a number a ruling had already moved.
>
> **It also CORROBORATES two of the four, independently.** The refresh's §7, listing what it
> did NOT re-litigate, keeps *"**HMAC-keyed addressing with opaque pack names** (the
> confirmation-attack fix) … **OOENC2** over `age` with `age` recorded as the fallback"* —
> the same conclusions rows 5 and 4 reach here, from a different pass. Two independent
> derivations agreeing is worth more than either alone, and is stated because it is the
> kind of thing a reader should be told rather than left to notice.

**The one thing worth ruling early is the row 3 / row 5 PAIR**, because they are a single
honesty argument split across two rows, and splitting the ruling is the way to end up with
the leak and not its confinement.
