# Security review for 0.9 (gate row E)

This is the report `RELEASE_0.9_GATE.md` row E asks for (brief `S09-01` §S5). It gives one finding per item:

1. Tor-exit-resolve (register I3).
2. `oo-netcut` and Stem (register I4).
3. The self-update check (Q1136).
4. The per-release no-telemetry re-check.
5. The SSRF and airplane guards, re-verified against every host added since 0.3.

The review was read on `main` at `91780c9eb` (2026-11-20). Every claim names the file and line it was read from. It changes no code. Each gap it found is a **proposed row** in §7, not a fix.

**What this report may not decide** (brief §S5): whether I3 and I4 are built, and who signs releases and with what key. Those are the maintainer's. Where this report proposes a timing or a park, it is a finding with its reasoning, not a ruling.

## 1. I3: Tor-exit-resolve for source IPs

**Finding: building it is already ruled.** `RC14` = a, answered by the maintainer on 2026-09-29, says I3 is built as its own slice at this row (`docs/ledger/RULINGS_INDEX.md:674`; the gate's 2026-09-29 amendment-log line). Q1138 = a had parked it only until this review.

**What is still open is timing.** This review proposes building the slice **after 0.9.0-beta.1 is cut**, for the reasons below. That departs from `RC14`'s placement at row E, so the move is the maintainer's to rule. Until it is ruled, `RC14` stands and the slice is part of row E (§8).

**The design of record** is in `docs/plans/2026-09-06-repo-analysis/PROMPT_21_security-and-network.md` §S4:
- a SOCKS `RESOLVE` (`0xF0`) on the proxy port already in use;
- cached per (domain, pass) and kill-switch-gated;
- stored under its own provenance reason, `dns-via-tor-exit`, never blended with an IP observed on the socket.

**What exists today:**
- `git grep -n -i -E 'netcut|import stem|from stem|0xF0|dns-via-tor-exit' -- src scripts` finds nothing.
- A fetch through any proxy records no server IP, and says why. `EthicalFetcher._capture_server_ip` (`src/ingest/__init__.py:1760`) returns `(None, "unavailable (proxy/Tor)")` whenever a proxy is configured (`proxied=bool(self.proxy or iso_proxies)`, `:1708`), HTTP proxies included. This is the gap I3 closes, for Tor only. It is honest today, but the IP column is empty for every source fetched through Tor.
- With a remote-resolving proxy (`socks5h`/`socks4a`, `src/ingest/__init__.py:831-860`), the exit already resolves the name for the fetch. So the local resolver learns nothing, and there is no local answer to keep.

**Why build it:**
- It fills a column that is empty by construction for exactly the users who chose Tor.
- It adds no third party: the exit resolves, and the design rejected DoH for that reason.
- It is small (about thirty lines of stdlib socket code).

**Why after the beta, as proposed:**
- It is a transport change.
- The sandbox cannot run it against a real Tor (there is no `tor` process, and outbound traffic is limited to the agent proxy). Its skeptic matrix therefore needs fixtures plus one operator run on a real Tor.
- The non-negotiables apply in full: never silently downgrade transport, and transport-aware verdicts. A configured SOCKS proxy that is *not* Tor must degrade to "unavailable (proxy is not Tor)", never to a local lookup. A local lookup is the deanonymising direct contact the design rules out.

**The airplane socket guard will not catch this slice by itself.** A raw SOCKS `RESOLVE` goes to a loopback Tor port, and the guard always lets loopback through. Its SOCKS coverage sits on PySocks' connect and on `http.client`, and a socket write outside `http.client` is not covered (`src/ingest/airplane.py:69-72`). So the slice must check the kill switch itself before opening the socket. It needs a test that `RESOLVE` is refused in airplane mode, and it must never run at boot.

**Precondition named:** the operator run on a real Tor, recorded like the other live checks.

## 2. I4: `oo-netcut` and Stem-controlled Tor

**Finding: park both until after 1.0.** This is a finding, not a ruling: register I4 and Q1138 agree on parking, and `RC14` did not touch it. `oo-netcut` is not built and nothing imports `stem` (same grep as §1).

**`oo-netcut`**
- It needs privilege elevation: a firewall drop-all, `ip link down`, `rfkill`, and `netsh`/`networksetup` on the other two platforms.
- That is a new class of operation for a userspace app, with a failure surface on each OS, and no lane here can test it.
- **What it would add is real.** It would be a layer under the app's own spawned processes: the update's `git`, the AI install's script, the Hugging Face snapshot, `pip`, and Ollama/vLLM. Those rely today on a gate before each spawn that egresses (§5, P4), because the in-process guard cannot reach them. The Ollama daemon is started ungated and relies on its pull being refused at the client (§4). It would also be a layer under other processes on the machine.
- **The park rests on cost:** the privilege and the per-OS testing it needs.
- The in-process layer it would sit under is in place and tested: the airplane socket guard (`src/ingest/airplane.py:858`, installed at `src/api/main.py:534`, `:615` and `src/api/unlock.py:623`; `tests/test_airplane_socket_guard.py`).

**Stem**
- Controlling a `tor` process through Stem is the mature path. PROMPT_21 §S5 asks that Arti's Python bindings be re-verified before they are bet on as the alternative.
- Per-source circuit isolation already exists without Stem:
  - `IsolateSOCKSAuth` with a per-host username (`src/ingest/__init__.py:1907`);
  - distinct isolation tokens per lane (`src/safety/fetcher.py:471`, shipped 2026-11-09).

## 3. Self-update (Q1136)

**Finding: shipped, and it meets three of Q1136's four clauses. "Signed releases" is not met, and its precondition is the maintainer's: a signing key and a trust root. A smaller departure, the `main` fallback, is proposed as row P1.**

The feature shipped in PR #1810 (2026-11-08), with later fixes including PR #2160 (R748). Code:
- `src/maintenance/self_update.py`;
- `scripts/apply_update.py`;
- the routes `POST /api/system/update/check` and `/update/apply` (`src/api/system.py:88`, `:129`).

| Q1136 clause | State | Evidence |
|---|---|---|
| **An opt-in check, consented like any egress** | Met | The check runs only on a click, behind `ensureOnline("Check GitHub for a newer version of the app")` (`src/static/app-settings.js:2304`). Like the other click-triggered lanes, that gate shows the one consent popup on the offline→online transition, and passes straight through when the app is already online (`src/static/app-core.js:1681`). The check is one or more `GET`s, one per page of 100 tags, plus one for `main` when no tag exists. All go through the guarded session held to `api.github.com` (`self_update.py:52`, `:181`), so the kill switch, the protected-mode proxy and the host list apply. Disclosure: `docs/SECURITY.md` line 109, and the consent popup's per-lane hover entry "App updates" (`src/static/net-hosts.js:240-247`). Tests: `tests/test_self_update.py::test_a_check_in_airplane_mode_is_named_by_the_endpoint`, `::test_the_ui_asks_the_consent_popup_before_the_update_starts`. |
| **Never auto-install** | Met | The only caller of `begin_apply`/`launch_helper` is `POST /update/apply` (`src/api/system.py:146`). Nothing runs on a timer. Applying goes through the same `ensureOnline` gate, then a separate `window.confirm` naming what happens (`app-settings.js:2333-2334`). The server also needs `confirm: true` plus the exact `ref`/`sha` of a check this process made in the last hour (`validate_apply`, `self_update.py:394-409`). The apply is refused in airplane mode and in protected mode before anything stops (`refuse_offline_or_protected`, `:340-350`), because the spawned `git fetch` is out of reach of the socket guard and the proxy. The server cannot tell a click from a scripted same-origin `POST`; cross-origin requests are blocked by the CSRF middleware (`src/api/main.py:1134`). Tests: `::test_apply_needs_the_exact_checked_ref_and_sha_and_a_fresh_check`, `::test_apply_is_refused_in_airplane_mode_before_any_helper_starts`, `::test_apply_is_refused_in_protected_mode_and_when_settings_cannot_be_read`, `::test_airplane_mode_switched_on_during_the_checks_still_stops_the_spawn`. |
| **Tags only** | Met while a tag exists; see P1 | "Newer" is the highest `vX.Y.Z` tag (`pick_newest_tag`, `:90`). Every tag page is read (`::test_every_tag_page_is_read`), and the check never moves backwards. **But** when no tag parses, the check falls back to `main`'s tip (`MAIN_URL` `:51`; `kind: "main"`, `:234-252`; pinned by `::test_check_falls_back_to_main_only_when_no_tag_exists`), and the helper accepts `ref == "main"` (`scripts/apply_update.py:300`, `:314`). Tags `v0.2.0` to `v0.5.0` exist, so the fallback is inert today. It is still a path Q1136 did not allow. |
| **Signed releases** | **Not met**; precondition named | No signing key is published (`.github/workflows/release.yml:5-6`, and at `:128` "No signing key yet -- verify integrity with the checksums below."). The update binds the code by commit identity only: the fetched commit must equal the `sha` the check read from `api.github.com`, from the pinned `origin`. `docs/SECURITY.md` line 109 states this as exactly that and no more, including that a git `insteadOf` rewrite in the user's own config can redirect the fetch. The update fetches `refs/tags/<tag>` with git (`apply_update.py:314-319`) and never touches the release artifacts or `SHA256SUMS`. **So for the in-app update, "signed" has to mean a signed tag (or commit) that the helper verifies against a trust root shipped in the app.** Signing only the wheel and sdist would leave the update path unsigned. **Precondition:** a signing key, who holds it, how it rotates, and that trust root (brief §S5; register G9). Until then, nothing is called "signed", in the app or in the notes. |

**The swap side** meets the G9 mechanics:
- `git merge --ff-only` on a clean `main`;
- a version that changes dependencies is refused before the swap;
- the passphrase variables are removed from every child process, so the restarted app opens locked;
- the old `HEAD` is recorded as the rollback point (no snapshot is taken);
- a rollback when the new version's launcher exits before the app ever answers on its port (`apply_update.py:419-434`, `:599-611`). A start that is merely slow is reported as unconfirmed and is not undone, because it may be mid-migration.

**Where the data lives.** In a git checkout, the data folder defaults to `<repo>/data` (`src/paths.py:113-114`). That is inside the checkout, but git-ignored (`.gitignore:86`, `/data/`), so neither the fast-forward nor a rollback's `reset --hard` touches it. With `OO_DATA_DIR` set it is outside the tree. PROMPT_21 §S7's premise, "the data directory living outside the code tree", therefore holds only with `OO_DATA_DIR`. The protection by default is the ignore rule. G9's "re-run `install.sh` on a snapshot" is the manual path that the Settings message points to after a rollback of a version whose database code changed (`docs/SECURITY.md` line 109).

## 4. The no-telemetry re-check (the `CLAUDE.md` per-release ritual)

**Finding: the claim holds on `91780c9eb`. The app sends no telemetry.** No path sends data about the user, their usage or crashes, and none pings for versions without a click. Every outbound path carries the corpus's own work. Each is gated by a click, an opted-in ride-along, or, for the vLLM status probe, an `OO_VLLM_URL` the operator set. Two reaches are not yet named in `docs/SECURITY.md` as they should be (§7 P2, P3), and the AI install does not refuse protected mode as the update does (P4).

**The ratchet was run** on `91780c9eb`, 2026-11-20:
- `tests/test_network_consent.py`: 22 passed. This includes the three tests the brief names: `::test_no_new_socket_importers`, `::test_no_new_socket_capable_importers`, `::test_every_socket_importer_allowance_states_a_reason`.
- The ratchet covers 16 socket-capable libraries: `requests`, `httpx`, `urllib.request`, `urllib3`, `http.client`, `aiohttp`, `websockets`, `ftplib`, `smtplib`, `imaplib`, `poplib`, `telnetlib`, `socket`, `opentimestamps`, `paramiko`, `pycurl`.
- Its allowances: 10 socket-capable importers under `src/` (the 4 HTTP-library importers among them) and 16 under `scripts/`, each with a written reason.
- The guards behind it: `tests/test_airplane_socket_guard.py`, `tests/test_ssrf_connect_guard.py` and `tests/test_boot_airplane_never_revokes_online.py`, 85 passed and 2 skipped. Both skips are at `test_airplane_socket_guard.py:664`, "this host cannot create a socket of that family": a sandbox limit, not a failure.
- The self-update and consent-coverage tests, `tests/test_self_update.py` and `tests/test_consent_coverage.py`: 155 passed.

**The outbound call sites were re-read.** §5's table lists every lane with its call site and its gate.

**Two things were checked beyond the libraries:**
- **Processes the app spawns.**
  - The AI installer and vLLM setup (`src/llm/installer.py:442`, `src/llm/vllm_lifecycle.py:3704`, `:3814-3854`) and the update's `git fetch` (`scripts/apply_update.py:315`) are each gated before the spawn.
  - The Ollama daemon (`src/llm/ollama_lifecycle.py:189`) is deliberately started even in airplane mode. It binds loopback and makes offline inference possible (`:30-39`). It starts with `OLLAMA_NO_CLOUD=1` (`:176`), and its egress, a model pull, is refused offline at the client (`src/llm/ollama.py:817`). As a separate process it is outside the socket guard, and that is disclosed.
  - `vllm serve` starts with `HF_HUB_OFFLINE=1` and `VLLM_NO_USAGE_STATS=1` (`vllm_lifecycle.py:2112-2116`, environment passed at `:2458`), so the served model does not phone home.
- **The browser.** The page's CSP is `connect-src 'self'` (`src/api/main.py:1061`). The exception is the opt-in `OO_API_DOCS=1` API pages, which load from a CDN (`:1064-1066`, disclosed at `docs/SECURITY.md:27`). No script in `src/static` fetches a non-loopback origin. The only outbound links are click targets behind the external-link confirm (UI invariant #7), for example the map credits (`src/static/app-map.js:1533`, `:3709`).

**The line for the release notes**, for the session that writes the 0.9.0-beta.1 notes (S7):

> No-telemetry re-check: the socket-importer ratchet (`tests/test_network_consent.py`, 16 socket-capable libraries, every allowance with a reason) passes on this tag. The outbound call sites were re-read against `docs/SECURITY.md` at `91780c9eb` (`docs/audit/SECURITY_REVIEW_0.9.md`), and the changes from there to this tag were re-read before tagging. The app sends no telemetry.

**For S7:** run the ratchet on the tagged SHA and re-read `git diff 91780c9eb <tag>` for new socket importers, spawns and hosts. If the ratchet fails, or the diff adds a socket importer or a host that `docs/SECURITY.md` does not name, do not publish this line until that is resolved.

## 5. The SSRF and airplane guards against every host since 0.3

**Finding:**
- Every in-process lane is behind the airplane socket guard.
- Every in-process lane is also behind the connect-time SSRF guard, with three exceptions:
  - the mailbox and the custody calendars, both by design and both disclosed;
  - the vLLM port probe (P3), which has the socket guard only.
- Every spawned process that egresses is gated before it starts, except the Ollama daemon. It starts ungated by design (it binds loopback and makes offline inference possible), and its egress, a model pull, is refused at the client (`src/llm/ollama.py:817`; §4).
- Every `docs/SECURITY.md` row (lines 92-111) has a live code path, and every "Where in the tree" anchor resolves.
- Two things the code reaches are not named where they should be (P2, P3), and one spawned lane does not refuse protected mode (P4).

Note that `docs/SECURITY.md` line 109 calls the update check "one guarded fetch"; it is one or more paginated `GET`s (§3), which P1's edit of that line can correct.

**The common gates:**
- **Airplane socket guard:** `src/ingest/airplane.py:858`, installed at boot, at lifespan and at unlock (§2). It refuses at `_guarded_getaddrinfo` (`:346`) and at the connect and `create_connection` wrappers (`:387`, `:439`, `:718`). Spawned processes are outside its reach by construction. That is why each spawn that egresses has its own gate below.
- **`EthicalFetcher`:** `src/ingest/__init__.py:1192`. The kill-switch refusal is at `:2004-2005`, inside `_guarded_redirect_get` (`:1957`). The connect-time SSRF guard (`src/ingest/ssrf_guard.py`) is entered at `:2023` and `:2052`.
- **The guarded session** (`src/safety/fetcher.py`): kill switch at `:376`, host lists at `:392-395`, connect-time SSRF guard at `:401-415`. So a lane that uses a guarded session instead of the ethical fetcher is SSRF-covered too. That includes the sessions with no host list:
  - user-pasted JSON-stat (`src/stats/fetch.py:385`);
  - Wikipedia dumps (`src/wiki/dumps.py:800`, `:808`);
  - OSM extracts (`src/geo/osm_downloads.py:770`, `:778`);
  - segmented downloads (`src/ingest/segmented_download.py:145`, `:160`).

| Lane (`SECURITY.md` row) | Code | Kill switch | Connect-time SSRF guard |
|---|---|---|---|
| Press collection | `src/ingest/crawl.py`, `src/monitoring/preflight.py`, `src/monitoring/health.py:55-62` | ethical fetcher | yes |
| Source discovery | `src/catalog/discover.py:51`, `src/catalog/wikidata_apply.py:48` | `discover.py:96` + guarded session | yes |
| Wikipedia / Wikimedia | `src/wiki/client.py:70`, `src/wiki/ores.py:137`, `src/wiki/dumps.py:800` | guarded session; dumps also at `dumps.py:344`, `:651`, `:719` | yes |
| Maps / OSM | `src/geo/osm_downloads.py:770`, `src/osm/replication.py:207` | `osm_downloads.py:364`, `:628`, `:693`; `replication.py:191` | yes |
| Law | `src/law/track.py:370`, `:740` | ethical fetcher | yes |
| Official statistics | `src/stats/fetch.py:300-385`, `src/api/stats.py:184` | `stats/fetch.py:582` + guarded session | yes (the pasted URL has no host list) |
| Markets & commodities | `src/markets/pipeline.py:81`, `src/markets/csv_feeds.py:305` | `pipeline.py:163`, `:205` + ethical fetcher | yes |
| Calendars | `src/events/feeds.py:676` | `feeds.py:1016` + ethical fetcher | yes |
| Hazard feeds | `src/api/hazards.py:30-32`, `:65` | ethical fetcher | yes |
| Keyword translations | `src/analytics/ring_loader.py:333` | `ring_loader.py:363`, `:384` | yes |
| Places and people | `src/entities/items.py:194` | `items.py:241`, `:258` | yes |
| Climate series | `src/stats/fetch.py:73-97`, `:651`, `:816` (host and path lists at `:214-223`, `:817-818`) | kill checks in `stats/fetch.py` + guarded session | yes |
| IPCC reports | `src/ingest/ipcc_spm.py:116` | `ipcc_spm.py:201` | yes |
| Medical papers | `src/medical/fetch.py:134` | `medical/fetch.py:140`, `:247`, `:281` | yes |
| Weather | `src/weather/openmeteo.py:34`, `:176` | ethical fetcher | yes |
| Discover by topic | `src/services/duckduckgo.py:206`, `:650`, `:456`, `:504` | guarded session + ethical fetcher | yes |
| Local AI, in process | `src/llm/installer.py:488` | `installer.py:346-360` (the AI egress window) | yes |
| Local AI, spawned | `installer.py:442`; `vllm_lifecycle.py:3704`, `:3814-3854` | gated before the spawn: `installer.py:414`; `vllm_lifecycle.py:3684`, `:3925` | n.a. (outside the process) |
| Local AI, model pull | `src/llm/ollama.py:801` | `ollama.py:817` | n.a. (Ollama's daemon) |
| App updates | check at `self_update.py:181`; spawn at `:440-444` (`launch_helper`, `:412`) | check: guarded session; apply: `:308`, `:314` → `:340-350` | check yes; `git` n.a. |
| Newsletter mailbox | `src/ingest/email.py:778` (IMAP), `:939` (POP) | `email.py:300-308`, called at `:768`, `:928` and before every command (R640) | no; see below |
| Chain of custody | `src/custody/timestamp.py:42-46` | `timestamp.py:239-241` + the socket guard | no (three fixed calendar hosts) |

**What "yes" means in the last column.** The connect-time check fully covers a direct connection and a proxy given as an IP literal (the documented `socks5://127.0.0.1:9050` shape). With a proxy given as a hostname it stands down for that request. With a remote-resolving proxy (`socks5h`/`socks4a`) there is no local resolution to check, because the exit resolves (`src/ingest/ssrf_guard.py:44-68`). In both of those cases the pre-fetch `_guard_target` policy is unchanged.

**Hosts added since 0.3** (`v0.3.0` = `917e8095f8`, 2026-08-23; the clone is not shallow; PR numbers checked against the first-parent history of `91780c9eb`). At `v0.3.0`, `docs/SECURITY.md` had no host table, only prose naming DuckDuckGo, Open-Meteo, World Bank/Eurostat, `api.github.com` and Ollama pulls. Each host below appears in the table above with its gate.

- **Earlier, PR #1075 (2026-09-08):** `ourworldindata.org`, `earthquake.usgs.gov`, the three OpenTimestamps calendars.
- **The table itself, PR #1135 (2026-09-16).** Mostly documentation catching up with code that already egressed: press, source discovery, Wikipedia (ORES, dumps), OSM (Geofabrik, planet), law, markets, calendars, hazards, local AI (`huggingface.co`, `pypi.org`, `objects.githubusercontent.com`), the mailbox and custody.
- **Later rows and hosts:**
  - keyword translations (#1148);
  - `stream.wikimedia.org` and `wikimedia.org` pageviews (#1155);
  - `release-assets.githubusercontent.com` and `ollama.com` (#1191);
  - places and people (#1206);
  - the OSM full-history planet (#1217);
  - the release run's `huggingface.co` read (#1394);
  - Geofabrik `-updates` (#1720);
  - GISTEMP (#1751), IPCC (#1759), GHCN (#1763), NSIDC (#1767), OWID bulk (#1789), ONI on `www.cpc.ncep.noaa.gov` (#1768);
  - app updates (#1810);
  - PubMed on `ftp.ncbi.nlm.nih.gov` (#2148).

**The mailbox is outside the SSRF guard, by design and stated.**
- `imaplib`/`poplib` connect to the server you name, with no public-address check. A loopback or LAN address is accepted while online, and the socket guard lets loopback through.
- That is a real use: a local mail bridge listens on `127.0.0.1`. The user, and only the user, names the host.
- The row already says the mailbox is "not the ethical fetcher". No row proposed.

## 6. Smaller observations, no row proposed

- `docs/SECURITY.md:36` says "Last checked **2026-09-26**". This review is a later check, and P2-P4 will move that date when they land.
- `tests/test_session_host_list.py:1647` gives the unlisted `src/stats/fetch.py` session the reason "the statistics agencies' catalogue URLs". The one unlisted call there is the user-pasted JSON-stat URL (`stats/fetch.py:385`, from `src/api/stats.py:184`). The reason text should say so. This is folded into P2.
- `docs/SECURITY.md:114` calls `configs/places_gazetteer.yml` "a repository file". It is not in the tree yet (`src/catalog/cities.py:42` reads it only if present). It is not an egress host, so this is only a wording fix for whichever PR adds the file.
- The release run's `_law_probe` and `_ores_probe` (`src/monitoring/release_run.py:2571`, `:1633-1636`) reach hosts already in the law and Wikipedia rows. The prose at `docs/SECURITY.md:157-165` names only its Hugging Face read. No new host, so no row.

## 7. Proposed rows (each its own PR; none is fixed here)

| # | Row | Why | Gates |
|---|---|---|---|
| P1 | **Self-update: tags only, with no `main` fallback.** Remove `MAIN_URL` and the `kind: "main"` path (`self_update.py:51`, `:234-252`). Make `validate_apply` (`:404`) and the helper (`scripts/apply_update.py:300`, `:314`) refuse any ref that is not a `vX.Y.Z` tag. With no release tag, the check answers "no release published yet" and offers nothing to install. Update `::test_check_falls_back_to_main_only_when_no_tag_exists` to pin the refusal, and update the hosts cell of `docs/SECURITY.md` line 109 ("or `main`'s tip when no release tag exists"). | Q1136 = a says "tags only". The fallback is inert while a `vX.Y.Z` tag exists. If the tags were removed or renamed, or the tag read returned no parseable tag, the check would offer `main`'s unreleased tip. A fork cannot reach it: the repository is pinned (`self_update.py:46-47`, `:132-133`). | Egress class: two security reads, full line. |
| P2 | **Discover by topic: disclose the result sites.** Row 107 says `html.duckduckgo.com` "and only that host". But `discover_sources_by_topic` then calls `discover_rss_feeds` on each new result domain, up to 50 (`src/services/duckduckgo.py:650`). That fetches the result page (`:456`) and probes its common feed paths (`:504`) through the ethical fetcher, from the opt-in endpoint (`src/api/source_management.py:1835`). Those fetches are robots-checked, SSRF-guarded and kill-switch-gated, but they go to arbitrary third-party domains DuckDuckGo chose. Fix the row and the consent popup's hover for that lane (`src/static/net-hosts.js`) in the same diff, as `docs/SECURITY.md:33-35` requires, or ask whether the follow-on fetch should be its own click. Fold in the `test_session_host_list.py:1647` reason text (§6). | A consent statement that names fewer hosts than the code reaches. This is the #14e failure shape: the step that runs before the action. | Consent text: two security reads; ×12 if the hover changes. |
| P3 | **The vLLM port probe stops at the loopback refusal.** `port_occupant()` (`src/llm/vllm_lifecycle.py:958`) runs on `GET /api/llm/vllm/status`, which Settings reads with no click (`src/api/llm.py:987`). It first builds a `VllmClient`, whose loopback refusal raises. That refusal is swallowed (`src/llm/vllm_lifecycle.py:982-985`, `except Exception: pass`), and the code falls through to a raw `connect_ex` on the `OO_VLLM_URL` host (`vllm_lifecycle.py:942`, `:990`). Stop on that refusal, as `vllm_client.py:231` and `ollama.py:543` do, or name the probe in `docs/SECURITY.md`. | It is the one in-process connect to an operator-chosen host that is behind neither the table nor a loopback check. It sends no payload, needs an operator environment variable, and is refused in airplane mode by the socket guard. But it runs without a click and goes direct in protected mode. | Network: two security reads. |
| P4 | **AI install in protected mode: refuse it, as the update does.** The update helper refuses in protected mode (`self_update.py:340-350`). The AI install's spawned steps check only the egress window (`installer.py:346-360`; `vllm_lifecycle.py:2755`). The click texts do say the download goes "over the clear internet — not through your configured proxy or Tor" (`src/static/index.html:4363-4364`, the AI egress dialog; also `app-settings.js:352`, `app-ai-tools.js:1314`, `:1331`). But when the app is already online, `ensureAiEgress` returns before that dialog (`app-core.js:1764`), and the remaining texts name only Tor, not a protected-mode SOCKS pool. The row would refuse the AI install's spawned steps while protected mode is chosen, with a named reason, as the update does. | "Never silently downgrade transport." The downgrade is disclosed on most paths, but not on the already-online one, and the sibling spawn refuses. | Consent and transport: two security reads, ×12. |

## 8. What closes row E, and what does not

- This report is the first half of row E's "closes when".
- The second half is the re-check stated in the release notes: §4's line, with the S7 re-run on the tagged SHA.
- **`RC14` adds a third item that the brief's acceptance sentence does not name: the I3 slice.** As ruled, I3 is built at row E, so row E would close only once that slice ships, unless the maintainer moves it after the beta (§1). The brief and `RC14` disagree here, and this report names the disagreement rather than settling it.
- Row E stays **OPEN**.
- I4's park (§2) is a finding awaiting the maintainer's ruling. Signed releases wait on the key and its trust root (§3).
