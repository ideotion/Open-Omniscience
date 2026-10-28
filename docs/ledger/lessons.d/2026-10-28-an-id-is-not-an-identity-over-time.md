## 2026-10-28 — an id is not an identity over time: an append-only log keyed by a reusable id must compare what the id pointed at, not only that the id appears

**What was found (R365, the WAL lane's trace of the custody log against a swapped corpus).** `articles.id` is an `INTEGER PRIMARY KEY` without AUTOINCREMENT, so ids are handed out again after a deletion or after a restore's swap discards the newest rows. The custody log is append-only, keyed `article:<id>`, in a separate file the swap does not touch. A check of the form "does the log have an INGEST entry for this id" is therefore true for a different article than the one asked about. `pending.drain` made exactly that check and dropped an owed entry as already written.

**The rule.** When a record lives longer than the key it is filed under, a membership test on the key alone answers "has this key ever been used", not "has this thing been recorded". Compare the content fingerprint the record carries (here the article's hash) as well, and when the fingerprint cannot be learned yet, keep the work queued and say so instead of guessing present. A test of such a check needs the second owner of the id, not only a missing entry.

**What it costs to forget.** A silent missing entry: the log's chain stays valid, the article is in the corpus, and nothing reports that this one has no custody record. Not observed in the field; found by reading `drain` against the id rules of the table.

**Limits.** The rule is applied to `drain` only. `gap_scan` stays id-only because `Article.hash` is rewritten in place by other lanes, so a hash compare there is unsafe until that column's meaning is settled. The restore writing a DELETE entry for the articles it discards is a separate, unbuilt design question.
