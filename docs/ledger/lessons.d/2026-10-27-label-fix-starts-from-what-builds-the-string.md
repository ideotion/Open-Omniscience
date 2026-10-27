## 2026-10-27 — a label fix starts from what BUILDS the string, not from the enum that looks like it

**What was found.** A draft keyed the import queue's `KINDS` (corpus, legacy, blobs, newsletters) because the Backup history prints a `kind`. That `kind` is the PREFIX OF THE REPORT'S FILE NAME (`list_import_reports`: `p.stem.split("-", 1)[0]`), and every writer passes `restore`, `newsletter` or `incomplete` to `persist_import_report`; none of the queue's words ever becomes a prefix. The independent read of the PR found it; the keys it added would have been harmless and useless, and the test and the ledger summary would have claimed a fix that did not happen.

**The rule.** Trace the displayed string back to the line that BUILDS it (here the file-name format and every call that writes one) and take the word list from there, not from a similarly named enum nearby. Pin the test to the writers (a scan for the call sites' literal first argument), so a new writer fails until it is keyed.
