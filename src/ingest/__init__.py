"""
Ethical HTTP fetching: the single, mandatory fetch path for ingestion.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every byte the platform ingests goes through here. The guarantees (PRODUCT_SYNTHESIS
§3.4 "Ethical by construction", "Fail *closed*"):

  * robots.txt is honoured, per-host cached, and **fail-closed**: if we cannot
    positively determine that a URL is allowed (network error, timeout, 5xx, or a
    restricted 401/403 on robots.txt), we do NOT fetch it. This is the opposite of
    the old EthicalScraper, which assumed "allowed" on any error.
  * a per-host minimum request interval is enforced (honouring robots Crawl-delay
    when larger), so we never hammer a source.
  * an honest, identifying User-Agent is sent.
  * only HTML is returned for article ingestion; other content types are rejected.

There is exactly one network path and no raw-requests bypass.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import math
import os
import socket
import sys
import threading
import time
import weakref
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urljoin, urlparse, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests

# Importing urllib3_log puts the request-path filter on urllib3's loggers (R142).
from src.ingest import urllib3_log as _urllib3_log  # noqa: F401
from src.ingest.fetch_verdict import (
    KILL_SWITCH_REFUSAL,
    KILL_SWITCH_REFUSAL_HEAD,
    failure_netloc,
    failure_url,
    userinfo_secrets,
)
from src.ingest.ssrf_guard import (
    BlockedConnectTarget,
    connect_scope,
    is_blocked_ip,
)
from src.monitoring.activity import activity_monitor
from src.monitoring.secret_scrub import log_failure, record_text

_LOG = logging.getLogger(__name__)

try:  # Single source of truth is pyproject; never hardcode a version literal.
    _OO_VERSION = _pkg_version("open-omniscience")
except PackageNotFoundError:  # raw checkout / not installed -> honest fallback
    _OO_VERSION = "0.0.0"

# Public alias so other honest-UA builders (the wiki client, ORES, dumps) share
# the one version source instead of hardcoding a stale literal.
OO_VERSION = _OO_VERSION

DEFAULT_USER_AGENT = (
    f"OpenOmniscienceBot/{_OO_VERSION} (+https://github.com/ideotion/Open-Omniscience; "
    "ethical research crawler)"
)


@dataclass
class FetchResult:
    """A successfully fetched page with provenance.

    ``status_code`` may be 304 (Not Modified) when the caller passed
    conditional-GET headers and the resource is unchanged; in that case
    ``content`` is empty and the caller should reuse what it already has. ``etag``
    and ``last_modified`` carry the response's validators (when present) so the
    caller can persist them for the next conditional request.
    """

    requested_url: str
    final_url: str  # after redirects
    status_code: int
    content: str  # decoded HTML
    content_type: str
    fetched_at: datetime
    etag: str | None = None  # response ETag (opaque validator), if sent
    last_modified: str | None = None  # response Last-Modified, if sent
    # The server IP we actually connected to (data-architecture Slice 6a). It is OUR
    # VANTAGE POINT -- usually a CDN edge / anycast address, NOT the publisher's origin.
    # Available only on a DIRECT clearnet connection: over a SOCKS proxy / Tor the socket
    # connects to the proxy, not the server, so the real server IP is unavailable and
    # ``server_ip`` is None with a stated ``server_ip_reason`` -- never a guess.
    server_ip: str | None = None
    server_ip_reason: str | None = None  # why server_ip is None (honest, when unavailable)
    # The UNDECODED response bytes, attached ONLY when the caller passes
    # ``keep_bytes=True`` (default None ⇒ zero memory cost on the scrape hot path).
    # Needed for binary bodies (e.g. a PDF law) whose bytes are destroyed by the
    # text-decode path; already bounded by ``max_bytes``.
    raw_content: bytes | None = None


class FetchError(Exception):
    """Base class for all fetch failures (never silently swallowed)."""


class RobotsDisallowed(FetchError):
    """robots.txt explicitly disallows this URL for our user agent."""


class RobotsUnavailable(FetchError):
    """robots.txt could not be determined -> fail closed, do not fetch.

    ``cause`` NAMES WHICH OF THREE DIFFERENT FACTS THIS IS, because they were one bucket
    until 2026-09-11 and the difference decides what a caller may honestly do next:

      * ``"refused"``      401/403 -- the host (or something in front of it) declined to
                           serve robots.txt on THIS path. Over Tor that is frequently the
                           exit's reputation rather than the publisher's wish, and nothing
                           in the answer says which, so it is never read as a policy.
      * ``"server_error"`` 5xx or an unexpected status -- the host is broken, not speaking.
      * ``"unreachable"``  a network failure, timeout, SSRF-blocked redirect or redirect
                           loop -- we never got an answer at all.

    A 404/410 is NOT here: no robots.txt means everything is allowed, and ``_get_robots``
    returns an empty parser for it. So this exception only ever covers a refusal or a
    failure -- never an absence.

    FAIL-CLOSED IS UNCHANGED for every one of them: the fetch is refused either way. The
    cause exists so the CATALOGUE can stop spending an absence like a verdict.
    """

    def __init__(self, message: str, *, cause: str = "unreachable") -> None:
        super().__init__(message)
        self.cause = cause


class CrawlDelayDeferred(FetchError):
    """The host's own ``Crawl-delay`` puts the next allowed fetch too far out to wait
    for inline (S04-13 S2; RULED 2026-09-15, answer sheet Q1013 = a).

    DELIBERATELY NOT A :class:`FetchFailed`. Nothing failed: the host asked us to wait
    and we are respecting that, so a caller counting this as a source failure would
    back the source off, or disqualify it, for doing exactly what it said it wanted.
    It is a DEFERRAL and the collector counts it in its own bucket.

    WHAT IT REPLACED, and the arithmetic that made it necessary (measured 2026-09-10 on
    the candidate kit's first live run): ``EthicalFetcher`` sleeps the declared delay
    before EVERY request, so one host costs ``delay x requests``, uncapped -- three
    hosts took 5409 s, 3621 s and 1829 s of a single run, and the pool could not end
    until its slowest member did. Refusing the wait alone would not have fixed it,
    because ``make_fetcher`` builds a fresh fetcher per collection pass and the
    in-memory ``_last_request`` goes with it: a host declaring ``Crawl-delay: 3600``
    would have been re-fetched on the very next pass, every pass, which is worse than
    no politeness at all. Hence the PERSISTED next-allowed-at this exception is the
    refusal half of.

    ``not_before`` is WALL-CLOCK (``time.time()``), because it is compared across
    processes; ``delay_s`` is the host's own declared figure.
    """

    def __init__(self, message: str, *, netloc: str, delay_s: float, not_before: float) -> None:
        super().__init__(message)
        self.netloc = netloc
        self.delay_s = delay_s
        self.not_before = not_before


class FetchFailed(FetchError):
    """The page itself could not be fetched, or was not usable HTML."""


class BlockedTarget(FetchFailed):
    """The URL (or a redirect of it) resolves to a non-public address (SSRF guard)."""


class RedirectOutOfScope(FetchFailed):
    """A redirect hop out of the scope the caller kept the fetch to (R629): a crawl kept to one site
    (``CrawlConfig.same_domain_only``) or a sitemap index, whose hop to another site is refused before anything is
    asked of that site (no lookup, no robots.txt read, no request). Deterministic, never retried; a ``FetchFailed``,
    so every caller that counts a page it could not have counts this one."""


# How long a robots.txt decision is cached, in seconds.
_ROBOTS_TTL = 3600.0

# PER-HOST BACKOFF FOR A ROBOTS FAILURE (2026-09-11 ruling: "so refused rows expire").
#
# THE COST IT REMOVES, measured: the completed 22,045-row run left 7,847 hosts whose
# robots.txt could not be read. At a flat one-hour TTL every one of them is re-asked every
# hour, for ever -- 7,847 requests an hour of pure refusal traffic against publishers who
# already declined once. Doubling from the same one-hour base settles a persistently
# refusing host at one request a day instead.
#
# IT IS A DEFERRAL, NEVER AN EXCLUSION -- the same guarantee, and the same wording, the feed
# de-churn backoff gives (see FeedFetchState): the CAP means every host is re-asked within
# _ROBOTS_BACKOFF_CAP_S however long it has been failing, and a single success clears the
# counter completely. Nothing is ever struck off; a refusal only gets quieter.
#
# WHY IT LIVES WITH THE DECISION rather than in its own table: robots is a PER-HOST fact and
# FeedFetchState is keyed per SOURCE, so two sources on one host would each carry their own
# backoff and each would keep asking -- the opposite of the point. Cached and persisted
# beside the decision it belongs to, so there is ONE authority over when a host is re-asked.
def _robots_backoff_cap_s() -> float:
    """Read live (not frozen at import) so a test or an operator can change it without
    re-importing the module; floored at the base TTL, since a cap below it would mean a
    failure is cached for LESS time than a success, which is backwards."""
    try:
        value = float(os.getenv("OO_ROBOTS_BACKOFF_CAP_S", "") or 24 * 3600.0)
    except ValueError:
        value = 24 * 3600.0
    return max(value, _ROBOTS_TTL)


def _robots_ttl_for(consecutive_failures: int) -> float:
    """Seconds to cache a robots decision after ``consecutive_failures`` failures in a row.

    Zero failures (a decision we actually read) is the plain TTL. Then 1h, 2h, 4h ... to the
    cap. Pure, so the schedule is asserted directly rather than inferred from timing.
    """
    if consecutive_failures <= 0:
        return _ROBOTS_TTL
    exp = min(consecutive_failures - 1, 32)          # cap the exponent before the min()
    return min(_ROBOTS_TTL * (2.0**exp), _robots_backoff_cap_s())

# --------------------------------------------------------------------------- #
# A5 (2026-07-24 throughput brief, C4): persist the robots.txt verdict cache to
# a small local JSON sidecar so a cold start reuses in-TTL decisions instead of
# re-fetching robots.txt for every host. This is a SHARPER win than "across
# restarts" alone: make_fetcher() builds a brand-new EthicalFetcher (empty
# in-memory cache) once per COLLECTION PASS (see _default_run_once), so
# WITHOUT this the whole robots cache was already being thrown away every
# pass, not merely across a real app restart.
#
# Persisted as WALL-CLOCK time (time.time()), never the in-process MONOTONIC
# clock _get_robots stores internally (self._now = time.monotonic, whose
# epoch/reference point is arbitrary per process and platform) -- a raw
# monotonic value written by one process is meaningless read back by
# another. On load, the remaining TTL is recomputed from the wall-clock delta
# and re-expressed in the CURRENT instance's own monotonic frame.
# --------------------------------------------------------------------------- #
_ROBOTS_PERSIST_LOCK = threading.Lock()


def _robots_cache_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "robots_cache.json"


def _robots_persist_enabled() -> bool:
    return os.environ.get("OO_ROBOTS_CACHE_PERSIST", "1") != "0"


# ONE ENTRY PER HOST (R621). Every per-host record -- the robots decision, its cause and failure count, the host-schedule stamp,
# the politeness interval, the per-host lock, the Tor circuit -- and both sidecars are keyed by the host and port a request goes
# to, never by the URL's userinfo, and never by how the host and port happen to be SPELLED. Before, they were keyed by
# ``scheme://netloc`` and ``netloc`` as written: a credentialed and a plain URL to one host were two hosts to the politeness code
# (two intervals, two locks, two robots reads), the user name and password were written into robots_cache.json and
# host_schedule.json, and the robots.txt read sent them as Basic auth; and ``HOST.Example``, ``host:``, ``host:080`` and
# ``https://host:443`` were each a host of their own (Steward 3's item 2), so a feed linking one site two ways doubled its rate.
# The page request itself is unchanged: it still carries the URL as given.

#: The default port of each scheme the fetcher speaks. A key never writes it: ``https://host:443`` is ``https://host``.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _host_netloc(netloc: str, scheme: str = "") -> str:
    """The host key for ``netloc``: the host and port a request goes to, in one spelling (R621).

    - The userinfo is out: ``urllib.parse`` takes it as everything before the LAST ``@`` and reads the host and port from what
      follows, and a host and port hold no ``@``.
    - The host is the one ``urllib.parse`` reads (``.hostname``), which is the name the SSRF guard checks: lower-cased, an IPv6
      literal in its brackets (a zone kept as written).
    - The port is its number: leading zeros gone (``host:080``), an empty port or port 0 gone (``host:``, ``host:0``: requests
      drops both and connects to the default), and the ``scheme``'s default
      port gone (80 for http, 443 for https). Without a scheme (a bare key read back from host_schedule.json, which records
      none) every explicit port stays, since ``host:443`` is the key of ``http://host:443``.
    - A trailing dot STAYS, deliberately (the stop clause of the fold, agreed with the coordinator): ``news.example.`` is an
      absolute name and ``news.example`` a relative one, which the resolver may complete through resolv.conf's search list
      (first, under ``ndots`` above one, as in a container; after an NXDOMAIN, under the default), so the two can be two hosts.
      Both parsers keep the dot, so the guard checks the dotted name, and a key without it would send the robots read to a name
      the guard never checked, or hand one name's robots answer and backoff to the other.

    Equal keys are therefore equal ``urllib.parse`` hosts and ports, and the robots URL built from the key reaches the host the
    guard checked; ``_refuse_parser_mismatch`` has already refused any URL that urllib3 reads as another host. Never raises: a
    host and port ``urllib.parse`` cannot read (a port out of range, a bracket it refuses, no host) come back as written after
    the userinfo (:func:`_readable_host_key` says ``None`` for them), and the fetcher refuses such a URL before any key is
    taken."""
    key = _readable_host_key(netloc, scheme)
    return netloc.rpartition("@")[2] if key is None else key


def _readable_host_key(netloc: str, scheme: str = "") -> str | None:
    """:func:`_host_netloc`'s key, or ``None`` when ``urllib.parse`` cannot read a host (and port) out of ``netloc``. Never
    raises. The activity monitor reads this one, and labels such a fetch from the masked URL instead."""
    try:
        parts = urlsplit("//" + netloc.rpartition("@")[2])
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if not port or port == _DEFAULT_PORTS.get(scheme):  # port 0 is the default: requests drops it and connects there (R624 read)
        return host
    return f"{host}:{port}"


#: The fixed words a robots refusal (401/403) adds when the page address carried a user name or password (R621, the independent
#: read's N2): the read is anonymous, so the refusal may be the login's, not a policy or an exit's reputation.
_ROBOTS_READ_WITHOUT_USERINFO = "robots.txt is read without the page address's credentials"


def _carries_userinfo(url: str) -> bool:
    """Whether ``url``'s authority holds a userinfo (an ``@``, as ``urllib.parse`` reads it). Never raises."""
    try:
        return "@" in urlparse(url).netloc
    except Exception:  # noqa: BLE001 - written from inside a refusal; an unreadable URL adds no words
        return False


def _robots_key_is_normal(key: str) -> bool:
    """Whether a robots-cache key is ``scheme://`` and the host key of what follows, as :meth:`EthicalFetcher.fetch` writes it."""
    scheme, sep, netloc = key.partition("://")
    return bool(sep) and key == f"{scheme}://{_host_netloc(netloc, scheme)}"


def _schedule_key_is_normal(key: str) -> bool:
    """Whether a host-schedule key is its own host key (the scheme-free form: the file records no scheme)."""
    return _host_netloc(key) == key


def _drop_unkeyed_robots(raw: dict) -> dict:
    """The robots sidecar without the entries an older build keyed otherwise than the host key: by ``scheme://user:pass@host``,
    or by a spelling (``https://HOST.Example``, ``https://host:443``, ``http://host:080``) that the host now shares with every other
    spelling of it (R621). DROPPED, not merged: an entry is a cache whose absence the fetcher already handles as a fresh process
    does (the next fetch of the host reads its robots.txt again, fail-closed as ever), so a drop costs one robots.txt request; and
    a credentialed entry's decision was read WITH the URL's credentials, which is not the anonymous read the host's one entry now
    holds, so folding it in, or choosing between it and the host's own entry, would keep a decision no anonymous read made."""
    return {key: entry for key, entry in raw.items() if _robots_key_is_normal(key)}


def _stamp_of(entry) -> tuple[float, float] | None:
    """A schedule entry's ``(not_before, delay_s)``, or ``None`` when it has no readable, FINITE ``not_before``. A NaN or an
    infinity is absent, not a stamp: ``max`` with a NaN answers whichever came first, so a NaN host stamp made a credentialed
    stamp's wait disappear (the independent read's edge). A delay that is not a finite number reads as none."""
    try:
        not_before = float(entry["not_before"])
    except Exception:  # noqa: BLE001 - an unreadable stamp is skipped, as _load_host_schedule skips it
        return None
    if not math.isfinite(not_before):
        return None
    try:
        delay_s = float(entry.get("delay_s") or 0.0)
    except Exception:  # noqa: BLE001 - an unreadable delay is none, as _load_host_schedule reads it
        delay_s = 0.0
    return not_before, delay_s if math.isfinite(delay_s) else 0.0


def _merge_unkeyed_stamps(raw: dict) -> dict:
    """The schedule sidecar with each stamp an older build keyed otherwise than the host key (``user:pass@host``,
    ``HOST.Example``, ``host:080``, ``host:``) folded into the host key's (R621). MERGED, not dropped: a stamp is the host's own
    stated wish and lapses by time alone (there is no forget path, see below), so dropping one would let the host be fetched
    before it asked to be. The later ``not_before`` and the larger ``delay_s`` win, whichever key held them, as the longer wait
    wins in ``_respect_rate_limit``; an unreadable or non-finite stamp adds nothing and takes nothing away."""
    out = {key: entry for key, entry in raw.items() if _schedule_key_is_normal(key)}
    for key, entry in raw.items():
        host = _host_netloc(key)
        if host == key:
            continue
        stamps = [s for s in (_stamp_of(out.get(host)), _stamp_of(entry)) if s is not None]
        if stamps:
            out[host] = {"not_before": max(s[0] for s in stamps), "delay_s": max(s[1] for s in stamps)}
    return out


def _lend_default_port_stamps(stamps: dict[str, tuple[float, float]]) -> None:
    """In memory only: a bare ``host:80`` or ``host:443`` stamp also holds for ``host`` (R621). The file records no scheme, so
    ``host:443`` is either an older build's key for ``https://host:443`` (now keyed ``host``) or this build's for
    ``http://host:443``; the stamp is kept under its own key AND its wait is lent to ``host``, the later ``not_before`` and the
    larger delay winning. That never shortens a wait a host asked for; the cost, stated, is that ``host`` also waits out a
    stamp of ``http://host:443`` or ``https://host:80``."""
    for key, (not_before, delay_s) in list(stamps.items()):
        lent = _stamp_of({"not_before": not_before, "delay_s": delay_s})  # a non-finite value lends nothing (see _stamp_of)
        if lent is None:
            continue
        for scheme in _DEFAULT_PORTS:
            host = _host_netloc(key, scheme)
            if host == key:
                continue
            if host not in stamps:
                stamps[host] = lent
                continue
            held = _stamp_of({"not_before": stamps[host][0], "delay_s": stamps[host][1]})
            if held is not None:  # the host's own stamp, when it does not compare, is left as it was read
                stamps[host] = (max(lent[0], held[0]), max(lent[1], held[1]))


def _scrub_sidecar(path: Path, lock: threading.Lock, is_normal, scrub) -> None:
    """Take the keys an older build wrote otherwise than the host key out of the FILE at load, not only out of memory (R621): a
    user name and password it wrote are not left on disk for every later read-modify-write to carry forward. Runs whatever
    ``OO_ROBOTS_CACHE_PERSIST`` and ``OO_HOST_SCHEDULE_PERSIST`` say (Steward 3's item 4): with persistence off nothing new is
    written, but a file an earlier run left must not keep the credentials. Rewrites the file only when it holds such a key
    (atomic temp+replace, under the file's own lock), with nothing in it but what was there. Never raises: a failed rewrite
    leaves the file as it was, and the loaders and writers leave those keys out all the same."""
    try:
        with lock:
            if not path.exists():
                return
            raw = json.loads(path.read_text("utf-8")) or {}
            if not isinstance(raw, dict) or all(is_normal(key) for key in raw):
                return
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(scrub(raw)), "utf-8")
            tmp.replace(path)
    except Exception as exc:  # noqa: BLE001 - best-effort; the loaders and writers leave the keys out regardless
        log_failure(_LOG, f"host key scrub failed for {path.name}", exc, level=logging.DEBUG)


def _load_persisted_robots(
    path: Path, *, now_monotonic, now_wall: float | None = None
) -> dict[str, tuple[RobotFileParser | None, float]]:
    """Reconstruct ``{host_key: (RobotFileParser|None, monotonic_expiry)}`` from
    the persisted sidecar, DROPPING any entry whose wall-clock TTL has already
    lapsed -- an expired verdict must be re-fetched, never trusted stale (the
    fail-closed semantics are unchanged: a dropped/missing entry just means
    the next fetch recomputes it, exactly like a fresh process today)."""
    if not path.exists():
        return {}
    wall_now = now_wall if now_wall is not None else time.time()
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt sidecar must never break startup
        return {}
    out: dict[str, tuple[RobotFileParser | None, float]] = {}
    for host_key, entry in _drop_unkeyed_robots(raw or {}).items():
        try:
            fetched_at = float(entry["fetched_at"])
            kind = entry["kind"]
            # The entry's own TTL when it recorded one (the per-host backoff), else the
            # flat base -- which is exactly what an entry written before the backoff had.
            try:
                entry_ttl = float(entry.get("ttl") or _ROBOTS_TTL)
            except (TypeError, ValueError):
                entry_ttl = _ROBOTS_TTL
            remaining = entry_ttl - (wall_now - fetched_at)
            if remaining <= 0:
                continue  # expired -- re-fetch, never trust stale (NEGATIVE-SPACE)
            decision: RobotFileParser | None
            if kind == "parsed":
                rp = RobotFileParser()
                rp.parse(str(entry.get("body") or "").splitlines())
                decision = rp
            elif kind == "allow_all":
                rp = RobotFileParser()
                rp.parse([])
                decision = rp
            elif kind == "disallow_all":
                decision = None
            else:
                continue  # unknown shape -- skip rather than guess
            out[host_key] = (decision, now_monotonic() + remaining)
        except Exception:  # noqa: BLE001 - one bad entry must never break the whole load
            continue
    return out


def _persisted_robots_fails(path: Path) -> dict[str, int]:
    """``{host_key: consecutive_failures}`` from the sidecar. Absent (an entry written
    before the backoff existed) reads as 0, which only means the next failure starts the
    schedule from the base -- never that the host is treated as having succeeded."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text("utf-8")) or {}
    except Exception:  # noqa: BLE001 - a corrupt sidecar must never break startup
        return {}
    out: dict[str, int] = {}
    for host_key, entry in _drop_unkeyed_robots(raw).items():
        try:
            fails = int(entry.get("fails") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if fails > 0:
            out[host_key] = fails
    return out


def _persisted_robots_causes(path: Path) -> dict[str, str]:
    """``{host_key: cause}`` from the sidecar, for entries that recorded one.

    Separate from :func:`_load_persisted_robots` on purpose: that function's shape is
    pinned by tests and by a repo invariant, and a refusal's CAUSE is additive metadata
    rather than part of the decision. An entry written before the cause existed simply has
    none, and the reader then reports ``"unknown"`` -- which is the honest answer, and the
    reason this does not fall back to a plausible-looking default.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text("utf-8")) or {}
    except Exception:  # noqa: BLE001 - a corrupt sidecar must never break startup
        return {}
    out: dict[str, str] = {}
    for host_key, entry in _drop_unkeyed_robots(raw).items():
        try:
            cause = entry.get("cause")
        except Exception:  # noqa: BLE001 - one bad entry never breaks the load
            continue
        if isinstance(cause, str) and cause:
            out[host_key] = cause
    return out


def _persist_robots_entry(
    path: Path, host_key: str, *, kind: str, body: str | None, cause: str | None = None,
    fails: int = 0, ttl: float | None = None,
) -> None:
    """Best-effort: record ONE host's freshly-computed verdict in the persisted
    sidecar (read-modify-write, atomic temp+replace, lock-guarded against
    concurrent writers for different hosts). Never raises into the fetch path
    -- a write failure only means the next process/pass re-fetches this host,
    the SAME fail-closed fallback that already exists today."""
    try:
        with _ROBOTS_PERSIST_LOCK:
            raw: dict = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text("utf-8")) or {}
                except Exception:  # noqa: BLE001 - a corrupt sidecar starts fresh
                    raw = {}
            raw = _drop_unkeyed_robots(raw)  # an older build's credentialed or differently spelled key is never carried forward (R621)
            raw[host_key] = {
                "kind": kind, "body": body, "fetched_at": time.time(), "cause": cause,
                # The backoff must SURVIVE a restart, or every cold start would hand a
                # host that has refused fifty times a fresh one-hour clock -- which is
                # how a politeness measure quietly becomes no measure at all.
                "fails": fails, "ttl": ttl,
            }
            # Bound the persisted file the SAME way the in-memory cache is bounded
            # (_ROBOTS_CACHE_MAX) -- oldest-fetched entries evicted first.
            if len(raw) > _ROBOTS_CACHE_MAX:
                ordered = sorted(raw.items(), key=lambda kv: kv[1].get("fetched_at", 0))
                raw = dict(ordered[-_ROBOTS_CACHE_MAX:])
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(raw), "utf-8")
            tmp.replace(path)
    except Exception as exc:  # noqa: BLE001 - persistence is an optimisation, never required
        # the fetcher's key names the host only (R621: it holds no userinfo), so this writes the host; the mask and the secrets stay
        # for any other caller's key, which could carry one (R620, Steward 3 #2)
        log_failure(
            _LOG, f"robots cache persistence failed for {failure_url(host_key)}", exc, *userinfo_secrets(host_key), level=logging.DEBUG
        )


# --------------------------------------------------------------------------- #
# PER-HOST NEXT-ALLOWED-AT (S04-13 S2; RULED 2026-09-15, answer sheet Q1013 = a)
#
# "Persist a per-host next-allowed-at beside the robots cache; refuse an inline wait
# beyond a few minutes with a named deferral counted as its own bucket."
#
# WHY IT MUST BE PERSISTED, in one sentence: ``make_fetcher`` builds a NEW
# EthicalFetcher once per collection pass, so the in-memory ``_last_request`` is
# thrown away between passes -- and a refusal without a persisted stamp would
# therefore re-fetch a ``Crawl-delay: 3600`` host on every single pass, turning the
# refusal into a louder version of the impoliteness it exists to stop.
#
# WALL-CLOCK, never monotonic, for exactly the reason the robots sidecar states
# above: a monotonic value written by one process is meaningless read back by
# another. The two frames never meet -- the in-memory path compares monotonic
# stamps, this one compares wall stamps, and only the resulting WAIT (a duration,
# frame-independent) is compared between them.
#
# THERE IS DELIBERATELY NO "FORGET" / FORCE PATH. The recorded lesson that a
# backoff is a cache an operator's "do it again" will hit is about a DIAGNOSTIC
# retry, where re-asking is the whole point. This is not that: the stamp records a
# host's own stated wish, and an override would be evading it -- the same category
# as the Tor->clearnet fallback and the robots workaround the non-negotiables
# already forbid. A stamp lapses by TIME passing, and by nothing else.
# --------------------------------------------------------------------------- #
_HOST_SCHEDULE_LOCK = threading.Lock()

#: Bound the sidecar the same way the robots cache is bounded.
_HOST_SCHEDULE_MAX = 4096

#: THE CAP ("a few minutes"), and the measurement behind the value. The
#: candidate-kit run of 2026-09-10 recorded per-row elapsed at p50 16 s, p95 35 s
#: and p99 138 s, so a 180 s ceiling clips only the tail that a long declared
#: ``Crawl-delay`` explains and leaves every ordinary polite wait untouched.
#: Revisable: it is published in the PR as a chosen value, not a derived one.
_CRAWL_DELAY_MAX_WAIT_S = 180.0


def _crawl_delay_max_wait_s() -> float:
    try:
        value = float(os.getenv("OO_CRAWL_DELAY_MAX_WAIT", "") or _CRAWL_DELAY_MAX_WAIT_S)
    except (TypeError, ValueError):
        return _CRAWL_DELAY_MAX_WAIT_S
    # A zero or negative ceiling would refuse EVERY host, including the ones whose
    # politeness costs a second -- a misconfiguration must degrade to the default
    # rather than to a silent total stop.
    return value if value > 0 else _CRAWL_DELAY_MAX_WAIT_S


def _host_schedule_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "host_schedule.json"


def _host_schedule_persist_enabled() -> bool:
    return os.environ.get("OO_HOST_SCHEDULE_PERSIST", "1") != "0"


def _load_host_schedule(
    path: Path, *, now_wall: float | None = None
) -> dict[str, tuple[float, float]]:
    """``{netloc: (next_allowed_at_wall, declared_delay_s)}``, dropping lapsed stamps.

    THE DELAY IS CARRIED, not just the deadline, and that is not bookkeeping. A
    fetcher built for a NEW pass has an empty robots cache, so it cannot re-derive
    the host's declared ``Crawl-delay`` before it has fetched robots.txt again --
    and a refusal that reports the courtesy interval it fell back to (``1 s``)
    instead of the host's real ``3600`` would be a fabricated number inside the one
    sentence whose whole job is to say why the fetch did not happen. Caught by
    driving a second fetcher against a stamp the first one wrote.

    A lapsed stamp is simply absent, which is byte-identical in effect to a fresh
    process: the next fetch is allowed and re-stamps. A corrupt sidecar starts
    empty rather than raising -- politeness degrades to the in-memory interval,
    which is the same floor that applied before this existed.
    """
    if not path.exists():
        return {}
    wall_now = time.time() if now_wall is None else now_wall
    try:
        raw = json.loads(path.read_text("utf-8")) or {}
    except Exception:  # noqa: BLE001 - a corrupt sidecar must never break a pass
        return {}
    out: dict[str, tuple[float, float]] = {}
    for netloc, entry in _merge_unkeyed_stamps(raw).items():
        try:
            not_before = float(entry["not_before"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            delay_s = float(entry.get("delay_s") or 0.0)
        except (TypeError, ValueError):
            delay_s = 0.0
        if not_before > wall_now:
            out[str(netloc)] = (not_before, delay_s)
    _lend_default_port_stamps(out)
    return out


def _stamp_remaining(not_before: float, delay_s: float, min_interval_s: float, netloc: str = "") -> float:
    """How long a persisted stamp still asks us to wait -- CLAMPED to the stamp's own
    delay (RR-9, field round 2026-09-24).

    A legitimate stamp is written as "now + the interval", so it can never lie further
    ahead of now than that interval. One that does was written on a clock that has since
    been CORRECTED: the NUC booted 12 hours fast, stamped legislation.gov.uk's 10-second
    crawl-delay on that clock, and after NTP set it right the probe was refused as "not
    before 13:49Z" at 06:35Z -- seven hours of politeness nobody had asked for, and one
    of row Q's three hosts lost. Clamping keeps the host's own stated wish (its delay,
    in full) and drops only the clock error; a stamp can still never be SHORTENED below
    what the host declared, because the bound is that declaration."""
    remaining = max(0.0, not_before - time.time())
    bound = max(float(delay_s or 0.0), float(min_interval_s or 0.0))
    if remaining > bound:
        _LOG.info(
            "politeness stamp for %s lay %.0f s ahead against its own %.0f s delay "
            "(written on a clock since corrected); waiting the delay instead",
            netloc or "a host", remaining, bound,
        )
        return bound
    return remaining


def _persist_host_schedule(path: Path, netloc: str, not_before: float, delay_s: float) -> None:
    """Best-effort read-modify-write of ONE host's next-allowed-at.

    Never raises into the fetch path: a write failure means the next pass falls back
    to the in-memory interval for this host, which is the behaviour that existed
    before this sidecar and is still polite, merely less so across a restart.
    """
    try:
        with _HOST_SCHEDULE_LOCK:
            raw: dict = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text("utf-8")) or {}
                except Exception:  # noqa: BLE001 - a corrupt sidecar starts fresh
                    raw = {}
            raw = _merge_unkeyed_stamps(raw)  # an older build's credentialed or differently spelled key is folded in, never carried forward (R621)
            raw[netloc] = {"not_before": float(not_before), "delay_s": float(delay_s)}
            if len(raw) > _HOST_SCHEDULE_MAX:
                # Evict the entries that lapse SOONEST: they are the ones whose loss
                # costs least (they were about to be allowed anyway), where dropping a
                # far-future stamp would silently re-permit the very host that asked
                # hardest to be left alone.
                ordered = sorted(
                    raw.items(),
                    key=lambda kv: (kv[1] or {}).get("not_before", 0)
                    if isinstance(kv[1], dict)
                    else 0,
                )
                raw = dict(ordered[-_HOST_SCHEDULE_MAX:])
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(raw), "utf-8")
            tmp.replace(path)
    except Exception as exc:  # noqa: BLE001 - persistence is an optimisation, never required
        # the fetcher's netloc names the host only (R621: it holds no userinfo), so this writes the host; the mask and the secrets
        # stay for any other caller's netloc, which could carry one (R620, Steward 3 #2)
        log_failure(
            _LOG,
            f"host schedule persistence failed for {failure_netloc(netloc)}",
            exc,
            *userinfo_secrets(f"//{netloc}"),
            level=logging.DEBUG,
        )


def _env_cap(name: str, default: int, *, floor: int) -> int:
    """Parse a positive integer cap from the environment, defensively."""
    try:
        return max(floor, int(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return default


# Per-pass host-cache bounds (P0.3 E1, field event 2026-07-09: a 21.6-hour
# marathon pass accumulated memory until the kernel OOM-killer fired). The
# robots cache holds a RobotFileParser (rule lists can be tens of KB for big
# sites) per host ever contacted; on a very wide crawl that grows for the whole
# pass. Bounding it costs at most a robots RE-FETCH for an evicted host (the
# fail-closed semantics are unchanged — an evicted entry is simply recomputed).
_ROBOTS_CACHE_MAX = _env_cap("OO_ROBOTS_CACHE_MAX", 4096, floor=64)
# The per-host last-request timestamps are tiny but also unbounded. POLITENESS
# WINS OVER THE BOUND: an entry is evicted only when its host was last fetched
# more than _LAST_REQUEST_SAFE_AGE_S ago (default 6 h — far beyond any plausible
# robots Crawl-delay), so eviction can never permit an early re-fetch. If every
# entry is younger than that, the map is left over-cap (a dict of floats; the
# honest trade).
_LAST_REQUEST_MAX = _env_cap("OO_HOST_STATE_MAX", 8192, floor=64)
_LAST_REQUEST_SAFE_AGE_S = 6 * 3600.0
# Bound on redirects followed (each hop is re-validated against the SSRF guard).
_MAX_REDIRECTS = 5
# HTTP statuses worth retrying (transient server-side / rate-limit signals). 4xx
# client errors are deterministic and never retried (finding BUG-02).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: How far ``_carries_airplane_refusal`` looks. The deepest real link is three (R619's shape: requests' ProxyError -> MaxRetryError ->
#: urllib3's ProxyError -> AirplaneModeError), so eight leaves room for a library that adds a wrapper; the node count and the seen set
#: bound a chain that is wide or that loops (``__context__`` can point back).
_REFUSAL_WALK_DEPTH = 8
_REFUSAL_WALK_NODES = 64


def _carries_airplane_refusal(exc: BaseException) -> bool:
    """True when the socket guard's own refusal is inside ``exc``, found by TYPE and never by words (R620, Steward 3's note).

    ``airplane.AirplaneModeError`` has one constructor, ``airplane._guard``, which raises only while the kill switch is engaged
    (with the airplane half armed, the host not local and no egress window open), from the socket calls a request makes before
    any byte reaches its destination: a name lookup, a connect, a CONNECT tunnel, and with R619 a request line that names its own
    destination. A host's answer reaches the fetcher as bytes that the libraries turn into their own classes, never into this one,
    so an instance found here means the switch refused this request, whatever text surrounds it and however requests and urllib3
    wrapped it: directly (NewConnectionError's ``__cause__``, R616), at a loopback proxy's CONNECT (ProtocolError's args, R620),
    or as a plain ``http://`` request line to a loopback proxy (urllib3's ProxyError inside MaxRetryError, R619).

    The walk follows ``__cause__``, the exceptions among ``args`` and urllib3's ``MaxRetryError.reason``; every real shape is reached
    through those (SOCKS too: urllib3.contrib.socks raises its NewConnectionError ``from`` the error). It does NOT follow
    ``__context__`` (the independent read's S1): Python sets that link on the first exception a request raises to whatever the CALLER's
    thread is handling at that moment, which comes from outside this request. A fetch made inside an ``except`` that holds a refusal
    somewhere in its chain (a fallback fetch after a Stopped one, a fetch in the handler of a bare guard refusal) would otherwise read
    its own host's failure, with the switch clear, as the switch's: never retried and reported offline. The walk is bounded by depth,
    by node count and by a seen set, and it never turns an exception into text. The class is read from
    ``sys.modules`` rather than imported here: if ``airplane`` was never imported, no instance can exist, and a first import from
    inside a failure's handler would capture whatever socket calls stood at that moment. A walk that fails answers False, so the
    failure is written as the request error it looks like (the pre-R620 reading), and the R320 switch read still applies.
    """
    try:
        airplane = sys.modules.get("src.ingest.airplane")
        if airplane is None:
            return False
        refusal = airplane.AirplaneModeError
        from urllib3.exceptions import MaxRetryError

        seen: set[int] = set()
        todo: list[tuple[object, int]] = [(exc, 0)]
        while todo and len(seen) < _REFUSAL_WALK_NODES:
            node, depth = todo.pop()
            if not isinstance(node, BaseException) or id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, refusal):
                return True
            if depth >= _REFUSAL_WALK_DEPTH:
                continue
            links: list[object] = [node.__cause__, *node.args]  # never __context__: it can be the caller's exception (see above)
            if isinstance(node, MaxRetryError):
                links.append(node.reason)
            todo.extend((link, depth + 1) for link in links)
    except Exception:  # noqa: BLE001 - this runs inside a failure's handler and must never replace that failure
        return False
    return False

# --------------------------------------------------------------------------- #
# C8 (2026-07-24 throughput brief): skip local DNS resolution when the exit
# resolves + a short-TTL cache for the path that still resolves locally (A6).
# --------------------------------------------------------------------------- #
#
# _guard_target() calls socket.getaddrinfo(host) on EVERY fetch + EVERY redirect
# hop -- even when proxied, where the resolved IP is never actually used to
# connect (the proxy/exit does that). Two distinct fixes:
#
# (1) When the configured proxy scheme is REMOTE-RESOLVING (socks5h/socks4a --
#     the trailing "h"/"a" is the curl/PySocks convention meaning "the PROXY
#     resolves", as opposed to plain socks5/socks4 where WE resolve locally and
#     hand the proxy an IP), the local getaddrinfo call is skipped entirely:
#     we never learn an IP to check, so there is nothing for _guard_target to
#     validate -- egress goes straight to the proxy with the hostname, saving
#     one DNS round-trip AND closing a DNS-metadata leak to the local/ISP
#     resolver (the exit performs the lookup instead). VERIFIED AT BUILD: the
#     app's own documented example (src/safety/settings.py) was
#     "socks5://127.0.0.1:9050" -- the LOCAL-resolving scheme -- so this
#     optimisation is INERT unless the operator (or our own default/guidance)
#     actually uses the "h" variant; the settings docstring/messages are
#     updated to recommend socks5h as the more private default. A plain
#     socks5/socks4 proxy is UNCHANGED (still resolved + guarded locally,
#     byte-identical) -- skipping the guard there would be a real SSRF hole,
#     since PySocks would still hand the proxy a LOCALLY-resolved IP with no
#     guard between resolution and connection.
# (2) For every path that STILL resolves locally (no proxy, or a non-remote-
#     resolving one), a short-TTL cache avoids re-resolving the SAME host on
#     every fetch/redirect hop within one pass. The TTL is intentionally SHORT
#     (default 60s) -- long enough to save real repeat-lookup latency across a
#     burst of fetches to one host, short enough that a DNS-rebinding attack
#     gains nothing durable (the guard re-validates well within any plausible
#     attack window). Per-instance (like every other host cache here), so it
#     resets every pass along with everything else -- never persisted, no new
#     staleness surface.
_DNS_CACHE_TTL_S = float(os.getenv("OO_DNS_CACHE_TTL", "60") or "60")
_DNS_CACHE_MAX = _env_cap("OO_DNS_CACHE_MAX", 2048, floor=64)
# The curl/PySocks "remote resolve" scheme suffix: socks5h / socks4a.
_REMOTE_RESOLVE_SOCKS_SCHEMES = frozenset({"socks5h", "socks4a"})


#: The proxy-mapping keys ``requests.utils.select_proxy`` can ever consult, minus
#: the ``<scheme>://<hostname>`` / ``all://<hostname>`` forms, which are matched by
#: their "://" instead. Used to narrow the endpoint set the connect-time SSRF guard
#: allowlists (see ``EthicalFetcher._request_proxy_endpoints``).
_SELECTABLE_PROXY_KEYS = frozenset({"http", "https", "all"})

#: The characters Python's ``urlsplit`` deletes wherever they stand (``urllib.parse._UNSAFE_URL_BYTES_TO_REMOVE``), mapped to a space, so a
#: redirect's Location can be read with them still visible (R622). ``urljoin`` drops them on a same-scheme hop before anything else sees them.
_URLSPLIT_DELETES_AS_SPACE = {ord("\t"): " ", ord("\r"): " ", ord("\n"): " "}


def _unsafe_url_text(text: str) -> bool:
    """A backslash, any whitespace or a control character: what may not stand in a URL's authority or in a host (R622)."""
    return any(ch == "\\" or ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in text)


def _is_remote_resolving_proxy(proxy_url: str | None) -> bool:
    """True when ``proxy_url``'s scheme resolves DNS AT THE PROXY/EXIT
    (``socks5h``/``socks4a``) rather than locally (``socks5``/``socks4``, any
    plain http(s) proxy, or no proxy at all). PURE string check, no I/O."""
    if not proxy_url or "://" not in proxy_url:
        return False
    scheme = proxy_url.split("://", 1)[0].lower()
    return scheme in _REMOTE_RESOLVE_SOCKS_SCHEMES

# --- Global network kill switch (a §0.5 invariant; maintainer: "Stop must be a
# kill switch"). Once set, EVERY new fetch attempt -- scheduler, manual ingest,
# crawler, markets, law, discovery -- refuses immediately. The single request
# already on the wire finishes (sockets aren't yanked mid-read), everything
# after it stops. Cleared when the operator starts collecting again.
_KILL = threading.Event()

#: THE ENGAGEMENT EPOCH (R327, ruled R614). The switch says whether it is engaged NOW; a reader that
#: decides after a request whether the failure was the target's (R320: read the switch after the work)
#: cannot tell from that alone that a Stop was pressed AND cleared again inside the request's flight, and
#: it then recorded the operator's Stop as the target's failure (robots "unreachable" cached for an hour,
#: a law document's check stamped for a day). So every :func:`activate_kill_switch` also counts itself:
#: a reader takes :func:`kill_switch_epoch` BEFORE its request and asks
#: :func:`kill_switch_engaged_since` after it, which is true when the switch is engaged now OR was engaged
#: at any moment in between. The set and the count happen together under ``_KILL_EPOCH_LOCK``, and a
#: clear takes the same lock, so a clear can never land between them (a reader would then see the switch
#: clear and the count unchanged); a capture before the pair sees the count change, a capture after it sees
#: the switch set at the fetcher's own check. Only ever increases, so a changed value cannot come back to the
#: one a reader captured. The window a reader asks about is everything between its capture and its question,
#: waits included (a host lock, a Crawl-delay, a retry back-off), not only the bytes on the wire.
_KILL_EPOCH = 0
# Re-entrant, so a future signal handler that engages the switch cannot deadlock a thread holding it.
_KILL_EPOCH_LOCK = threading.RLock()

#: Every ``requests.Session`` an :class:`EthicalFetcher` fetches through, and every ``GuardedSession`` (R638). Weak, so a fetcher that is gone takes its session with
#: it. :func:`activate_kill_switch` closes their pooled keep-alive connections: the socket guard refuses a request written to one after
#: the Stop (``airplane._guarded_putrequest``), and closing them leaves none idle to be written to at all. A closed ``Session`` stays
#: usable; its adapters open new pools on the next request, which then meets the connect guard.
_FETCHER_SESSIONS: weakref.WeakSet[requests.Session] = weakref.WeakSet()
# Re-entrant for the reason _KILL_EPOCH_LOCK is: activate_kill_switch takes it, and must not deadlock a thread already inside it.
_FETCHER_SESSIONS_LOCK = threading.RLock()


def _register_fetcher_session(session: requests.Session) -> None:
    with _FETCHER_SESSIONS_LOCK:
        _FETCHER_SESSIONS.add(session)


def _close_fetcher_pools() -> int:
    """Close the pooled connections of every registered fetcher session; how many sessions were closed. Never raises.

    A connection a request is using at this moment is not in its pool: urllib3 closes it when the request hands it back to the closed
    pool, and the request itself finishes or fails on its own (the single request already on the wire, as the Stop has always meant)."""
    with _FETCHER_SESSIONS_LOCK:
        sessions = list(_FETCHER_SESSIONS)
    closed = 0
    for session in sessions:
        try:
            session.close()
            closed += 1
        except Exception as exc:  # noqa: BLE001 - the Stop must complete whatever one session does
            # The class only, never the words or a traceback: an error from a pool can carry a URL with its login (R142).
            logging.getLogger(__name__).debug("kill switch: closing a fetcher session's pool failed (%s)", type(exc).__name__)
    return closed


#: The live socket of every mailbox pull in progress (IMAP or POP3, R647). Weak, so a pull that is gone takes its entry with it.
#: :func:`activate_kill_switch` shuts each one down, so a pull blocked on a stalled server ends at the Stop instead of at its timeout.
_LIVE_MAILBOX_SOCKETS: weakref.WeakSet[socket.socket] = weakref.WeakSet()
# Re-entrant for the reason _FETCHER_SESSIONS_LOCK is.
_LIVE_MAILBOX_SOCKETS_LOCK = threading.RLock()


def _shut_socket(sock: socket.socket) -> None:
    """Shut a live mailbox socket down at the TCP level. Never raises.

    The base ``socket.socket.shutdown``, not an ``SSLSocket``'s own: no TLS close record is written, and the TLS object a reading
    thread is inside is left alone. Both directions: a ``recv`` blocked in another thread returns at once, and nothing more can be
    written. The pull's own code then sees the closed connection and ends as the Stop it follows (R640)."""
    try:
        socket.socket.shutdown(sock, socket.SHUT_RDWR)
    except Exception as exc:  # noqa: BLE001 - a socket already closed or never connected has nothing to shut
        logging.getLogger(__name__).debug("kill switch: shutting a mailbox socket down failed (%s)", type(exc).__name__)


def register_mailbox_socket(sock: socket.socket) -> None:
    """Record a live mailbox socket for the Stop (R647). Called the moment the socket exists, before the greeting is read. If the switch is
    already engaged it is shut down at once: a Stop that landed between the connect and this call is not missed."""
    with _LIVE_MAILBOX_SOCKETS_LOCK:
        _LIVE_MAILBOX_SOCKETS.add(sock)
    if kill_switch_active():
        _shut_socket(sock)


def unregister_mailbox_socket(sock: object) -> None:
    """Take ``sock`` off the Stop's list. ``None`` (no socket yet, or one a library already let go of) is a no-op. Never raises."""
    if sock is None:
        return
    with _LIVE_MAILBOX_SOCKETS_LOCK, contextlib.suppress(TypeError):
        _LIVE_MAILBOX_SOCKETS.discard(sock)  # type: ignore[arg-type]


def _shut_mailbox_sockets() -> int:
    """Shut down every live mailbox socket; how many there were. Never raises."""
    with _LIVE_MAILBOX_SOCKETS_LOCK:
        socks = list(_LIVE_MAILBOX_SOCKETS)
    for sock in socks:
        _shut_socket(sock)
    return len(socks)


def activate_kill_switch() -> None:
    global _KILL_EPOCH
    with _KILL_EPOCH_LOCK:
        _KILL.set()
        _KILL_EPOCH += 1
    # Going offline is a HARD close: an egress window (the consented "install the
    # local AI without starting the collector" exemption) must never outlive the
    # operator's decision to go offline, or the airplane button would stop meaning
    # what it says. Imported lazily -- egress_window asks us for the kill-switch
    # state, so a module-level import here would be circular.
    try:
        from src.ingest.egress_window import close_window

        close_window()
    except Exception:  # noqa: BLE001 - the kill switch must engage no matter what
        pass
    # No keep-alive connection is left idle to be reused after the Stop (R638). After the switch is set, so a request that takes a
    # connection from a pool between the two meets the putrequest guard instead.
    _close_fetcher_pools()
    # A mailbox pull blocked on a stalled server ends now rather than at its timeout (R647); after the switch is set, so a pull that
    # registers its socket between the two shuts it itself.
    _shut_mailbox_sockets()


def clear_kill_switch() -> None:
    """Turn the switch off. A MECHANISM, and deliberately nothing more.

    It does NOT record that an operator went online -- see
    :func:`note_operator_crossed_online`. The first cut of the boot-race fix set
    the decision flag here, on the theory that clearing the switch and going online
    are the same event. They are not: this primitive is also how a caller reaches a
    known state (every test fixture in the tree does exactly that), and folding the
    decision in meant any such caller silently suppressed the boot airplane engage.
    That is the wrong direction to be wrong in -- it weakens zero-network boot, the
    non-negotiable the flag was written to leave untouched.
    """
    with _KILL_EPOCH_LOCK:  # never between an engagement's set and its count (R614)
        _KILL.clear()


def kill_switch_active() -> bool:
    return _KILL.is_set()


def kill_switch_epoch() -> int:
    """How many times the switch has been engaged in this process: capture it before a request (R614)."""
    return _KILL_EPOCH


def kill_switch_engaged_since(epoch: int) -> bool:
    """True when the switch is engaged now, or was engaged at any moment after ``epoch`` was captured.

    The question a recorder asks after a request whose failure it may store as the target's: a request
    that shared its flight with a Stop, even one cleared again before the failure reached the caller, is
    not an answer about the target, and the recorder stores nothing for it (R614 (2)). The cost is
    conservative: a real failure that happens to share its window with a Stop (waits included) is asked
    again next time.
    """
    return kill_switch_active() or epoch != _KILL_EPOCH


#: Has an OPERATOR crossed ONLINE in this process? Set by
#: :func:`note_operator_crossed_online` and never cleared, so it records "a
#: decision was taken", not the current state -- it must survive a later
#: deliberate go-offline, because a flag mirroring the state would re-arm the
#: clobber below the moment the operator toggled airplane back on.
#:
#: THE RACE IT CLOSES (field report 2026-08-02: "sometimes the app remains in
#: airplane mode with no explanation" on a NEW instance). Airplane-at-boot is
#: engaged TWICE on the unlock path: synchronously in ``unlock.py`` (so there is no
#: window where the corpus is open and the socket guard is not), and again at the
#: tail of ``_run_startup_upkeep`` -- which on that path runs in a BACKGROUND
#: THREAD. A new instance's upkeep is slow (catalog seed, ANALYZE, counts, cache
#: warm), so the wizard is on screen throughout it. Cross online during that
#: window and the upkeep thread's ``activate_kill_switch()`` lands AFTER the
#: operator's ``clear_kill_switch()`` and silently puts the app back in airplane
#: mode -- the POST had already returned ``online: true``, so nothing reported it,
#: and the 5 s poll simply repainted the button. Intermittent by construction: it
#: depends purely on whether the click beat the thread.
#:
#: The zero-network-boot non-negotiable is untouched. A boot still engages airplane
#: unconditionally; it just may not RE-engage it over an explicit later decision,
#: which was never "booting offline" in the first place.
_CROSSED_ONLINE = threading.Event()


def note_operator_crossed_online() -> None:
    """Record that an OPERATOR deliberately took this process online.

    Called from the three surfaces where that is what actually happened -- the
    go-online endpoint, scheduler start, and run-now -- each of which is already
    behind the ONE network-consent popup. Kept separate from
    :func:`clear_kill_switch` so that reaching a known state, which is a different
    act, can never be mistaken for a decision.
    """
    _CROSSED_ONLINE.set()


def crossed_online_since_boot() -> bool:
    """True once an operator has explicitly taken this process online.

    Callers that engage airplane as part of BOOT consult this so a slow background
    upkeep can never revoke a decision the operator already made."""
    return _CROSSED_ONLINE.is_set()


def _reset_crossed_online_for_tests() -> None:
    _CROSSED_ONLINE.clear()


#: The blocked-address predicate lives in ``src.ingest.ssrf_guard`` so the
#: resolve-time check below and the connect-time check there read ONE definition
#: -- two copies would be two answers to one question, and the whole point of
#: NET-01 is that those two moments must agree. Re-exported under its historical
#: private name for the call sites and tests that already use it.
_is_blocked_ip = is_blocked_ip

#: The fixed words a robots refusal of a redirect hop ends with (R629): the address refused is the hop's, reached from the page asked for.
_REDIRECT_HOP_NOTE = "reached by a redirect"


class _RedirectChain:
    """One page fetch's walk along its redirect chain (R629): the ONE per-host lock it holds, and the scope its caller kept it to.

    A hop to another host takes that host's robots.txt and politeness interval under that host's lock, as a first request does.
    The lock is HANDED OVER, never added: the host the chain leaves is stamped (its request was answered) and its lock released
    BEFORE the next host's lock is waited for, so a thread holds at most one host lock at any moment. Two chains crossing each
    other (A -> B on one thread while B -> A runs on another) can then never each hold the lock the other waits for, which is the
    deadlock a second lock taken on top of the first would make. What the hand-over gives up is nothing a lock protected: the host
    left behind has had its request answered and its response closed.
    """

    __slots__ = ("_fetcher", "_lock", "first", "netloc", "requested", "scope")

    def __init__(self, fetcher: EthicalFetcher, netloc: str, scope: Callable[[str], bool] | None) -> None:
        self._fetcher = fetcher
        #: entered and exited as the ``with`` it replaces did, so whatever ``_host_lock`` hands back keeps working
        self._lock: AbstractContextManager[Any] | None = None
        self.first = netloc  #: the host key of the URL asked for: a retry starts again from it
        self.netloc = netloc  #: the host key whose lock is held
        self.requested = False  #: a request went to the held host since it was taken: its interval counts from the stamp
        self.scope = scope
        self._take(netloc)

    def _take(self, netloc: str) -> None:
        lock = self._fetcher._host_lock(netloc)
        lock.__enter__()
        self._lock, self.netloc, self.requested = lock, netloc, False

    def stamp(self) -> None:
        """Write the held host's last-request time, once, if a request went to it."""
        if self.requested:
            with self._fetcher._host_state_guard:
                self._fetcher._last_request[self.netloc] = self._fetcher._now()
            self.requested = False

    def move(self, netloc: str) -> None:
        """Stamp and release the held host, then wait for ``netloc``'s lock holding none (nothing to do on the held host)."""
        if netloc == self.netloc and self._lock is not None:
            return
        self.stamp()
        self.release()
        self._take(netloc)

    def release(self) -> None:
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.__exit__(None, None, None)


class EthicalFetcher:
    """Stateful fetcher enforcing robots.txt (fail-closed) + per-host rate limits.

    A ``session`` may be injected for testing (any object with a ``.get(url,
    timeout=...)`` returning a requests-like Response).
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_s: float = 1.0,
        timeout: float = 30.0,
        max_bytes: int = 10 * 1024 * 1024,
        respect_robots: bool = True,
        proxy: str | None = None,
        proxy_pool: list[str] | None = None,
        session: requests.Session | None = None,
        max_retries: int = 2,
        retry_backoff_s: float = 0.5,
        robots_cache_path: Path | None = None,
        body_deadline_s: float | None = None,
    ):
        self.user_agent = user_agent
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self.max_bytes = max_bytes
        # A wall-clock bound on reading ONE body (2026-09-10, the candidate kit's first live
        # run): the socket timeout bounds each recv, not the whole read, so a server that
        # trickles a body a few bytes per timeout -- a tarpit -- holds a worker for as long as
        # it likes. Generous by default (ten timeouts, never under two minutes) so a slow but
        # honest Tor transfer of a large page still completes; only a trickle is refused, loudly.
        self.body_deadline_s = (
            float(body_deadline_s) if body_deadline_s is not None else max(10.0 * float(timeout), 120.0)
        )
        self.respect_robots = respect_robots
        # Bounded retry/backoff for transient fetch failures (finding BUG-02).
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_s = max(0.0, float(retry_backoff_s))
        self.proxy = proxy or None
        # C10 (2026-07-24 throughput brief, §6b): an operator-run SOCKS pool.
        # TAKES PRECEDENCE over ``proxy`` when non-empty (see _isolated_proxies,
        # which does the actual per-host sharding). Re-validated here (not just
        # at the settings-save layer) -- ALL-TOR OR REFUSED: fails loud on
        # construction rather than silently using a pool with a non-SOCKS
        # member, in case the caller bypassed save_settings's own check (e.g. an
        # older/hand-edited persisted file, or a direct construction in tests).
        self._proxy_pool: list[str] | None = None
        if proxy_pool:
            from src.safety.fetcher import validate_socks_pool

            validate_socks_pool(list(proxy_pool))
            self._proxy_pool = list(proxy_pool)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        if isinstance(self.session, requests.Session):
            _register_fetcher_session(self.session)  # its pool is closed on a Stop (R638)
        # Size the connection pool for parallel collection: with up to ~50
        # concurrent DISTINCT hosts (per-host concurrency stays 1 via the host
        # lock), the default urllib3 pool (10) would churn host-pools and warn.
        # A generous adapter keeps warm keep-alive connections reused across a
        # pass. Real session only (an injected test stub manages its own I/O).
        if isinstance(self.session, requests.Session):
            try:
                from requests.adapters import HTTPAdapter

                from src.config.power_profiles import http_pool_size

                # C9 (2026-07-24 throughput brief): hardware-aware, via the
                # OO_HTTP_POOL override or the active power profile (Optimized=64,
                # byte-identical to the literal this replaces).
                pool_n = max(1, http_pool_size())
                adapter = HTTPAdapter(pool_connections=pool_n, pool_maxsize=pool_n)
                self.session.mount("http://", adapter)
                self.session.mount("https://", adapter)
            except Exception:  # noqa: BLE001 - pool sizing is an optimisation, never required
                pass
        # Protected fetch (Theme 2): route through the user's proxy (e.g. Tor at
        # socks5://127.0.0.1:9050). We *use* the proxy and verify it is set; we do NOT
        # guarantee anonymity — the user must run and trust the proxy. SOCKS proxies
        # additionally need PySocks (pip install pysocks) — there is no packaged extra
        # for it; HTTP/HTTPS proxies work out of the box.
        # A POOL's actual per-host endpoint is chosen at FETCH TIME (_isolated_proxies,
        # every real request path routes through it) -- this session-level default is
        # only ever a defensive fallback (the first member) for anything that might
        # read .session.proxies directly without going through that method.
        if self._proxy_pool:
            first = self._proxy_pool[0]
            self.session.proxies = {"http": first, "https": first}
        elif self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}
        # Per-HOST Tor stream isolation (on by default; OO_TOR_STREAM_ISOLATION=0
        # disables). Over a SOCKS proxy, each host's requests ride their OWN Tor
        # circuit (IsolateSOCKSAuth), so no exit node or circuit observer can link
        # the user's activity across different sources — Tor Browser's "isolate by
        # first-party domain" model. A no-op for non-SOCKS/no proxy. We still never
        # claim anonymity; this only compartmentalises what the proxy already gives.
        self._stream_isolation = os.environ.get("OO_TOR_STREAM_ISOLATION", "1") != "0"
        self._max_redirects = _MAX_REDIRECTS
        # host -> (decision_parser_or_None, expiry). None == "do not fetch this host".
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}
        #: host_key -> why robots could not be determined, for the same TTL as the
        #: decision above. Only ever holds a host whose decision is None.
        self._robots_cause: dict[str, str] = {}
        #: host_key -> consecutive robots FAILURES, which set that host's next TTL
        #: (_robots_ttl_for). Cleared by a single success; persisted, so a restart does
        #: not hand a host that refused fifty times a fresh one-hour clock.
        self._robots_fails: dict[str, int] = {}
        self._last_request: dict[str, float] = {}
        #: netloc -> WALL-CLOCK next-allowed-at, for hosts that declare a
        #: ``Crawl-delay`` (S04-13 S2, Q1013 = a). Loaded from the sidecar in
        #: __init__ below, so a fresh per-pass fetcher inherits what the previous
        #: pass promised instead of re-asking a long-delay host immediately.
        self._host_schedule: dict[str, tuple[float, float]] = {}
        # C8: short-TTL DNS cache for the path that still resolves locally (a
        # remote-resolving SOCKS proxy skips this entirely -- see
        # _is_remote_resolving_proxy). host -> (getaddrinfo results, expiry).
        self._dns_cache: dict[str, tuple[list, float]] = {}
        # Per-host locks: one source/host is fetched by at most ONE thread at a
        # time, so parallel collection (a bounded worker pool) is polite by
        # construction — concurrency is ACROSS hosts, never within one host's
        # rate-limit. The shared mutable state (_robots, _last_request) for a host
        # is only touched under its lock. Different hosts run in parallel.
        self._host_locks: dict[str, threading.Lock] = {}
        self._host_locks_guard = threading.Lock()
        # Serialises WRITES to ``_last_request`` against the eviction sweep
        # (skeptic finding 2026-07-09: an unsynchronised sweep could pop a
        # FRESH stamp written between its snapshot and its pop, letting the
        # next fetch of that host skip the politeness delay). Reads stay
        # lock-free (a stale read only ever sleeps MORE, never less).
        self._host_state_guard = threading.Lock()
        # sleep is indirected so tests can run without real delays.
        self._sleep = time.sleep
        self._now = time.monotonic

        # A5 (2026-07-24 throughput brief, C4): reuse in-TTL robots.txt verdicts
        # from a prior pass/process instead of starting cold every time
        # make_fetcher() builds a fresh instance (see the module-level note by
        # _ROBOTS_TTL). Injectable so tests never touch the real data_dir().
        self._robots_cache_path = robots_cache_path or _robots_cache_path()
        # An older build's keys leave the file whether or not this run persists (R621, Steward 3's item 4): a credential left
        # on disk is not this run's to keep. Nothing new is written when persistence is off.
        _scrub_sidecar(self._robots_cache_path, _ROBOTS_PERSIST_LOCK, _robots_key_is_normal, _drop_unkeyed_robots)
        if _robots_persist_enabled():
            try:
                self._robots.update(
                    _load_persisted_robots(self._robots_cache_path, now_monotonic=self._now)
                )
                self._robots_cause.update(_persisted_robots_causes(self._robots_cache_path))
                self._robots_fails.update(_persisted_robots_fails(self._robots_cache_path))
            except Exception:  # noqa: BLE001 - a bad cache load must never break construction
                pass

        # S04-13 S2 (Q1013 = a): the per-host next-allowed-at, "beside the robots
        # cache" both in the ruling's words and on disk. Derived from the same
        # injectable path so a test that redirects the robots sidecar redirects this
        # one too -- two independently-injected paths is how a fixture ends up
        # writing half its state into the real data_dir().
        self._host_schedule_path = self._robots_cache_path.with_name("host_schedule.json")
        _scrub_sidecar(self._host_schedule_path, _HOST_SCHEDULE_LOCK, _schedule_key_is_normal, _merge_unkeyed_stamps)  # as above
        if _host_schedule_persist_enabled():
            try:
                self._host_schedule.update(_load_host_schedule(self._host_schedule_path))
            except Exception:  # noqa: BLE001 - a bad load must never break construction
                pass

    def _host_lock(self, netloc: str) -> threading.Lock:
        """Return (creating if needed) the lock that serialises fetches to ``netloc``.

        The lock map is deliberately UNBOUNDED: evicting a lock object another
        thread may already hold a reference to would let two threads fetch the
        same host concurrently (politeness is never traded for memory — a
        threading.Lock is ~100 bytes, and the fetcher is per-pass so the map
        dies with the pass; pass recycling bounds the pass).
        """
        with self._host_locks_guard:
            lock = self._host_locks.get(netloc)
            if lock is None:
                lock = threading.Lock()
                self._host_locks[netloc] = lock
            return lock

    def cache_stats(self) -> dict:
        """Sizes of the per-pass host caches (memory instrumentation, P0.3 E1).

        Read by the collection-perf monitor each tick so a marathon pass's
        accumulation is measured, not guessed. Plain lengths — cheap, no locks
        beyond the GIL (an off-by-one under concurrent mutation is fine for a
        gauge).
        """
        return {
            "robots": len(self._robots),
            "last_request": len(self._last_request),
            "host_locks": len(self._host_locks),
            "dns": len(self._dns_cache),
        }

    def declared_sitemaps(self, url: str) -> list[str]:
        """Sitemap URLs the host's own robots.txt DECLARES (``Sitemap:`` directives,
        parsed by the stdlib ``RobotFileParser`` -- the same cached decision
        ``_enforce_robots`` uses, so this costs a real robots fetch only on a cache
        miss). C7 (2026-07-24 throughput brief): the preferred discovery source,
        since it is the site's OWN authoritative pointer -- a conventional
        ``/sitemap.xml`` guess is only the fallback (see ``src.ingest.sitemap``).

        Same guards as :meth:`fetch` (this can trigger a REAL robots.txt fetch on a
        cache miss, so it must never bypass them): the kill switch is honoured
        (airplane mode refuses -- raises ``FetchFailed``, exactly like ``fetch``),
        the SSRF guard runs on the target host, and the per-host lock serialises
        against a concurrent fetch to the same host.

        Returns ``[]`` (never a guess) when robots.txt disallows/is unavailable for
        this host, or when it declares no sitemaps at all.
        """
        if _KILL.is_set():
            raise FetchFailed(KILL_SWITCH_REFUSAL)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return []
        self._refuse_parser_mismatch(url)  # before the guard looks the host up (R622)
        self._guard_target(parsed.hostname)  # SSRF: never reach internal addresses
        parsed = parsed._replace(netloc=_host_netloc(parsed.netloc, parsed.scheme))  # the host key, never the userinfo or a spelling (R621)
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        with self._host_lock(parsed.netloc):
            parser = self._get_robots(host_key, parsed)
        if parser is None:
            return []
        try:
            return list(parser.site_maps() or [])
        except Exception:  # noqa: BLE001 - a parser quirk must never break discovery
            return []

    def _declares_crawl_delay(self, key_or_netloc: str) -> bool:
        """True when the cached robots decision for this host declares a
        Crawl-delay (checked under both scheme keys for a bare netloc)."""
        keys = (
            (key_or_netloc,)
            if "://" in key_or_netloc
            else (f"https://{key_or_netloc}", f"http://{key_or_netloc}")
        )
        for k in keys:
            cached = self._robots.get(k)
            if cached is not None and cached[0] is not None:
                try:
                    if cached[0].crawl_delay(self.user_agent):
                        return True
                except Exception:  # noqa: BLE001 - unknowable delay: keep the entry
                    return True
        return False

    def crawl_delay_for(self, url_or_netloc: str) -> float | None:
        """The ``Crawl-delay`` (seconds) the host's CACHED robots.txt declares for this
        fetcher's user agent, or ``None`` when none is declared or the host's robots
        decision is not cached. Never fetches: a read-only view of what the last
        ``fetch`` learned, for a caller that plans its NEXT requests to the host and
        wants to know what each one will cost in waiting (the candidate pipeline's
        probe budget: at Crawl-delay 900 six probes are ninety minutes of one worker).
        A bare netloc is checked under both scheme keys, like ``_declares_crawl_delay``.
        """
        parsed = urlparse(url_or_netloc) if "://" in url_or_netloc else None
        netloc = parsed.netloc if parsed is not None else url_or_netloc
        # the cache is keyed by the host key, per scheme (R621): no userinfo, one spelling, no default port
        keys: tuple[str, ...] = (f"{parsed.scheme}://{_host_netloc(netloc, parsed.scheme)}",) if parsed is not None else ()
        keys += (f"https://{_host_netloc(netloc, 'https')}", f"http://{_host_netloc(netloc, 'http')}")
        for k in keys:
            cached = self._robots.get(k)
            if cached is None or cached[0] is None:
                continue
            try:
                delay = cached[0].crawl_delay(self.user_agent)
            except Exception:  # noqa: BLE001 - an unreadable delay is nothing a caller can plan on
                return None
            if delay:
                return float(delay)
        return None

    def _bound_host_caches(self) -> None:
        """Keep the per-pass host caches bounded on a very wide/long pass.

        Best-effort and defensive (a bookkeeping error must never break a
        fetch), and POLITENESS OUTRANKS THE BOUND (skeptic-hardened 2026-07-09):

        * A robots entry whose parser declares a ``Crawl-delay`` is NEVER
          evicted — an in-flight fetch between its robots check and its
          rate-limit read must always still see the declared delay. Evicting a
          delay-LESS entry is semantically neutral for pacing (the rate limit
          falls back to ``min_interval_s``, exactly what that entry yields)
          and only costs a fail-closed robots recompute on the next contact.
        * ``_last_request`` stamps are mutated ONLY under ``_host_state_guard``
          (shared with the writer in the fetch path), so eviction can never
          race a fresh stamp out of the map (the TOCTOU a skeptic reproduced);
          an entry is evicted only when older than ``_LAST_REQUEST_SAFE_AGE_S``
          AND its host declares no Crawl-delay, so a forgotten timestamp can
          never permit an impolitely early re-fetch. All-young over-cap maps
          simply stay over cap (a dict of floats — the honest trade).
        """
        try:
            if len(self._robots) > _ROBOTS_CACHE_MAX:
                items = sorted(self._robots.items(), key=lambda kv: kv[1][1])
                excess = len(items) - _ROBOTS_CACHE_MAX
                for key, (decision, _expiry) in items:
                    if excess <= 0:
                        break
                    if decision is not None:
                        try:
                            if decision.crawl_delay(self.user_agent):
                                continue  # politeness-critical: never evicted
                        except Exception:  # noqa: BLE001 - unknowable: keep it
                            continue
                    self._robots.pop(key, None)
                    excess -= 1
            if len(self._last_request) > _LAST_REQUEST_MAX:
                with self._host_state_guard:
                    now = self._now()
                    items2 = sorted(self._last_request.items(), key=lambda kv: kv[1])
                    excess = len(items2) - _LAST_REQUEST_MAX
                    for key, last in items2:
                        if excess <= 0 or (now - last) < _LAST_REQUEST_SAFE_AGE_S:
                            break  # sorted ascending: the rest are younger still
                        if self._declares_crawl_delay(key):
                            continue  # a long declared delay outlives the safe age
                        self._last_request.pop(key, None)
                        excess -= 1
        except Exception:  # noqa: BLE001 - a cache bound must never break a fetch
            pass

    @property
    def _real_session(self) -> bool:
        """Network-level guards (DNS-resolution SSRF check, streamed size cap) apply only
        to the real requests session; an injected stub/double controls its own returns, so
        only the cheap literal-IP block runs for it. Computed at call time because tests may
        swap ``.session`` after construction."""
        return isinstance(self.session, requests.Session)

    # -- public API -------------------------------------------------------- #

    def fetch(
        self,
        url: str,
        *,
        require_html: bool = True,
        extra_headers: dict[str, str] | None = None,
        keep_bytes: bool = False,
        redirect_scope: Callable[[str], bool] | None = None,
    ) -> FetchResult:
        """Fetch ``url`` ethically. Raises a ``FetchError`` subclass on any refusal.

        ``require_html`` rejects non-HTML responses (used for article pages). Set it
        False to fetch feeds (RSS/Atom XML) through the same robots/rate-limit path.

        A redirect hop to ANOTHER host (another host key: a host or a port, never only the
        scheme) is a first request to that host (R629): its robots.txt is read and its interval
        waited, fail-closed, under its own lock, before it is requested. ``redirect_scope``, when
        given, is asked about every hop's URL first, and a hop it answers False for (or cannot
        answer) is refused with :class:`RedirectOutOfScope` before anything is asked of its host:
        a crawl kept to one site hands its site here.

        ``extra_headers`` adds request headers (e.g. conditional-GET
        ``If-None-Match`` / ``If-Modified-Since`` for feeds). When the server
        answers ``304 Not Modified`` the returned ``FetchResult`` has
        ``status_code == 304`` and empty content — a valid, non-error result, so
        the caller can skip re-parsing an unchanged feed.

        ``keep_bytes`` additionally attaches the UNDECODED response bytes on
        ``FetchResult.raw_content`` (default off ⇒ byte-identical + no extra
        memory for every existing caller). Needed for a binary body (e.g. a PDF
        law) whose bytes the text-decode path would otherwise destroy.
        """
        if _KILL.is_set():
            raise FetchFailed(KILL_SWITCH_REFUSAL)
        try:
            parsed: ParseResult | None = urlparse(url)
        except ValueError:
            # A link urlsplit cannot read (an unclosed IPv6 bracket ``http://[::1``, a bracketed host that is no address, a netloc
            # NFKC would change) raised a bare ValueError out of the fetch, which ended the source's whole feed pass: a feed
            # item's link reaches here through ``ingest_url`` (R626's read). Refused below, outside this handler, as the
            # unsupported or malformed URL it is.
            parsed = None
        if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise FetchFailed(f"unsupported or malformed URL: {failure_url(url)!r}")

        # Cheap length check per fetch; evicts only when a cap is exceeded (E1).
        self._bound_host_caches()

        self._refuse_parser_mismatch(url)  # before the guard looks the host up (R622)
        self._guard_target(parsed.hostname)  # SSRF: never reach internal addresses

        # Every per-host record below (robots, schedule, interval, lock, circuit) is keyed by the host key, never the userinfo
        # or the host's spelling (R621, see _host_netloc); the request itself is made with ``url`` as given. Taken AFTER
        # _refuse_parser_mismatch (R622), which reads the URL as written.
        parsed = parsed._replace(netloc=_host_netloc(parsed.netloc, parsed.scheme))
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        # Per-host Tor circuit (computed once, from the ORIGINAL host) so the
        # robots check and every page/redirect hop for this host share it.
        iso_proxies = self._isolated_proxies(parsed.netloc)

        # Serialise everything for this host under its per-host lock: robots +
        # rate-limit + the (possibly retried) GET + body read. So a host is hit by
        # AT MOST ONE request at a time (politeness is never traded for speed, even
        # under parallel collection), while DIFFERENT hosts proceed in parallel —
        # each on its own Tor circuit. A redirect hop to another host hands the lock
        # over to that host's (R629, see _RedirectChain): never two held at once. The
        # lock held at the end releases on return/raise.
        chain = _RedirectChain(self, parsed.netloc, redirect_scope)
        try:
            return self._fetch_locked(
                url,
                host_key=host_key,
                parsed=parsed,
                require_html=require_html,
                extra_headers=extra_headers,
                iso_proxies=iso_proxies,
                keep_bytes=keep_bytes,
                chain=chain,
            )
        finally:
            chain.release()

    def _fetch_locked(
        self, url, *, host_key, parsed, require_html, extra_headers, iso_proxies,
        keep_bytes=False, chain: _RedirectChain,
    ) -> FetchResult:
        """The per-host-serialised fetch body (``chain`` holds the host lock: the first host's, then the hop's)."""
        # robots.txt is checked once (not per retry): a disallow/unavailable is a
        # deliberate, non-transient refusal.
        if self.respect_robots:
            self._enforce_robots(url, host_key, parsed)

        # Bounded retry with exponential backoff for *transient* failures only
        # (network errors, 429, and 5xx) -- finding BUG-02. Deterministic refusals
        # (4xx, non-HTML, robots/SSRF) are never retried. Per-host rate limiting is
        # honoured before every attempt so retries stay polite.
        fetch_token = activity_monitor.fetch_started(url)
        try:
            attempt = 0
            transient: Exception | None = None
            response = final_url = None
            while True:
                try:
                    self._respect_rate_limit(parsed.netloc, host_key)
                except CrawlDelayDeferred:
                    # The first attempt deferred: no request was made, a true deferral. A RETRY that defers
                    # follows a request that WAS made and failed (a 5xx, a 429, a timeout) on a host whose
                    # Crawl-delay exceeds the inline wait: the failure in hand is the honest answer, not a
                    # deferral (a caller counting it as one gave the failed request no back-off). The host's
                    # next-allowed-at was persisted before the raise, so the next pass still waits.
                    if attempt == 0:
                        raise
                    if transient is not None:
                        raise transient from None
                    break  # a retryable status: handled below, as when the retries run out
                chain.requested = True
                prior = (transient, response, final_url)  # this attempt's predecessor, for a hop that defers on a retry
                transient = None
                response = final_url = None
                try:
                    response, final_url = self._http_get(
                        url, extra_headers=extra_headers, proxies=iso_proxies, chain=chain
                    )
                except CrawlDelayDeferred:
                    # A redirect hop's own host deferred (R629), before its request: on the first attempt that is the answer, as
                    # above; on a retry the failed request before it is (the same rule as for the first host, above).
                    if attempt == 0:
                        raise
                    transient, response, final_url = prior
                    if transient is not None:
                        raise transient from None
                    break  # a retryable status: handled below, as when the retries run out
                except requests.RequestException as exc:
                    if _carries_airplane_refusal(exc):
                        # The guard's own refusal, found by TYPE (R620): the switch's, whatever words came with it. Raised at once
                        # in the switch's whole sentence: never retried (it is the person's setting, not a host's passing failure,
                        # and the next pass asks again) and carrying no host's text. Every reader reads that sentence as the switch's.
                        raise FetchFailed(KILL_SWITCH_REFUSAL) from None
                    # the URL through failure_url: a link holding spaces must not continue in the guard's words (R616). Its userinfo,
                    # masked there, is taken out of the error's words as well (Steward 3 #1): requests quotes a URL it cannot prepare
                    # ("Failed to parse: https://u:pw@..."). The secrets are the named URL's; a redirect hop's own userinfo is not among
                    # them, stated: a hop with no http(s) scheme, no host or an authority urllib3 cannot parse (the URLs requests quotes)
                    # is refused before it is requested, by the hop check, _guard_target and _refuse_parser_mismatch.
                    transient = FetchFailed(
                        f"request error for {failure_url(url)}: {record_text(exc, *userinfo_secrets(url), typed=False)}"
                    )
                finally:
                    # the host last requested: the first, or the host of the hop the chain ended on (the hosts it left were
                    # stamped as it left them, R629)
                    chain.stamp()

                # transient is None <=> _http_get returned, i.e. `response` is set.
                # Spelled out because that pairing lives in the try/except above.
                if (
                    transient is None
                    and response is not None
                    and response.status_code not in _RETRYABLE_STATUS
                ):
                    break  # got a definitive (success or non-retryable) response

                if attempt >= self.max_retries:
                    if transient is not None:
                        raise transient
                    break  # out of retries: fall through to handle the status below

                attempt += 1
                # A retry starts again from the first host, under its lock (R629), and moves there BEFORE its back-off, so the sleep
                # holds only that lock, as before R629: a hop host the attempt ended on is stamped and released first and its other
                # fetches are not held up by this one's sleep (the independent read's nit). The one move: no path reaches the next
                # attempt without passing here.
                chain.move(chain.first)
                self._sleep(self.retry_backoff_s * (2 ** (attempt - 1)))

            # the loop exits with either a definitive response or a raised error
            assert response is not None and final_url is not None

            # Source IP capture (Slice 6a): read the connected server IP while the
            # connection is still live (stream=True keeps it open until the body is
            # read). Clearnet only -- over Tor/proxy this is honestly unavailable.
            server_ip, server_ip_reason = self._capture_server_ip(
                response, proxied=bool(self.proxy or iso_proxies)
            )

            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")

            # 304 Not Modified: a VALID conditional-GET answer, not a failure.
            # The resource is unchanged; return an empty-bodied result carrying
            # the (echoed) validators so the caller can refresh its bookkeeping.
            if response.status_code == 304:
                if hasattr(response, "close"):
                    response.close()
                return FetchResult(
                    requested_url=url,
                    final_url=final_url,
                    status_code=304,
                    content="",
                    content_type=response.headers.get("Content-Type", ""),
                    fetched_at=datetime.now(UTC),
                    etag=etag,
                    last_modified=last_modified,
                    server_ip=server_ip,
                    server_ip_reason=server_ip_reason,
                )

            if response.status_code != 200:
                raise FetchFailed(f"HTTP {response.status_code} for {failure_url(url)}")

            content_type = response.headers.get("Content-Type", "")
            if require_html and "html" not in content_type.lower():
                raise FetchFailed(f"non-HTML content ({content_type!r}) for {failure_url(url)}")

            content, raw_body = self._read_body(
                response, url, token=fetch_token, keep_bytes=keep_bytes
            )

            return FetchResult(
                requested_url=url,
                final_url=final_url,
                status_code=response.status_code,
                content=content,
                content_type=content_type,
                fetched_at=datetime.now(UTC),
                etag=etag,
                last_modified=last_modified,
                server_ip=server_ip,
                server_ip_reason=server_ip_reason,
                raw_content=raw_body,
            )
        finally:
            activity_monitor.fetch_finished(fetch_token)

    def _capture_server_ip(
        self, response, *, proxied: bool
    ) -> tuple[str | None, str | None]:
        """The server IP we connected to (Slice 6a) + an honest reason when unavailable.

        Returns ``(ip, None)`` on a direct clearnet connection, else ``(None, reason)``.
        NEVER a guess: over a SOCKS proxy / Tor the socket connects to the PROXY, not the
        server, so the real server IP is genuinely unavailable. The captured IP is OUR
        VANTAGE POINT (usually a CDN edge / anycast), not proof of the publisher's origin.
        """
        if proxied:
            return None, "unavailable (proxy/Tor)"
        if not self._real_session:
            return None, None  # injected/test session: no real socket to read
        # Read the connected peer from the live urllib3 socket. Internals differ across
        # urllib3 versions, so try the known paths and degrade loudly (never fabricate).
        sock = None
        try:
            sock = response.raw._connection.sock  # urllib3 HTTPConnection
        except Exception:  # noqa: BLE001
            try:
                sock = response.raw._fp.fp.raw._sock  # http.client fallback
            except Exception:  # noqa: BLE001
                sock = None
        if sock is None:
            return None, "unavailable (socket not readable)"
        try:
            ip = sock.getpeername()[0]
            ipaddress.ip_address(ip)  # validate; raises on garbage
            return str(ip), None
        except Exception:  # noqa: BLE001
            return None, "unavailable (socket not readable)"

    # -- SSRF guard + bounded redirects + size-capped body ----------------- #

    def _guard_target(self, host: str | None) -> None:
        """Refuse to fetch internal/non-public targets (SSRF, CWE-918).

        Honours the kill switch FIRST. ``fetch()`` and ``sitemaps_for()`` check it
        before calling here, so for them this is redundant -- but this method is
        also a SIDE DOOR: ``src/monitoring/preflight.py`` and
        ``feed_preflight.py`` call it (and ``_guarded_redirect_get``) directly
        instead of going through ``fetch()``, and so never met that check. The
        resolution below is itself egress -- it hands the operator's resolver the
        list of sources they read -- so a path that skipped the check leaked DNS
        for every enabled source. Checking here means the gate belongs to the
        method that touches the network rather than to the callers who must
        remember to ask.

        Applies only to the real requests session — an injected stub/double performs no
        real network I/O, so there is nothing to guard (and tests may legitimately use
        loopback stand-in hosts). For a real fetch, literal IPs are checked and hostnames
        are resolved + checked (rejecting a name that resolves to a private/loopback/
        link-local address — defeating DNS-rebinding-to-internal).

        C8: when the configured proxy is REMOTE-RESOLVING (socks5h/socks4a), the
        hostname branch is skipped entirely — we never learn an IP to validate,
        egress goes straight to the proxy, and the exit resolves it (see the
        module-level note by ``_is_remote_resolving_proxy``). A literal IP is
        STILL checked either way (cheap, no resolution needed). Every other
        configuration (no proxy, a plain http(s) proxy, or a LOCAL-resolving
        socks5/socks4 proxy) keeps the FULL guard, byte-identical to before —
        this is the one branch that changes behaviour, and only under a
        verified remote-resolving scheme.
        """
        if not self._real_session:
            return
        if _KILL.is_set():
            raise FetchFailed(KILL_SWITCH_REFUSAL)
        if not host:
            raise FetchFailed("missing host")
        if _unsafe_url_text(host):
            # Never looked up, and never written: a name with spaces could otherwise be the opening words of a sentence (R622).
            raise BlockedTarget("URL host contains a backslash, whitespace or control character")
        host = host.strip("[]")  # IPv6 literal brackets
        try:
            if _is_blocked_ip(ipaddress.ip_address(host)):
                raise BlockedTarget(f"refusing to fetch a non-public address: {host}")
            return  # a public IP literal
        except ValueError:
            pass  # not an IP literal -> a hostname
        if _is_remote_resolving_proxy(self._effective_base_proxy(host)):
            return  # the exit resolves; nothing for us to check
        infos = self._resolve_cached(host)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _is_blocked_ip(ip):
                raise BlockedTarget(f"refusing to fetch {host!r}: it resolves to a non-public address ({ip})")  # fixed words first (R622)

    def _resolve_cached(self, host: str) -> list:
        """``socket.getaddrinfo(host, None)`` with a short-TTL cache (C8/A6) — a
        real fetch/redirect chain can hit the SAME host several times in one pass;
        this avoids re-resolving it every time. Bounded (``_DNS_CACHE_MAX``): on
        overflow the WHOLE cache is cleared rather than a sorted eviction (the TTL
        is already short, so this self-heals within ``_DNS_CACHE_TTL_S`` regardless
        — simpler than the size-sorted eviction the robots/last-request caches use,
        and correctness never depends on which entries survive)."""
        now = self._now()
        cached = self._dns_cache.get(host)
        if cached is not None and now < cached[1]:
            return cached[0]
        try:
            infos: list | None = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise FetchFailed(f"cannot resolve host {host!r}: {record_text(exc, typed=False)}") from None
        except UnicodeError:
            # The name cannot be IDNA-encoded (an empty label, ``a..example``, or one over 63 characters), raised before any query. It
            # is a ValueError, not an OSError, and escaped the fetch raw (R622 read). Raised below, outside this handler, so that the
            # UnicodeError is not its context: record_text writes any error a UnicodeError is reachable from as that error's fixed record.
            infos = None
        if infos is None:
            raise FetchFailed(f"cannot resolve host {host!r}: the name cannot be encoded for a lookup")
        if len(self._dns_cache) >= _DNS_CACHE_MAX:
            self._dns_cache.clear()
        self._dns_cache[host] = (infos, now + _DNS_CACHE_TTL_S)
        return infos

    def _effective_base_proxy(self, host_or_netloc: str | None) -> str | None:
        """The proxy THIS host actually uses, before any per-host stream-
        isolation auth is layered on: the pool's sharded member when a POOL is
        configured (C10), else the single ``self.proxy``, else ``None``.

        ``host_or_netloc`` accepts EITHER a bare hostname (``_guard_target``'s
        ``parsed.hostname``) or a full ``netloc`` (``_isolated_proxies``'s
        ``parsed.netloc``, which may carry a port / IPv6 brackets) --
        normalised to the bare hostname here so BOTH call sites shard the SAME
        host onto the SAME pool member (a port-bearing vs bare form of the
        identical host must never disagree on which endpoint/circuit it gets)."""
        if self._proxy_pool and host_or_netloc:
            from src.safety.fetcher import shard_host_to_proxy

            hostname = urlparse(f"//{host_or_netloc}").hostname or host_or_netloc
            return shard_host_to_proxy(hostname, self._proxy_pool)
        return self.proxy

    def _isolated_proxies(self, netloc: str | None) -> dict[str, str] | None:
        """Per-HOST proxy selection + Tor stream-isolation for ``netloc`` (or
        ``None`` to use the session's base proxy).

        C10: when an operator-run SOCKS POOL is configured, ``netloc`` first
        SHARDS onto one pool member (a stable, host->endpoint mapping -- see
        ``src.safety.fetcher.shard_host_to_proxy``) -- per-host CIRCUIT
        isolation (below) is still layered on TOP of that endpoint, so a host
        gets both a dedicated endpoint AND a dedicated circuit on it. Without a
        pool this is exactly the prior single-proxy behaviour.

        Returns a ``{"http":…, "https":…}`` dict whose SOCKS URL carries a
        per-host username so Tor's ``IsolateSOCKSAuth`` builds a dedicated circuit
        for this host. The page fetch and its robots.txt both route through this,
        so a host's traffic shares one circuit and is unlinkable to other hosts'
        circuits. ``None`` ONLY when there is no proxy at all.

        WHENEVER A PROXY IS CONFIGURED THE MAPPING IS EXPLICIT, isolated or not
        (isolation disabled, or an HTTP proxy that cannot isolate, get the bare
        proxy). Until 2026-09-25 those two cases returned ``None`` and left the
        choice to ``session.proxies`` -- and requests folds the ``HTTP(S)_PROXY``
        environment into the REQUEST's mapping, which then wins over the
        session's, so a system proxy variable replaced the operator's proxy for
        exactly those fetches. A per-request mapping is merged the other way.
        """
        if not netloc:
            return None
        base = self._effective_base_proxy(netloc)
        if not base:
            return None
        if not self._stream_isolation:
            return {"http": base, "https": base}
        # Lazy import: src.safety.fetcher imports from src.ingest, so a top-level
        # import here would be circular. The helper is pure string work.
        from src.safety.fetcher import _with_stream_isolation

        isolated = _with_stream_isolation(base, netloc)
        return {"http": isolated, "https": isolated}

    def _http_get(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        proxies: dict[str, str] | None = None,
        chain: _RedirectChain | None = None,
    ):
        """GET with manual, bounded redirects, re-validating every hop (SSRF).

        ``extra_headers`` (e.g. conditional-GET validators) are sent on each hop;
        the final resource is the one that validates them. ``proxies`` (per-host
        Tor stream isolation) overrides the session proxy for THIS fetch, keyed on
        the ORIGINAL host so every redirect hop stays on the same circuit.
        ``chain`` (the page fetch's, from :meth:`fetch`) makes a hop to another
        host a first request to it (R629, :meth:`_take_hop_host`).
        """
        return self._guarded_redirect_get(
            url, extra_headers=extra_headers, proxies=proxies, stream=True, chain=chain
        )

    def _guarded_redirect_get(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        proxies: dict[str, str] | None = None,
        stream: bool = False,
        chain: _RedirectChain | None = None,
    ):
        """The ONE redirect path: follow bounded redirects manually, re-running the
        SSRF guard on EVERY hop's target (CWE-918). Returns ``(response, final_url)``.

        ``chain`` is given by the page fetch alone (``fetch`` -> ``_http_get``, R629): its
        scope is asked about every hop before the guard looks the hop's host up, and a hop
        to another host then takes that host's lock, robots.txt and interval before it is
        requested (:meth:`_take_hop_host`). Every other caller passes none and keeps the
        behaviour it had: the robots read (``_get_robots``, so ``declared_sitemaps`` too),
        whose own hops are never made to read robots.txt again, and the two preflights.

        Both the page fetch (``_http_get``, ``stream=True``) and the robots.txt
        fetch (``_get_robots``, ``stream=False``) route through here, so a 30x
        redirect to an internal address (``127.0.0.1`` / ``169.254.169.254`` / a
        rebinding hostname) is refused on the robots path exactly as on the page
        path -- closing the prior gap where robots used ``allow_redirects=True``
        and so let its redirect chain bypass the guard.

        Also honours the kill switch, for the same reason ``_guard_target`` does:
        the two preflight modules call this directly rather than through
        ``fetch()``, so without it they had no kill-switch gate of their own.

        NET-01: this is also where the CONNECT-TIME SSRF scope is entered, and it
        is entered here for the same reason the kill-switch check moved here --
        this is the ONE method through which the page fetch, the robots fetch,
        every redirect hop and both preflight side doors reach the network.
        ``_guard_target`` validates the address a hostname resolves to; requests
        then resolves the SAME name again inside ``create_connection`` and
        connects to whatever that second answer says. The scope makes every
        socket this thread opens for the duration of this request validate the
        address it is actually reaching (see ``src.ingest.ssrf_guard``), so the
        two moments can no longer disagree.
        """
        if self._real_session and _KILL.is_set():
            raise FetchFailed(KILL_SWITCH_REFUSAL)
        if proxies is None:
            # The two preflight side doors call this without a mapping. Give them the
            # host's own, as the page and robots paths do, so no request through this
            # method is left to ``session.proxies`` (see ``_isolated_proxies``).
            first = urlparse(url)
            proxies = self._isolated_proxies(_host_netloc(first.netloc, first.scheme))  # the host key, as fetch() hands it (R621, Steward 3's item 3)
        # Lazily, and on EVERY request rather than behind a one-shot flag:
        # ``src.ingest.airplane`` imports this module, so the import cannot be at
        # module level, and the installer is an ``if already installed: return``
        # -- so re-asking costs a sys.modules lookup and self-heals after a test
        # (or anything else) restores the real socket calls. A "we decided once"
        # flag would leave the guard silently absent from that point on.
        from src.ingest.airplane import ensure_connect_guard_installed

        ensure_connect_guard_installed()
        current = url
        unreadable_from: str | None = None
        with connect_scope(
            enabled=self._real_session,
            proxies=self._request_proxy_endpoints(url, proxies),
        ):
            # ONE translation, around the WHOLE scope body rather than around the
            # GET alone: a redirect hop's own ``_guard_target`` resolves inside
            # the scope, so the resolution check can raise from there too, and a
            # try around ``session.get`` would have let that one escape as a
            # BlockedConnectTarget -- a type no caller catches, on a path that is
            # refused for exactly the same reason. Callers keep the exception
            # contract they already have: a connect-time refusal is a
            # BlockedTarget like a resolve-time one, deterministic, never retried.
            try:
                for hop in range(self._max_redirects + 1):
                    kwargs: dict[str, Any] = {"timeout": self.timeout, "allow_redirects": False}
                    if extra_headers:
                        kwargs["headers"] = extra_headers
                    if proxies:
                        kwargs["proxies"] = proxies
                    if stream and self._real_session:
                        kwargs["stream"] = True
                    self._refuse_parser_mismatch(current)
                    resp = self.session.get(current, **kwargs)
                    status = resp.status_code
                    location = resp.headers.get("Location") if hasattr(resp, "headers") else None
                    if 300 <= status < 400 and location:
                        try:
                            nxt = urljoin(current, location)
                            p = urlparse(nxt)
                        except ValueError:
                            # An unclosed IPv6 bracket (``http://[::1/x``) or a netloc NFKC would change: a bare ValueError escaped the
                            # fetch, so the robots read never backed the host off and ``ingest_url`` did not catch it (R622 read).
                            raise FetchFailed(f"redirect to a URL that cannot be read: {failure_url(location)!r}") from None
                        if p.scheme not in ("http", "https") or not p.netloc:
                            raise FetchFailed(f"redirect to unsupported URL: {failure_url(nxt)!r}")
                        # The hop is read BEFORE the guard looks its host up (R622), not on the next turn of the loop: a Location
                        # can name a host with spaces in it, which reached the resolver and began the guard's sentence. A tab, CR
                        # or LF is read as a space, as the first request's own check reads it, since ``urljoin`` deletes them.
                        visible = location.translate(_URLSPLIT_DELETES_AS_SPACE)
                        if visible != location:
                            try:
                                self._refuse_parser_mismatch(urljoin(current, visible))
                            except ValueError:  # shown as a space, a bracketed host is no longer an address
                                raise BlockedTarget("URL host cannot be read") from None
                        self._refuse_parser_mismatch(nxt)
                        if _carries_userinfo(location):
                            # A Location that writes a user name or password (R633): followed, the server's choice of login went out
                            # as an Authorization header and the address, login included, came back as the page's URL to be stored
                            # (a review measured it). Refused before anything is asked of its host, for every caller, robots reads
                            # included. The Location is read, not the joined URL: a relative Location writes no authority and keeps
                            # the one of the request it answers, so an address the caller wrote with a login keeps it on that host,
                            # as before; any Location that writes one is refused, the caller's own login included, so a login is
                            # never handed to another host. (``urljoin`` above has already read the Location, so this reads it the
                            # same way, and never raises.) A BlockedTarget, as R622's refusals of the address beside it: deterministic,
                            # never retried, and the type a caller holding a fetch to one host already reads as a refused hop.
                            raise BlockedTarget(
                                f"redirect to an address that carries a user name or password, not followed: {failure_url(nxt)!r}"
                            )
                        if chain is not None:
                            self._refuse_out_of_scope(chain, nxt)  # before the guard looks the host up: nothing is asked of it (R629)
                        self._guard_target(p.hostname)  # re-validate the redirect target
                        if hasattr(resp, "close"):
                            resp.close()
                        if chain is not None and hop < self._max_redirects:  # never for a hop the bound will not request
                            self._take_hop_host(chain, nxt, p)
                        current = nxt
                        continue
                    return resp, str(getattr(resp, "url", current) or current)
            except BlockedConnectTarget as exc:
                raise BlockedTarget(record_text(exc, typed=False)) from None
            except requests.RequestException:
                raise
            except ValueError:
                # requests parses a 3xx answer's Location even when it is told not to follow it (``Session.send`` builds
                # ``Response.next`` through ``resolve_redirects``), and a Location urlsplit cannot read (an unclosed IPv6
                # bracket) raised a bare ValueError out of the request: the robots read never backed the host off, and
                # ``ingest_url`` did not catch it (R622 read). Handled here, round the loop, and not round the request itself,
                # so the request line stays as main has it (the CodeQL fingerprint lesson of 2026-10-16); the loop's own reads
                # already turn theirs into BlockedTarget or FetchFailed, so what reaches this handler is the request's. Raised below, outside
                # this handler, so no UnicodeError is its context (record_text writes any error a UnicodeError is reachable
                # from as that error's fixed record).
                unreadable_from = current
        if unreadable_from is not None:
            raise FetchFailed(f"redirect to a URL that cannot be read, from {failure_url(unreadable_from)}")
        raise FetchFailed(f"too many redirects for {failure_url(url)}")

    @staticmethod
    def _refuse_out_of_scope(chain: _RedirectChain, nxt: str) -> None:
        """Refuse a hop the page fetch's scope does not cover (R629), before anything is asked of its host. A scope that cannot
        answer (it raises) keeps the hop out: the scope is a promise about where a fetch may go, so a doubt refuses."""
        if chain.scope is None:
            return
        try:
            inside = bool(chain.scope(nxt))
        except Exception:  # noqa: BLE001 - fail closed; the hop is refused in fixed words below, the error is not written
            inside = False
        if not inside:
            raise RedirectOutOfScope(f"redirect leaves the site the fetch is kept to, not followed: {failure_url(nxt)!r}")

    def _take_hop_host(self, chain: _RedirectChain, nxt: str, p) -> None:
        """Make a page fetch's hop to ANOTHER host a first request to it (R629), before it is requested.

        Another host is another host key (``_host_netloc``: the host and the port a request goes to), the key every per-host
        record already uses. A hop on the same key (another path, or ``http`` -> ``https`` on the same host) is unchanged: it is
        under that host's lock, and the robots decision and the interval of the first request stand for it. For another host,
        in the order ``fetch()`` takes them for a first request, each fail-closed:
          - the chain's lock moves to the new host (the old one stamped and released first, never two held: see _RedirectChain);
          - its robots.txt (``_enforce_robots``: a disallow is RobotsDisallowed, an unreadable robots.txt RobotsUnavailable, the
            same refusals as a first request's, ending with fixed words that say a redirect led there);
          - its interval or Crawl-delay is waited, or deferred past the cap (CrawlDelayDeferred, the stamp written first, its
            sentence naming the hop's address and ending with the same fixed words);
          - the switch is read before and after the waits: a Stop pressed while the hop waited for a lock or an interval refuses
            it, for an injected session as for a real one (the hop's own ``_guard_target`` reads it first only for a real one).
        The robots read is ``_get_robots``, which passes no chain on: its own redirect hops keep today's behaviour and never read
        robots.txt themselves, so a read can never recurse."""
        key = _host_netloc(p.netloc, p.scheme)
        if key == chain.netloc:
            return
        if _KILL.is_set():
            raise FetchFailed(KILL_SWITCH_REFUSAL)
        chain.move(key)
        host_key = f"{p.scheme}://{key}"
        if self.respect_robots:
            self._enforce_robots(nxt, host_key, p._replace(netloc=key), hop=True)
        self._respect_rate_limit(key, host_key, hop_url=nxt)
        if _KILL.is_set():
            raise FetchFailed(KILL_SWITCH_REFUSAL)
        chain.requested = True

    @staticmethod
    def _refuse_parser_mismatch(url: str) -> None:
        """Refuse a URL that ``urlparse`` and ``urllib3`` read as two different hosts.

        ``_guard_target`` is handed ``urlparse(url).hostname`` while the connection is
        made to the host ``requests``/``urllib3`` parse out of the same string, and
        the two disagree on a backslash before an ``@`` (``https://evil.test\\@good.org/``
        is ``good.org`` to the first and ``evil.test`` to the second). The connect-time
        guard still catches an internal address, but not where it stands down (a
        hostname proxy), so the disagreement itself is refused, on the first request
        and on every redirect hop.
        """
        # Only the authority can send the two parsers to different hosts; a space in a
        # path or query is encoded by requests and fetched, so it is not refused.
        rest = url.split("://", 1)[1] if "://" in url else url
        authority = rest
        for stop in ("/", "?", "#"):
            authority = authority.split(stop, 1)[0]
        if _unsafe_url_text(authority):
            raise BlockedTarget("URL authority contains a backslash, whitespace or control character")
        from urllib3.util import parse_url

        try:
            theirs = (parse_url(url).host or "").lower().strip("[]")
        except Exception:  # noqa: BLE001 - an unparsable URL is refused, not fetched
            raise BlockedTarget("URL is not parsable by the HTTP client") from None
        try:
            ours = (urlparse(url).hostname or "").lower().strip("[]")
        except ValueError:
            raise BlockedTarget("URL host cannot be read") from None
        if "%" in theirs or "%" in ours:
            # Whether a percent-encoded host is decoded depends on the urllib3 version (2.7.0 connects to the decoded
            # address, urlparse reads a name), so it is refused outright rather than compared.
            raise BlockedTarget("URL host is percent-encoded")
        if not ours.isascii():
            # Two IDNA standards disagree on some names (faß.de), so a non-ASCII host
            # is accepted only when the codec the resolver uses gives the client's name.
            try:
                ours = ours.encode("idna").decode("ascii")
            except UnicodeError:
                raise BlockedTarget("URL host cannot be encoded") from None
        if theirs != ours:
            raise BlockedTarget("URL host is read differently by two parsers")

    def _request_proxy_endpoints(
        self, url: str, explicit: dict[str, str] | None
    ) -> dict[str, str]:
        """Every proxy this request could actually be sent through.

        The connect-time guard allowlists the proxy endpoint, so it has to know
        the same endpoint ``requests`` will use -- and ``session.proxies`` is not
        that answer. ``Session.merge_environment_settings`` folds in the
        ``HTTP(S)_PROXY`` environment (honouring ``NO_PROXY``) whenever
        ``trust_env`` is set, which is the default; a guard that only read
        ``session.proxies`` would refuse the proxy connection of every operator
        whose proxy comes from their environment. Merged in the precedence
        requests itself uses (``Session.merge_environment_settings``): the
        per-request mapping over the environment over the session -- the
        environment is folded into the REQUEST's mapping, which then wins over
        the session's. (Before 2026-09-25 this read session over environment,
        the reverse of what requests does.)

        The result is then narrowed to the keys ``requests.utils.select_proxy``
        can ever consult -- read out of the installed library rather than
        recalled: ``<scheme>://<hostname>``, ``<scheme>``, ``all://<hostname>``,
        ``all``. That is a SUPERSET of whatever is selected for any hop, so it
        can never refuse a proxy requests would actually use, and it drops the
        rest of what ``get_environ_proxies`` returns -- which is every
        ``*_proxy`` variable in the environment with its suffix stripped, so
        ``NO_PROXY`` arrives as the key ``no`` carrying a comma-separated host
        list and ``yarn_https_proxy`` as ``yarn_https``. Those matter because a
        proxy endpoint given as a HOSTNAME stands the guard down for the request:
        without this filter, an unrelated ``npm_config_proxy`` naming a host
        would silently disable the check on a great many developer machines.
        """
        merged: dict[str, str] = dict(getattr(self.session, "proxies", None) or {})
        if getattr(self.session, "trust_env", False):
            try:
                merged.update(requests.utils.get_environ_proxies(url, no_proxy=None))
            except Exception as exc:  # noqa: BLE001 - an unreadable environment is not a fetch error
                log_failure(
                    _LOG,
                    f"could not read environment proxies for {failure_url(url)!r}",
                    exc,
                    *userinfo_secrets(url),
                    level=logging.DEBUG,
                )
        merged.update(explicit or {})
        return {k: v for k, v in merged.items() if k in _SELECTABLE_PROXY_KEYS or "://" in k}

    def _read_body(
        self, response, url: str, *, token: int | None = None, keep_bytes: bool = False
    ) -> tuple[str, bytes | None]:
        """Decode the body, enforcing ``max_bytes`` *before* materialising it (DoS).

        A declared Content-Length over the cap is rejected up front; for the real
        (streamed) session the body is read incrementally and aborted once the
        decompressed size exceeds the cap (defeats gzip/decompression bombs).

        Returns ``(decoded_text, raw_bytes_or_None)`` — ``raw_bytes`` is the
        undecoded body when ``keep_bytes`` is set (already bounded by
        ``max_bytes``), else None so no extra memory is held.
        """
        cl = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        if cl and str(cl).isdigit() and int(cl) > self.max_bytes:
            raise FetchFailed(f"declared length {cl} exceeds {self.max_bytes} bytes for {failure_url(url)}")
        if self._real_session and hasattr(response, "iter_content"):
            total = 0
            chunks: list[bytes] = []
            started = self._now()
            # 16 KiB chunks, not 64: the deadline below is checked between chunks, and a
            # blocking read returns only when its chunk is full, so the chunk size is the
            # granularity at which a trickling server can be caught.
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                if self._now() - started > self.body_deadline_s:
                    if hasattr(response, "close"):
                        response.close()
                    raise FetchFailed(
                        f"body read exceeded {self.body_deadline_s:.0f}s for {failure_url(url)} "
                        "(a slow or trickling response)"
                    )
                total += len(chunk)
                if total > self.max_bytes:
                    if hasattr(response, "close"):
                        response.close()
                    raise FetchFailed(f"response exceeds {self.max_bytes} bytes for {failure_url(url)}")
                chunks.append(chunk)
            raw = b"".join(chunks)
            activity_monitor.fetch_bytes(total, token)  # real, app-attributed download size
            # Pick a text encoding WITHOUT touching response.apparent_encoding: on a
            # streamed response the body is already consumed, so apparent_encoding
            # re-reads it and raises "content already consumed" (crashing the scrape).
            # Detect from the bytes we just collected instead. requests also defaults
            # unlabelled text/* to ISO-8859-1, which is usually wrong for modern pages,
            # so detect in that case too.
            encoding = getattr(response, "encoding", None)
            if not encoding or str(encoding).lower() in ("iso-8859-1", "latin-1"):
                try:
                    from charset_normalizer import from_bytes

                    best = from_bytes(raw).best()
                    if best and best.encoding:
                        encoding = best.encoding
                except Exception:  # noqa: BLE001 - detection is best-effort
                    pass
                encoding = encoding or "utf-8"
            kept = raw if keep_bytes else None
            try:
                return raw.decode(encoding, errors="replace"), kept
            except (LookupError, TypeError):
                return raw.decode("utf-8", errors="replace"), kept
        # Injected (test) session: not streamed; check the already-materialised body.
        if response.content and len(response.content) > self.max_bytes:
            raise FetchFailed(f"response exceeds {self.max_bytes} bytes for {failure_url(url)}")
        activity_monitor.fetch_bytes(len(response.content or b""), token)
        return response.text, (response.content if keep_bytes else None)

    # -- robots ------------------------------------------------------------ #

    def forget_robots(self, host_or_key: str) -> int:
        """Drop every cached robots decision for this host, returning how many were dropped.

        THE TRAP THIS EXISTS FOR. The per-host backoff is the right default and the wrong
        answer to an OPERATOR SAYING "check these again". A `--retry robots_unavailable` run
        starts by loading the sidecar, so every host it means to re-ask is already inside the
        backoff that its own earlier failure created -- the run would return the cached
        refusal, rewrite the same verdict, and look like work while asking no host anything.

        So an explicit retry forgets first. Scheme-agnostic (the cache is keyed by
        ``https://host``, and a run may name either), and it clears the decision, the cause
        and the failure counter together -- a partial forget would re-ask the host and then
        apply a backoff computed from failures it is no longer counting.
        """
        raw = (host_or_key or "").strip().lower()
        if not raw:
            return 0
        netloc = raw.split("://", 1)[-1].split("/", 1)[0]
        if not _host_netloc(netloc):
            return 0
        # the cache is keyed by the host key, per scheme (R621): no userinfo, one spelling, no default port
        targets = {f"{scheme}://{_host_netloc(netloc, scheme)}" for scheme in _DEFAULT_PORTS}
        dropped = 0
        for key in [k for k in self._robots if k in targets]:
            self._robots.pop(key, None)
            self._robots_cause.pop(key, None)
            self._robots_fails.pop(key, None)
            dropped += 1
        return dropped

    def _enforce_robots(self, url: str, host_key: str, parsed, *, hop: bool = False) -> None:
        """Refuse ``url`` unless its host's robots.txt allows it. ``hop``: ``url`` is a redirect hop's (R629), and the refusal
        ends with fixed words saying so, since the caller records it against the address it asked for."""
        via = f" ({_REDIRECT_HOP_NOTE})" if hop else ""
        parser = self._get_robots(host_key, parsed)
        if parser is None:
            # "unknown", never a plausible default: a sidecar entry written before the
            # cause existed, or evicted from the map, has no cause to report, and inventing
            # one would put a confident wrong attribution into the pipeline's own data.
            cause = self._robots_cause.get(host_key, "unknown")
            # A 401/403 for a page address that carried a user name or password is not the same news as a Tor exit's 403: the
            # robots read went out without them (one anonymous read per host, R621), so a robots.txt behind the login answers
            # this way. Said in fixed words AFTER the sentence every reader reads, which is otherwise unchanged (N2).
            caveat = f" ({_ROBOTS_READ_WITHOUT_USERINFO})" if cause == "refused" and _carries_userinfo(url) else ""
            raise RobotsUnavailable(
                f"robots.txt for {failure_url(host_key)} could not be determined ({cause}); refusing to fetch{caveat}{via}",
                cause=cause,
            )
        # RobotFileParser compares the path AND what follows it, so an address with an EMPTY path and a query or a fragment
        # (https://b.example?x, https://b.example#f) was compared as "?x" or "#f", which no "Disallow: /" covers, while requests
        # asks for "/?x": the page was fetched against its host's robots.txt (the independent read of R629, S1; it predates R629,
        # and direct fetches had it too). Checked as the "/" it is fetched as; the refusal still names the address as written.
        # (``url`` was read by urlparse before this call, so urlsplit reads it too.)
        parts = urlsplit(url)
        checked = urlunsplit(parts._replace(path="/")) if not parts.path else url
        if not parser.can_fetch(self.user_agent, checked):
            raise RobotsDisallowed(f"robots.txt disallows {failure_url(url)}{via}")

    def _get_robots(self, host_key: str, parsed) -> RobotFileParser | None:
        cached = self._robots.get(host_key)
        if cached is not None and self._now() < cached[1]:
            return cached[0]

        robots_url = f"{host_key}/robots.txt"
        # Same per-host Tor circuit as the page fetch, so a host's robots.txt is
        # not leaked onto the shared base circuit (complete per-host isolation).
        iso = self._isolated_proxies(getattr(parsed, "netloc", None))
        decision: RobotFileParser | None
        # Persisted alongside `decision` (A5, C4) so a reload can reconstruct the
        # SAME parser: "parsed" carries the raw body, "allow_all"/"disallow_all"
        # need none (defaults below cover every early-return/exception path).
        persist_kind = "disallow_all"
        persist_body: str | None = None
        cause = "unreachable"
        epoch = kill_switch_epoch()  # before the request: a Stop pressed and cleared inside it is still a Stop (R614)
        try:
            # Follow redirects MANUALLY through the shared guarded loop so a
            # robots.txt that 30x-redirects to an internal address is refused
            # (SSRF, CWE-918). Previously this used allow_redirects=True, which let
            # the robots redirect chain bypass the per-hop SSRF guard that the page
            # fetch always applied (finding OO-D2-001).
            resp, _robots_final = self._guarded_redirect_get(robots_url, proxies=iso)
            status = resp.status_code
            if status == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                decision = rp
                persist_kind, persist_body = "parsed", resp.text
            elif status in (404, 410):
                # No robots.txt -> everything allowed (standard behaviour).
                rp = RobotFileParser()
                rp.parse([])
                decision = rp
                persist_kind = "allow_all"
            elif status in (401, 403):
                # Access to robots is REFUSED on this path -> fail closed. Recorded as its
                # own cause rather than as a policy: over Tor this is frequently the exit's
                # reputation, and the answer does not say which (2026-09-11 measurement --
                # 7,847 unavailable against 262 explicitly disallowed, thirty to one, at a
                # uniform 25-53% across fourteen countries on every continent).
                decision = None
                cause = "refused"
            else:
                # 5xx / unexpected -> the host is broken, not speaking -> fail closed.
                decision = None
                cause = "server_error"
        except (requests.RequestException, FetchError) as exc:
            # The switch's own refusal, by its sentence: engaged before the capture, it refused this read by
            # name, and a clear may land before this line, so neither the switch nor the count says so now.
            # A wider match here could only skip a cache write (the host is asked again), never cause a fetch.
            refused_by_name = isinstance(exc, FetchError) and record_text(exc, typed=False).startswith(KILL_SWITCH_REFUSAL_HEAD)
            if refused_by_name or kill_switch_engaged_since(epoch):
                # A refusal BY THE SWITCH, or a request cut off by it mid-flight (the socket
                # guard's OSError arrives here wrapped in a requests error), is not an answer
                # about the host: cached as "unreachable" it blamed the host for an hour and
                # the NEXT pass acted on a verdict no request ever produced (R297). Nothing is
                # cached or persisted, so the next fetch asks again; the refusal says what it was.
                # The same when the switch was engaged and cleared again while this request was
                # in flight: the epoch says a Stop happened, whatever the switch reads now (R614).
                if isinstance(exc, FetchError):
                    raise
                raise FetchFailed(KILL_SWITCH_REFUSAL) from None
            # network/timeout, an SSRF-blocked redirect target, a redirect to an
            # unsupported scheme, or too many redirects -> cannot safely determine
            # robots -> fail closed.
            decision = None
            cause = "unreachable"

        # A FAILURE BACKS OFF; A SUCCESS CLEARS THE COUNTER OUTRIGHT. The deferral is
        # per host and capped, so a host that keeps refusing is asked once a day instead
        # of once an hour, and is never struck off.
        if decision is None:
            fails = self._robots_fails.get(host_key, 0) + 1
            self._robots_fails[host_key] = fails
            self._robots_cause[host_key] = cause
        else:
            fails = 0
            self._robots_fails.pop(host_key, None)
            self._robots_cause.pop(host_key, None)
        ttl = _robots_ttl_for(fails)
        self._robots[host_key] = (decision, self._now() + ttl)
        if _robots_persist_enabled():
            _persist_robots_entry(
                self._robots_cache_path, host_key, kind=persist_kind, body=persist_body,
                cause=cause if decision is None else None, fails=fails, ttl=ttl,
            )
        return decision

    # -- rate limiting ----------------------------------------------------- #

    def _respect_rate_limit(self, netloc: str, host_key: str, *, hop_url: str | None = None) -> None:
        """Wait out this host's interval, or REFUSE when the wait is too long.

        S04-13 S2 (Q1013 = a). Two stamps CAN decide the wait and they live in
        different clock frames (see the module-level block): ``_last_request`` is this
        process's monotonic record, the sidecar is a wall-clock record that survives
        the per-pass fetcher rebuild. They are not both consulted for the same host:
        ``_last_request`` is the authority whenever it has an entry, and the sidecar
        speaks only where it knows something that record cannot -- first contact in
        this process, or a declared delay our robots cache has since forgotten. The
        longer wait still wins where both apply; what is gone is the case where both
        described the SAME constraint through different clocks (the block below
        records what that cost).

        Beyond the cap the wait is refused by name rather than slept. The refusal is
        a DEFERRAL, not a failure of the source: the stamp is still written, so the
        next pass knows when this host becomes available instead of re-asking it
        immediately and paying the same wait again.
        """
        interval = self.min_interval_s
        declared_delay = 0.0
        cached = self._robots.get(host_key)
        if cached and cached[0] is not None:
            try:
                delay = cached[0].crawl_delay(self.user_agent)
            except Exception:
                delay = None
            if delay:
                declared_delay = float(delay)
                interval = max(interval, declared_delay)

        wait = 0.0
        last = self._last_request.get(netloc)
        if last is not None:
            elapsed = self._now() - last
            if elapsed < interval:
                wait = interval - elapsed

        # The persisted stamp -- consulted ONLY when it can say something this
        # instance's own record cannot. Two conditions, and the negative space is the
        # point: a host we have already contacted in THIS process is governed by
        # ``_last_request`` above, which is the same constraint measured by the same
        # clock, so re-deriving it from the sidecar adds no information and makes two
        # records of one quantity -- which is exactly how the two came to DISAGREE.
        # Measured, not feared: the sidecar is wall-clock and ``_last_request`` is
        # monotonic, so under an injected test clock the wall read returned the full
        # interval (real elapsed ~0.1 ms) while the monotonic read returned the
        # correct remainder, and ``max()`` took the stale one -- a fetcher sleeping
        # 10 s where 8 were owed. In production the two frames tick together and the
        # ``max()`` was simply redundant; the disagreement only ever showed up where
        # something moved one clock and not the other.
        #
        # The second condition is the one that earns its keep: a sidecar delay LARGER
        # than anything we can re-derive means our robots cache has forgotten (a fresh
        # pass, or a lapsed TTL) what the host itself declared. Then the stamp is the
        # only surviving record of the host's own stated wish, and it wins.
        stamp = self._host_schedule.get(netloc)
        if stamp is not None:
            not_before, persisted_delay = stamp
            if netloc not in self._last_request or persisted_delay > declared_delay:
                if persisted_delay > declared_delay:
                    declared_delay = persisted_delay
                    interval = max(interval, persisted_delay)
                wait = max(wait, _stamp_remaining(not_before, persisted_delay, self.min_interval_s, netloc))

        if wait <= 0:
            self._stamp_host_schedule(netloc, interval, declared_delay)
            return

        cap = _crawl_delay_max_wait_s()
        if wait > cap:
            # Write the stamp BEFORE raising. A deferral that forgot when the host
            # becomes free would send the next pass straight back into the same
            # refusal, which is the "refuse and retry next pass" failure this whole
            # sidecar exists to prevent.
            resume_at = self._stamp_host_schedule(netloc, wait, declared_delay)
            # A redirect hop's deferral (R629) is the hop host's Crawl-delay, not the page asked for's: its address and the fixed
            # words that say a redirect led there come after the sentence every reader reads (Steward 3's item 1), so a caller
            # filing it against the page it asked for still says whose Crawl-delay it was. Readers key on the type and on the
            # "deferred" prefix law/track.py writes before it (src/api/law.py _verdict_of), never on these words.
            where = f", for {failure_url(hop_url)!r} ({_REDIRECT_HOP_NOTE})" if hop_url else ""
            raise CrawlDelayDeferred(
                f"Crawl-delay {declared_delay or interval:g} s: not before "
                f"{datetime.fromtimestamp(resume_at, UTC).isoformat(timespec='seconds')}{where}",
                netloc=netloc,
                delay_s=declared_delay or interval,
                not_before=resume_at,
            )
        self._sleep(wait)
        self._stamp_host_schedule(netloc, interval, declared_delay)

    def _stamp_host_schedule(self, netloc: str, interval: float, declared_delay: float) -> float:
        """Record when this host may next be fetched, and return that wall time.

        Only a host that DECLARES a ``Crawl-delay`` is persisted. The ordinary
        one-second courtesy interval needs no sidecar -- it has always been shorter
        than the gap between two passes touching one host, so writing it would add a
        4096-entry file write per fetch to record a constraint that can never bind.
        """
        resume_at = time.time() + max(0.0, interval)
        if declared_delay <= 0:
            return resume_at
        self._host_schedule[netloc] = (resume_at, declared_delay)
        if _host_schedule_persist_enabled():
            _persist_host_schedule(
                self._host_schedule_path, netloc, resume_at, declared_delay
            )
        return resume_at
