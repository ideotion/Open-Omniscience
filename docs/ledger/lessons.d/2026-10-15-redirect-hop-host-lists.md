## 2026-10-15 — a redirect hop goes through Session.send, not Session.request: put a host guard in send, and list what the shared session really serves (PR #1393)

**What was found.** The sink sweep's parked LOW said the Wikipedia, ORES and DuckDuckGo clients "bypass `_guarded_redirect_get`". The cause is one level lower than the suggested fix (`allow_redirects=False` plus a re-issue per client).
requests' `Session.resolve_redirects` calls `self.send` for every hop, not `self.request`, so anything a `GuardedSession` does in `request` (the kill switch, the transport choice) runs once, for the first URL, and never on a hop.
A host check belongs in `send`, where the first request and every hop both pass. It is one override instead of a manual redirect loop per client, and it holds for any caller that follows redirects through the session.

**The rules.**
1. **Guard in `send`, check the whole URL, and reuse the parser-mismatch refusal.** The check runs `EthicalFetcher._refuse_parser_mismatch` first (backslash, whitespace or control in the authority, any `%` in the host, the two parsers
   disagreeing, non-IDNA hosts), then https only, no userinfo, port 443 only, then the list. The host compared is the one urllib3 will connect to (`parse_url(url).host`, which lower-cases), not the `urlparse` one.
2. **An entry's KIND decides its comparison, so branch on it.** A first draft tested `host == entry` for every entry and then the suffix clause; urllib3 returns `.wikipedia.org` (an empty label) as-is, so the suffix entry `.wikipedia.org`
   matched its own empty-label host. `if entry.startswith("."): suffix and strictly longer; elif host == entry` closes it, and a parametrized test pins the label boundaries: `notwikipedia.org`, `wikipedia.org.evil.test`,
   `.wikipedia.org`, the bare `wikipedia.org`, a trailing dot, `127.0.0.1`, `[::1]`. A mutation run found this; reading the code had not.
3. **A shared session serves more hosts than its client's name says.** The wiki client's one session also fetches the pageviews top list from the bare `wikimedia.org` and the EventStreams SSE from `stream.wikimedia.org`
   (`client.session` in `src/wiki/service.py`). A list written from "the Action API is `*.wikipedia.org`" would have refused both in production and passed every unit test of the API. Read every caller of `.session`, and pin each endpoint
   constant against the list in a test (`api_endpoint` for each edition code, `top_url`, `EVENTSTREAMS_URL`).
4. **requests re-quotes a hop's Location, so a percent test must survive that.** `requote_uri` unquotes unreserved escapes: `x%41.wikipedia.org` arrives as `xA.wikipedia.org`, a legitimate listed host, so an end-to-end hop test with
   `%41` proves nothing. `%2B` survives requoting and reaches the check; the unquoted form is tested by calling the check directly.
5. **Make an opt-in list a decision, not an accident.** `allowed_hosts` defaults to `None` (every other caller unchanged), and an AST ratchet pins every `guarded_session` / `following_session` call WITHOUT a list in a table with its
   count, zero slack, so a new unlisted session fails a test and says why. The sessions left out are the ones that redirect between CDNs by design; they need their own look at where each really redirects.
6. **A mutation matrix must prove its baseline first.** One run against a red baseline reported every mutant killed, because every mutant failed for the unrelated reason. The script now runs the unmutated tests and refuses to score
   unless they are green.
