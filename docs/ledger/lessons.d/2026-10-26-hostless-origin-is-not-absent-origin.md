## 2026-10-26 — hostless origin is not absent origin

**Found (audit of the HTTP surface, R191).** The CSRF guard computed `host = _origin_host(Origin) or _origin_host(Referer)` and refused only when `host is not None and host not in loopback`. `urlparse("null").hostname`, `urlparse("file:///x").hostname` and `urlparse("about:blank").hostname` are all `None`, so a header that WAS sent, and named no place, took the same branch as a header that was NOT sent (a CLI, which the guard allows on purpose). The `or` made it worse: a loopback Referer next to `Origin: null` was read instead of the Origin. Sandboxed iframes, `file://` pages and some cross-origin redirects send exactly `Origin: null`.

**Rule.** A guard that allows "no header" must test PRESENCE (`header is not None`) before it tests what the header parses to; a parse that yields nothing is not the same fact as the header being absent. When two headers could decide, the stronger one (Origin) decides alone and the weaker (Referer) is read only when it is missing.

**The sibling found beside it.** FastAPI's default 422 returns `errors()` whole, and each error carries `input`; for a body error that is the request body. A route that takes a passphrase therefore echoed it the moment a field was missing. Fix once, globally: a `RequestValidationError` handler that keeps `type`/`loc`/`msg` and drops `input`/`ctx`. Pinned by a canary string on three routes; the repo-invariant that forbids `scrubbed(` on a name an `except ... as e` binds is NAME-based, so a loop variable called `e` in a handler trips it (use another name).

**Limits.** Not browser-verified: the shell tests send headers by hand, there is no `file://` client. PR #1469.
