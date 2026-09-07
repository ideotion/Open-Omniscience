# Prompt 21 — Security, network posture and the consent surface

> **Scope:** `src/utils/security.py`, `src/ingest/` guards, the airplane layer, the consent machinery.
> **Gated on:** I3 (Tor-exit-resolve), I4 (`oo-netcut` / Stem), G9 (self-update), NET-09 (release signing).
> **Sequencing:** its S3 (nonce CSP) is blocked on prompt 15's inline-handler retirement. Everything else is
> independent.

> ### EXECUTION RECORD, 2026-09-07 — three slices built, four ruling-gated, one claim corrected
>
> Executed against `main` @ `d9ee33e7`, branch `claude/security-network-posture-consent-e7uyr5`.
> Read this before the slices: four of the seven wait on a maintainer ruling this session may
> not take, and one of the three buildable ones rested on a claim the tree contradicts.
>
> | slice | verdict | the anchor that settles it |
> |---|---|---|
> | **S1** — NET-01, the SSRF connect-time TOCTOU | **was genuinely open; BUILT** — and live-reproduced first: a real `EthicalFetcher` against a resolver answering `93.184.216.34` at guard time and `127.0.0.1` at connect time returned a loopback server's body as a clean 200 | `src/ingest/ssrf_guard.py`, the scope entered in `src/ingest/__init__.py::_guarded_redirect_get`, hooked into the one socket patch layer in `src/ingest/airplane.py`; `tests/test_ssrf_connect_guard.py` (16 tests; an 11-mutation matrix, each asserted to have applied) |
> | **S2** — NET-02 (`safe_href`/`sanitize_url`) + PRH-03 (the `uddg` redirect) | **was genuinely open; BUILT** | `src/utils/security.py` (`ValueError` only, `urlparse` hoisted so propagation is testable), `src/services/duckduckgo.py::_unwrap_search_redirect`; `tests/test_security_hardening.py`, `tests/test_duckduckgo_url_helpers.py` |
> | **S3** — the nonce CSP, and `docs/SECURITY.md` | **SPLIT: the doc half BUILT, the nonce half still blocked** | `docs/SECURITY.md` now opens its embedded 2026-06-08 report with a per-finding disposition table re-derived from the tree; `src/api/main.py::_CSP` still carries `script-src 'unsafe-inline'` and cannot lose it until prompt 15 S2 retires the ~590 inline handlers |
> | **S4** — I3, Tor-exit-resolve (SOCKS `RESOLVE`) | **RULING-GATED; re-verified design-only** | `0xF0` and `dns-via-tor-exit` appear nowhere under `src/`. The full design of record is already in `docs/ledger/OPEN_QUEUE.md` (2026-07-20 amendment); what is owed is the go/no-go, question I3 |
> | **S5** — I4, `oo-netcut` and Stem-controlled Tor | **RULING-GATED; re-verified design-only** | nothing under `src/` imports `stem` or names `netcut`; both lines exist only in `docs/ROADMAP.md`. Question I4's recommended default is to park both |
> | **S6** — PRH-16, the consent machinery | **STALE CLAIM: two of the three named pieces ARE in the tree** — see below | `src/legal/consent.py:43` (`CONSENT_DOC_VERSION = "1.0"`), `src/api/legal.py` + `src/api/unlock.py`'s locked-state allowlist, `tests/test_legal_documents.py::test_unlock_first_launch_inserts_legal_step_before_passphrase` |
> | **S7** — G9 + NET-09, self-update and signing | **RULING-GATED; re-verified unbuilt** | no `self_update` module exists (the two "self-update" hits in `src/static/` are unrelated comments about Home refreshing itself). `.github/workflows/release.yml` publishes `SHA256SUMS` and its own header says signing is a tracked future item, so the release path does not over-claim today |
>
> **The corrected claim, named as §2 of the working mode requires.** `INVENTORY.md` PRH-16
> and this prompt's own §6 say `OO_REQUIRE_CONSENT`, `CONSENT_DOC_VERSION` and a web consent
> modal "exist nowhere in the tree". `CONSENT_DOC_VERSION` exists, with `is_accepted` /
> `needs_acceptance` / `record_consent` around it. The web consent surface exists too — and
> the reason it did not answer to a search for a *modal* is that a modal was deliberately not
> what was built: `docs/legal/IMPLEMENTATION_NOTES.md` records choosing a dedicated pre-app
> page over an in-SPA `<dialog>` because it blocks harder. Only `OO_REQUIRE_CONSENT` is
> genuinely absent, and that too is a recorded decision rather than an omission — the same
> notes call it "intentionally left as a documented option, not the default, because
> hard-blocking the web entrypoint could strand a desktop-launcher or `curl | bash` user with
> no console." So S6's ask ("record the refusal where the design lives") was already
> satisfied; nothing was decided here, and the one open question is whether the opt-in hard
> block should ever ship.
>
> **What §1 said was already closed, re-verified rather than trusted.** The SOCKS/Tor proxy
> blind spot is closed (`airplane.py` patches `http.client.HTTPConnection._tunnel` and
> PySocks' `socksocket.connect`), and the folder-backup symlink traversal is closed
> (`src/backup/folder_backup.py:701` refuses a symlink outright on the restore path, never
> following it). Both hold at this anchor.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md non-negotiables on the network kill switch and the socket-level
airplane guarantee, then `docs/audit/09_TRANSVERSAL_AUDIT_0.3_DELTA.md`.

The lesson that governs this whole area is recorded and cost a real egress window: **"every real path checks
the gate itself" is an enumeration, and enumerations are wrong.** Relaxing the socket-level backstop was
justified in writing by an audit of the fetch paths — and two modules called `EthicalFetcher`'s *internal*
helpers directly rather than `fetch()`, so they met neither gate, and the backstop had been their sole
protection since it was built. Before relaxing any catch-all, grep for callers of the guarded thing's
**internal** helpers; the caller that reached past the front door is exactly the one an enumeration omits.

## 1. What is already closed, so it is not re-audited

The SOCKS/Tor proxy blind spot (audit 09's P0-1) is closed: `http.client.HTTPConnection._tunnel` and PySocks'
`socksocket.connect` are both patched, so a real destination is checked before SOCKS negotiation, and the
audit's own stub-SOCKS5 exploit is now blocked. The folder-backup symlink traversal on the restore path is
closed. All ten Action-Plan-D items shipped on 2026-07-25.

## 2. Slices

### S1 — NET-01: SSRF connect-time IP pinning

The remaining TOCTOU: a hostname resolved at guard time can resolve differently at connect time. The fix is a
custom transport adapter that pins the validated IP for the actual connection. It was deliberately not
attempted before because it wants its own full-skeptic session, and that judgement stands — treat it as the
prompt's largest slice, not a drive-by.

### S2 — NET-02 and PRH-03: the sanitizer and the redirect

`safe_href` (`src/utils/security.py`) holds a broad `except Exception` in `_clean_url`'s chain. It is the
app-wide sanitizer, so a silent swallow there is silent everywhere.

The same function strips the query string **before** validation, which is why every real DuckDuckGo
`/l/?uddg=<target>` redirect result loses its target and is discarded as scheme-less. That is a live defect in
the one sanctioned external discovery channel, and its test asserts only that a list came back.

### S3 — NET-04: the nonce-based CSP

`'unsafe-inline'` is still in `script-src` and cannot leave until the ~590 inline handlers do (prompt 15 S2).
Sequence accordingly; landing the nonce first breaks the app.

Also here: `docs/SECURITY.md` is a stale point-in-time audit whose CSRF and CSP findings were closed in code.
Correct it or banner it — a security document describing a fixed state as open teaches the wrong thing.

### S4 — I3: Tor-exit-resolve for source IPs

Direct contact is **ruled out** as an automatic mechanism and the reason is worth restating so nobody
re-proposes it: ICMP cannot ride Tor at all, so a ping is always clearnet by construction, and a direct probe
of a just-Tor-fetched source hands the server and the ISP a time-correlated link between the user's real IP
and that source — a deanonymisation, worse than fetching clearnet outright.

The Tor-native path is SOCKS `RESOLVE` (0xF0) on the same port already in use: the **exit** performs the
lookup, so the source's DNS sees only the exit. No direct contact, no new third party (DoH was deliberately
not chosen — it adds an external service class), roughly thirty lines of stdlib socket code, cached per
(domain, pass), kill-switch-gated, and degrading honestly when the configured SOCKS proxy is not Tor.

The answer is the same epistemic class as the clearnet capture at a **different vantage** — "the edge nearest
the exit" versus "the edge nearest the user" — so it stores under a distinct provenance reason
(`dns-via-tor-exit`), never blended with socket-observed. Exit rotation producing several answers is **data**
under the multiple-IPs-per-source model, disclosed. When the Stem control-port integration lands, Tor's
ADDRMAP already holds the resolutions the exits performed during the fetches — a free upgrade that this need
not wait for.

### S5 — I4: the privileged airplane layer and Stem

`oo-netcut` — opt-in, interface-agnostic, explicit and narrowly scoped elevation, never silent: firewall
drop-all in both directions including inbound; `ip link down` on non-loopback interfaces; an rfkill bonus on
bare metal; Windows `netsh` and macOS `networksetup` behind one helper. The button names the layer it
controls, and a userspace app can never equal a hardware webcam light — we never claim it does.

Stem-controlled Tor is the sibling: there is no pure-Python Tor, the mature path is controlling a `tor`
process via Stem (the Tor Project's own library), and Arti's Python bindings were nascent at the knowledge
cutoff and must be **re-verified** before being bet on. Per-source **circuit isolation** (`IsolateSOCKSAuth`,
already a primitive here) compartmentalises without any clearnet exposure and is strictly preferable to
per-source clearnet, which stays an explicit consented last resort.

### S6 — PRH-16: the consent machinery that was designed and never built

`OO_REQUIRE_CONSENT`, `CONSENT_DOC_VERSION` and a web consent modal came out of the legal-acceptance work and
exist nowhere in the tree. Decide whether they are wanted; if not, record the refusal where the design lives.

### S7 — G9 and NET-09: self-update and signing

The self-update posture is ruled: **manual, user-driven, git-pull based, no signing key yet**. The mechanics
are snapshot → verify → staged migrate → atomic swap → rollback, and the data directory living outside the
code tree is what makes the corpus, settings and keys survive by construction. Five questions remain open
(channel, trust root, cadence, curl-pipe-bash versus git, mirror anchoring). Releases carry checksums and no
signature; NET-09 is whether that changes.

Never silently decrypt across an update.

## 3. Scope fence

No fabricated security, ever — no lock screen over plaintext, no theatre. Never silently downgrade transport.
Never evade robots, blocks or CAPTCHAs. Wrong-passphrase rate limiting stays a deliberate, reasoned omission
and is not to be re-added as an oversight (an attacker who can brute-force has the file and works offline;
backoff would punish only the honest fat-finger user).
