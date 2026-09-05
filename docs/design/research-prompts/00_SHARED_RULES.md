# Shared rules for every Open Omniscience research session

Paste this block at the top of each research prompt. It exists because **three
consecutive networked sessions failed the same task through three different tool
surfaces**, and each one rewrote its prompt for the next instead of characterising the
environment. These rules are the fix.

---

## Rule 0 — PROBE THE ENVIRONMENT BEFORE DOING ANY WORK

Your value depends on reaching specific external hosts. Find out in the first minute
whether you can, and **report the result as a finding**, not as a failed attempt.

```bash
for h in <the hosts this task needs>; do
  echo -n "$h "; curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 "https://$h/" || echo FAIL
done
echo -n "control(pypi.org) "; curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 https://pypi.org/
```

The control host distinguishes *"the network is down"* from *"an allowlist refused these
specific hosts."* If the target hosts fail while the control succeeds, **stop and report
that**, with the per-host evidence. Do not rewrite your approach and retry — a policy
gateway is not something a better prompt routes around. A convergence of failures is
itself the deliverable.

## Rule 1 — READ THE URL YOU WERE SERVED, NEVER THE ONE YOU ASKED FOR

Some tools silently rewrite a request and return a different resource with no error. A
past session asked for `?page=2`, was served page 1 three times, and nearly published
*"pagination is broken at the publisher"* — a confident, wrong, undetectable claim about
someone else's API.

**Before attributing any output to any input you supplied, verify the tool echoed your
input back.** Record the served URL beside every fact.

## Rule 2 — SEPARATE FACTS FROM INFERENCES

A fetched fact and a one-sentence generalisation drawn from it look identical in a
well-written report, and the generalisation is where the errors are. Tag every claim:

* `fetched` — you retrieved the artefact and read it. Record the URL and the date.
* `search-verified` — a search result or secondary page stated it; you did not fetch the
  primary artefact.
* `lead` — plausible, unverified. **A lead ships as a lead**, never promoted.

**Never invent a URL, an endpoint, a licence, a file size, or a version number.** If you
cannot verify it, say so — an honest gap is worth more than a plausible guess, and this
project has been burned by fabricated endpoints before.

## Rule 3 — LICENCES ARE READ FROM THE ARTEFACT, NOT FROM A SUMMARY

A project's "About" page saying *"open data"* is not a licence. Fetch the actual
`LICENSE` / `COPYING` / terms page, quote the identifier verbatim (e.g. `CC0-1.0`,
`CC-BY-SA-4.0`, `MIT`), and give the URL. Where a dataset aggregates other datasets
(WordNet-style collections are the usual case), **licences vary per component** — report
per component or report that you could not.

## Rule 4 — SIZE AND OFFLINE-VIABILITY ARE REQUIREMENTS, NOT FOOTNOTES

The app is local-first and fully offline. Any data source ships as a **static file
generated on a networked machine and committed to the repository**, under a **100 MB
per-file limit**. For every candidate report:

* the raw distribution size and format;
* whether it can be **filtered down** to 12 languages (en fr de es pt ru ar zh ja hi bn id)
  and, if so, the rough filtered size;
* whether the filtering can be done with a script and no service dependency at runtime.

A source that only works via a live API is **disqualified** for bundling — say so plainly.

## Rule 5 — NO HEAVY RUNTIME DEPENDENCIES

`torch`, `onnx` and `transformers` are **banned** from this project's core. A neural
model is not an acceptable answer. Data files, lookup tables and pure-Python parsers are.

## Deliverable format

One Markdown file. A table of candidates with a verification tier per row, then a
per-candidate section with the evidence. End with:

1. **What you could not verify, and why** (be specific — blocked host, missing licence
   file, dump too large to inspect).
2. **Which findings are facts and which are your inferences.**
3. A recommendation, clearly marked as your judgement rather than a finding.
