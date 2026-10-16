## 2026-10-15 — listing a fixed endpoint you cannot probe: take the host from the URL the code builds, say so, and make each consumer say what it does with a refusal (PR #1394)

**What was found.** Six sessions that fetch ONE fixed https endpoint (four Wikidata loaders on `www.wikidata.org`, the country-catalogue SPARQL query on `query.wikidata.org`, the Hugging Face weights-digest check on `huggingface.co`) had no host
list, and the table that pinned them said they redirect between CDNs by design. They do not; that sentence belonged to the downloads next to them. The sandbox the change was built in cannot reach any of the three hosts (the environment's proxy
refuses the tunnel), so what those hosts redirect to could not be observed.

**The rules.**
1. **Without a live look, the list is the host of the URL the code builds, and a test asserts the two are EQUAL.** `tests/test_session_host_list.py` checks `list == (urlsplit(endpoint).hostname,)` for each of the four lists and that a neighbour host
   (the other Wikidata host, a Hugging Face CDN host) is refused. The first draft only checked that the endpoint was ACCEPTED by its list, and the independent read's mutation run widened a list by one host in four places (a second Wikidata host,
   `query-main.wikidata.org`, `hf.co`, an inline widening at one call site) without one test failing. An accepting test cannot see a list that grew. The Hugging Face URL was an inline f-string, so the test checked a hand-written copy: it is
   now the constant `HF_MODEL_API_URL`. An exact host is the tighter choice, and the failure it risks is a refused request that a later session can widen with evidence; a family suffix guessed in advance cannot be tightened without the same evidence.
2. **Say in the docs that the list was not checked against live redirects, and make every consumer say what it does with a refusal.** `docs/SECURITY.md` states the first for these three hosts, so the absence of an observation is not read as one.
   "Refused loudly" was an overclaim: the source-typing pass swallowed every exception (`except Exception: continue`), so a redirect off Wikidata read as "Wikidata had no match", and the other loaders fold a `RedirectRefused` into a refused or error
   count. The pass now catches the type explicitly and counts it (`sources_refused`, the class name and no address in the result, "N refused" on the Diagnostics button). Probe a claim about a failure's visibility by feeding the consumer the exception.
3. **Test each module through its OWN default getter, and read the list the session it built carries.** The end-to-end tests mount one scripted adapter under `guarded_session`, record every session built, and call `_default_getter` / `guarded_getter` / the SPARQL transport / `_weights_digest_proposal`, so deleting the
   `allowed_hosts=` argument, or widening it inline, at a call site fails that module's test. A test of the helper alone would stay green with the argument gone.
4. **A test about two parsers disagreeing asserts the disagreement first.** `test_the_real_parsers_split_a_backslash_authority_...` now asserts that `urllib3` reads `de.wikipedia.org` and `urlparse` reads `evil.test` for the string it uses, so a library
   release that makes them agree turns the test red instead of leaving it passing about nothing.
5. **A reading with no host is a refusal, not a pass.** Faked one-reading cases cover a `hostname` of `None`, a `hostname` of the empty string and a percent in only one reading: the first two are refused by the comparison (an empty
   host is no listed host), the third by the percent clause when it runs and by the comparison when it does not.
6. **A table of exceptions refuses an empty reason.** `UNLISTED_SESSIONS` asserts every row's reason is non-blank, so a row cannot be added to make a failing count pass without saying why.
7. **Prose about what a table leaves out is checked against its rows.** The new comment above `UNLISTED_SESSIONS` and the SECURITY.md sentence said the remaining sessions have no fixed host; the installer's release lookup on `api.github.com` is a fixed
   endpoint, and its row now says so (a fixed endpoint not listed yet, beside the asset download that follows a response-chosen URL to storage whose host moves). Reconcile each sentence that characterises the rows with each row.
