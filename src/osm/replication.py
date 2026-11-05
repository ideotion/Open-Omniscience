"""Geofabrik's daily change files for one extract: where they are, which are owed, and how one is fetched (S06-01 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q812 = a: «Geofabrik daily diffs per selected extract, applied to the ingested classes; if a diff older than the three-month
retention is needed, re-baseline from a fresh extract and say so.» Q824 = a puts the daily apply inside the online consent.

THE LAYOUT IS THE OSM REPLICATION FORMAT, AND IT IS FROM MEMORY. Geofabrik publishes, beside each extract, a directory
``<region>-updates/`` holding ``state.txt`` (the newest sequence number and its time), and for each sequence ``N`` the change file
``AAA/BBB/CCC.osc.gz`` and its ``AAA/BBB/CCC.state.txt`` (``N`` written as three groups of three digits). The brief (S06-01 §5 step 2)
makes confirming this, and the retention figure, an operator step on a networked machine: the build container reaches no mirror, so
nothing here was read from one. Every figure below is the code's reading of that layout, and the tests build their fixtures from it.

THE URL IS BUILT, NEVER READ. The extract's header names a replication base URL; this module does not use it. The host is the one
the download manager already talks to (``GEOFABRIK_BASE``), the path is built from a region code that passed ``is_valid_code``, and the
session refuses any other host on every hop (R143): a file's header is somebody else's text and must not choose where this app connects.

THE NAMED REFUSALS. A fetch the kill switch stopped says so ("refused: airplane mode is engaged"), never "fetch failed" (invariant
#14e's corollary); a transport that is unavailable says that; a change file the mirror no longer holds is ``DiffNotFound`` (the
re-baseline signal), and every other failure is ``DiffUnavailable``. Nothing here retries: a retry is the caller's, and a Tor
circuit that fails is never replaced by a clearnet one (the session never downgrades).

The module reads no database and writes only the one file it is asked to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

from src.geo.osm_downloads import GEOFABRIK_BASE
from src.geo.osm_regions import is_valid_code
from src.osm.picker import DIFF_RETENTION_DAYS

#: ``europe-latest.osm.pbf`` -> ``europe``. Only a top-level region: the download manager refuses a sub-path (``is_valid_code``).
_EXTRACT_NAME = re.compile(r"^([a-z]+(?:-[a-z]+)*)-latest\.osm\.pbf$")


class ReplicationError(ValueError):
    """The mirror answered with something that is not a replication state (or a sequence that cannot be a number)."""


class DiffNotFound(LookupError):
    """The mirror says it does not hold this file (HTTP 404): past its retention, or never published."""


class DiffRefused(RuntimeError):
    """A gate stopped the request before it was sent: the kill switch, a transport that is unavailable, a host that is not listed.

    The text is the NAME of the gate (a fixed sentence), so a page can show it as the reason, not as a failure of the mirror.
    """


class DiffUnavailable(RuntimeError):
    """The request was sent (or tried) and failed for a reason of the network or the mirror: a drop, a timeout, a 5xx."""


KILL_SWITCH_TEXT = "refused: airplane mode is engaged, so no change file was requested"

#: The one host a change-file session may reach (R143: the session refuses any other host on every hop). It is the download manager's own,
#: and it is a module-level name so the pin in ``tests/test_session_host_list.py`` can read it against the popup lane that names it.
REPLICATION_HOSTS = (urlparse(GEOFABRIK_BASE).hostname or "",)  # a tuple: a list could be widened in place by any caller


@dataclass(frozen=True, slots=True)
class ReplicationState:
    """One ``state.txt``: the newest (or this file's own) sequence number and the time it carries."""

    sequence: int
    timestamp: datetime


def parse_state(text: str) -> ReplicationState:
    """The ``sequenceNumber`` and ``timestamp`` of a replication state file (a Java properties file: ``key=value``, ``\\:`` for a colon)."""
    values: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().replace("\\:", ":").replace("\\\\", "\\")
    seq = values.get("sequenceNumber", "")
    if not seq.isdigit():
        raise ReplicationError("the state file has no whole-number sequenceNumber")
    stamp = values.get("timestamp", "")
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise ReplicationError("the state file has no readable timestamp") from None
    if when.tzinfo is None:
        raise ReplicationError("the state file's timestamp carries no time zone")
    return ReplicationState(int(seq), when)


def sequence_path(sequence: int) -> str:
    """``4123`` -> ``000/004/123``: the three groups of three digits a replication directory is laid out in."""
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0 or sequence > 999_999_999:
        raise ReplicationError("a sequence number is a whole number from 0 to 999,999,999")
    return f"{sequence // 1_000_000:03d}/{sequence // 1000 % 1000:03d}/{sequence % 1000:03d}"


def region_of(extract_name: str | None) -> str | None:
    """The Geofabrik region an extract file was downloaded as (``europe-latest.osm.pbf`` -> ``europe``), or None for any other name."""
    m = _EXTRACT_NAME.match(extract_name or "")
    if m is None or not is_valid_code(m.group(1)):
        return None
    return m.group(1)


def updates_base(region: str) -> str:
    """``https://download.geofabrik.de/<region>-updates``, for a region code that passed the download manager's path-safety gate."""
    if not is_valid_code(region):
        raise ReplicationError("not a region code")
    return f"{GEOFABRIK_BASE}/{region}-updates"


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    """What to do about the mirror's state. ``action`` is exactly one of the four; ``first``..``last`` is the range owed (inclusive)."""

    action: Literal["current", "apply", "rebaseline", "mirror-behind"]
    first: int | None = None
    last: int | None = None
    #: How far the mirror's newest time is ahead of the country's newest applied time, in days (None when either is unknown).
    days_behind: float | None = None
    #: A sentence for the dated event and the page, in the code's own words.
    reason: str | None = None


def plan_updates(
    *,
    applied_sequence: int,
    applied_timestamp: datetime | None,
    remote: ReplicationState,
    retention_days: float = DIFF_RETENTION_DAYS,
) -> UpdatePlan:
    """Decide from the country's position and the mirror's state. Pure: the same inputs always give the same plan.

    * the mirror is at the country's sequence: ``current`` (a quiet day is a plan, not a failure);
    * the mirror is BEHIND the country: ``mirror-behind``, a refusal that applies nothing (a mirror that went backwards, or a
      country position from another stream, is not a place to apply from);
    * the mirror's newest time is more than ``retention_days`` ahead of the country's: ``rebaseline`` BEFORE any request, because
      the first file owed is older than the mirror keeps (the stated rule, Q812);
    * otherwise ``apply`` ``applied_sequence + 1`` through ``remote.sequence``. A file the mirror turns out not to hold is
      found by the fetch (``DiffNotFound``) and ends in a re-baseline too: the retention figure is the code's, the mirror's is real.
    """
    if remote.sequence == applied_sequence:
        return UpdatePlan("current", reason="the mirror has no newer change file")
    if remote.sequence < applied_sequence:
        return UpdatePlan(
            "mirror-behind",
            reason="the mirror's newest change file is older than the one already applied, so nothing was applied",
        )
    days = None if applied_timestamp is None else (remote.timestamp - applied_timestamp).total_seconds() / 86400.0
    if days is not None and days > retention_days:
        return UpdatePlan(
            "rebaseline",
            days_behind=days,
            reason=(
                f"the first change file owed is about {days:.0f} days older than the mirror's newest, past the "
                f"~{retention_days:.0f} days it keeps, so the extract has to be downloaded again"
            ),
        )
    return UpdatePlan("apply", first=applied_sequence + 1, last=remote.sequence, days_behind=days)


class DiffSource(Protocol):
    """Where state files and change files come from. The apply is handed one; it never builds a client of its own, so a test passes a
    class that reads files and production passes :class:`GuardedDiffSource` (the same rule as ``versioned.adapters.base``)."""

    def fetch_state(self, sequence: int | None = None) -> str:
        """The text of ``state.txt`` (the newest) or of one sequence's own state file."""
        ...

    def fetch_diff(self, sequence: int, dest: Path) -> int:
        """Write sequence ``sequence``'s ``.osc.gz`` to ``dest`` and return the bytes written (the compressed size)."""
        ...


_CHUNK = 1024 * 1024


def _kill_switch_engaged() -> bool:
    from src.ingest import kill_switch_active

    return bool(kill_switch_active())


class GuardedDiffSource:
    """The production source: Geofabrik, through the ONE guarded session (kill switch, protected-mode proxy, host list on every hop)."""

    def __init__(self, region: str, *, session_factory=None, timeout: float = 60.0) -> None:
        self.base = updates_base(region)
        self._factory = session_factory
        self._timeout = timeout

    def _session(self, url: str):
        if self._factory is not None:
            return self._factory(url)
        from src.safety.fetcher import guarded_session

        return guarded_session(isolation_token=url, allowed_hosts=REPLICATION_HOSTS)

    def _get(self, url: str):
        from src.ingest.airplane import AirplaneModeError
        from src.monitoring.secret_scrub import record_text
        from src.safety.fetcher import NetworkBlocked, RedirectRefused, TransportUnavailable

        try:
            resp = self._session(url).get(url, stream=True, timeout=self._timeout)
        except (NetworkBlocked, AirplaneModeError):
            raise DiffRefused(KILL_SWITCH_TEXT) from None
        except TransportUnavailable as exc:
            # A ConnectionError, named BEFORE the generic clause below: the operator's protected mode has nothing to route through,
            # which is theirs to fix, and the same request would be refused the same way. Never retried over clearnet.
            raise DiffRefused(record_text(exc)) from None
        except RedirectRefused as exc:
            raise DiffRefused(record_text(exc)) from None
        except Exception as exc:  # noqa: BLE001 - every other failure of the request is the network's or the mirror's
            # The socket-level guard raises inside urllib3 and requests wraps it as a ConnectionError, so a switch thrown after the
            # request's own check arrives here as a network failure: the switch is asked again before the text is chosen.
            if _kill_switch_engaged():
                raise DiffRefused(KILL_SWITCH_TEXT) from None
            raise DiffUnavailable(record_text(exc)) from None
        status = getattr(resp, "status_code", 200)
        if status == 404:
            resp.close()
            raise DiffNotFound("the mirror does not hold this file")
        if status != 200:
            resp.close()
            raise DiffUnavailable(f"the mirror answered HTTP {status}")
        return resp

    def fetch_state(self, sequence: int | None = None) -> str:
        url = f"{self.base}/state.txt" if sequence is None else f"{self.base}/{sequence_path(sequence)}.state.txt"
        resp = self._get(url)
        try:
            return resp.text
        finally:
            resp.close()

    def fetch_diff(self, sequence: int, dest: Path) -> int:
        resp = self._get(f"{self.base}/{sequence_path(sequence)}.osc.gz")
        written = 0
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(_CHUNK):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
        except Exception as exc:  # noqa: BLE001 - a body that stops half-way is a failed fetch, and the half file is not kept
            dest.unlink(missing_ok=True)
            from src.monitoring.secret_scrub import record_text

            raise DiffUnavailable(record_text(exc)) from None
        finally:
            resp.close()
        return written

