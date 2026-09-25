"""The published per-lane budgets, and the arithmetic on each lane's measured bytes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1006 = a (ruled 2026-09-15), verbatim: «Settings → Storage shows each lane's size, its
budget, the honest arithmetic ("at your current rate this lane grows ~2 GB/month"), and
the disk left; budgets are published defaults sized for the reference VM.» Q1010 = a:
«Every budget is published and sized for the 2-core / 3.5 GB VM by default; power users
raise them; nothing silently assumes the maintainer's machine.» Q1011 = a: «The app reads
cores, RAM and free disk at boot (no network), proposes budgets from a published table,
and shows the reading.» The package docstring has listed this module since S1 as "the
published per-lane budgets and the measured-bytes arithmetic"; this is it.

THE TABLE IS A FILE, ``configs/lane_budgets.yml``, so that "published" is something a
reviewer can diff. This module is its only reader, and it refuses a malformed table BY
NAME rather than falling back to a default: a budget surface that quietly invented a
number would be the one thing Q1010 forbids.

IT CARRIES THE NUMBERS THAT WERE RULED AND NO OTHERS. One lane budget exists, Q707's
20 GB for Wikipedia. The S04-08 brief says per-lane numbers beyond the table's shape are
not the build's to decide, so the other rows hold ``None`` and a reason token, and
``tests/test_lane_budgets.py`` pins them there until a ruling moves one.

THE TWO CODE COPIES OF THE WIKIPEDIA NUMBER STAY, PINNED. ``src.scheduler.settings`` is
read on the boot path and imports nothing from ``src``; ``src.wiki.tiers`` runs its whole
tier decision with no file open. Making either parse YAML would add a boot-time read and
a failure mode to modules that have none, so ``WIKI_LANE_DEFAULT_BUDGET_GB`` and
``DEFAULT_TOTAL_BUDGET_GB`` keep their literals and the test asserts both equal this
table's row. The table is the published source; a change on either side alone fails CI.

GROWTH IS MEASURED FROM THE LANE'S OWN BYTES, OR NOT SHOWN. Each lane's size is recorded
at most hourly as a snapshot gauge (``lane_mib_<kind>``, beside ``wal_bytes`` in
``src.database.snapshots``), and the rate is the change between the first and last of
those readings inside a 30-day window, divided by the wall-clock time between them. Below
seven days of span there is no rate, and the reason says so -- a two-hour reading scaled
to a month is a guess with a number on it. It is a RATE, never a projection: nothing here
says when a disk fills or a budget runs out, because the next month is not the last one.

NOTHING HERE TOUCHES THE NETWORK. It stats files, reads one small YAML file, and reads
the snapshot rows the corpus already holds.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from src.versioned.lanes import KINDS, lane

_LOG = logging.getLogger("versioned.budget")

#: Where the table lives. Packaged with the app (``pyproject.toml`` ships ``configs/**/*.yml``).
TABLE_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "configs" / "lane_budgets.yml"

#: The only table version this reader understands. A newer file is refused rather than
#: half-read: a key this module does not know could be the one that changes a number.
TABLE_VERSION: Final[int] = 1

#: The corpus. Q1004 = a names it "``corpus.db`` (press, as today)"; on disk it is the
#: SQLite file ``DATABASE_URL`` points at. It is not a versioned lane, so it is named here
#: rather than added to :data:`src.versioned.lanes.KINDS`.
PRESS: Final[str] = "press"

#: Every lane the table must carry, in display order.
ALL_KINDS: Final[tuple[str, ...]] = (PRESS, *KINDS)

#: Why a row carries no number. CLOSED, like every token vocabulary in this package: the
#: UI translates each token, so an unknown one would reach the screen as a raw string.
REASONS: Final[tuple[str, ...]] = ("not_ruled",)

#: 1 GB here is 1024**3 bytes -- the unit ``src.wiki.tiers`` enforces the Wikipedia budget
#: in, and the unit every byte figure in the UI is formatted in.
BYTES_PER_GB: Final[int] = 1024**3
MIB: Final[int] = 1024**2

#: The growth window and the shortest span a rate is computed over. See the module
#: docstring; both travel in every growth payload so the UI can say them.
GROWTH_WINDOW_DAYS: Final[int] = 30
GROWTH_MIN_SPAN_DAYS: Final[int] = 7

#: Why a lane has no growth figure. The first four are about the lane; ``unreadable``
#: is the snapshot store failing to answer.
GROWTH_REASONS: Final[tuple[str, ...]] = ("absent", "unmeasurable", "no_history", "too_short", "unreadable")

_RULING_ID = re.compile(r"^[A-Z]{1,3}[0-9]{1,5}$")
_ROW_KEYS: Final[frozenset[str]] = frozenset({"budget_gb", "reason", "ruling", "setting"})


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #
class BudgetTableError(ValueError):
    """The table is missing, unreadable or malformed. Its own type so the storage report
    can say "the published table could not be read" as a named state beside every figure
    it can still measure, instead of failing the whole panel."""


@dataclass(frozen=True, slots=True)
class LaneBudget:
    """One lane's published row."""

    kind: str
    #: Whole GB, or ``None`` when no budget has been ruled for this lane.
    budget_gb: int | None
    #: A :data:`REASONS` token exactly when ``budget_gb`` is ``None``.
    reason: str | None
    #: The ruling the number comes from (``Q707``); ``None`` exactly when there is no number.
    ruling: str | None
    #: The ``SchedulerSettings`` field holding the operator's own value, when there is one.
    setting: str | None

    @property
    def budget_bytes(self) -> int | None:
        return None if self.budget_gb is None else self.budget_gb * BYTES_PER_GB


@dataclass(frozen=True, slots=True)
class BudgetTable:
    """The whole table, validated."""

    version: int
    reference_cores: int
    reference_ram_gb: float
    lanes: tuple[LaneBudget, ...]

    @property
    def reference_ram_bytes(self) -> int:
        return int(self.reference_ram_gb * BYTES_PER_GB)

    def row(self, kind: str) -> LaneBudget:
        for row in self.lanes:
            if row.kind == kind:
                return row
        raise BudgetTableError(f"the budget table has no row for lane {kind!r}")


def _settings_fields() -> frozenset[str]:
    from src.scheduler.settings import SchedulerSettings

    return frozenset(f.name for f in fields(SchedulerSettings))


def _positive_int(value: Any, what: str) -> int:
    # ``bool`` is an ``int`` in Python; ``true`` in a YAML file is a typo, not a budget.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BudgetTableError(f"{what} must be a positive whole number, got {value!r}")
    return value


def _row(kind: str, raw: Any, settings_fields: frozenset[str]) -> LaneBudget:
    if not isinstance(raw, dict):
        raise BudgetTableError(f"lane {kind!r}: a row must be a mapping, got {type(raw).__name__}")
    unknown = set(raw) - _ROW_KEYS
    if unknown:
        raise BudgetTableError(f"lane {kind!r}: unknown key(s) {sorted(unknown)}")
    if "budget_gb" not in raw:
        # Absent is not null: a row that forgot its number must not read as "not ruled".
        raise BudgetTableError(f"lane {kind!r}: budget_gb is required (null when not ruled)")
    budget = raw["budget_gb"]
    reason = raw.get("reason")
    ruling = raw.get("ruling")
    setting = raw.get("setting")
    if budget is None:
        if reason not in REASONS:
            raise BudgetTableError(
                f"lane {kind!r}: a row without a budget needs a reason from {REASONS}, got {reason!r}"
            )
        if ruling is not None:
            raise BudgetTableError(f"lane {kind!r}: a ruling names a number, and this row has none")
    else:
        budget = _positive_int(budget, f"lane {kind!r}: budget_gb")
        if reason is not None:
            raise BudgetTableError(f"lane {kind!r}: a row with a budget carries no reason token")
        if not isinstance(ruling, str) or not _RULING_ID.match(ruling):
            raise BudgetTableError(
                f"lane {kind!r}: a published number needs the ruling it comes from, got {ruling!r}"
            )
    # The type check first: a list here is unhashable, and the membership test would
    # raise a TypeError the storage report does not catch instead of this named refusal.
    if setting is not None and (not isinstance(setting, str) or setting not in settings_fields):
        raise BudgetTableError(f"lane {kind!r}: {setting!r} is not a scheduler setting")
    return LaneBudget(kind=kind, budget_gb=budget, reason=reason, ruling=ruling, setting=setting)


def load_table(path: Path | None = None) -> BudgetTable:
    """Read and validate the table, or raise :class:`BudgetTableError` naming what is wrong.

    Not cached: the file is a few hundred bytes, and an edited table should be what the
    next panel load shows rather than what this process happened to read first.
    """
    import yaml

    target = path or TABLE_PATH
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        # A file that is not UTF-8 raises a ValueError, not an OSError; both are "could
        # not be read", and neither may escape as a 500 from the storage panel.
        raise BudgetTableError(f"the budget table could not be read: {type(exc).__name__}") from exc
    except yaml.YAMLError as exc:
        raise BudgetTableError("the budget table is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise BudgetTableError("the budget table must be a mapping")
    unknown = set(raw) - {"version", "reference_machine", "lanes"}
    if unknown:
        raise BudgetTableError(f"unknown top-level key(s) {sorted(unknown)}")
    version = raw.get("version")
    if isinstance(version, bool) or version != TABLE_VERSION:
        raise BudgetTableError(f"this app reads table version {TABLE_VERSION}, got {version!r}")

    ref = raw.get("reference_machine")
    if not isinstance(ref, dict) or set(ref) != {"cores", "ram_gb"}:
        raise BudgetTableError("reference_machine must carry exactly cores and ram_gb")
    cores = _positive_int(ref["cores"], "reference_machine.cores")
    ram = ref["ram_gb"]
    # ``.nan`` and ``.inf`` are valid YAML floats that pass ``> 0`` (or fail it silently)
    # and then break the byte conversion; they are refused here, by name.
    if isinstance(ram, bool) or not isinstance(ram, (int, float)) or not math.isfinite(ram) or ram <= 0:
        raise BudgetTableError(f"reference_machine.ram_gb must be a positive number, got {ram!r}")

    lanes_raw = raw.get("lanes")
    if not isinstance(lanes_raw, dict):
        raise BudgetTableError("lanes must be a mapping of lane -> row")
    if set(lanes_raw) != set(ALL_KINDS):
        missing = sorted(set(ALL_KINDS) - set(lanes_raw))
        extra = sorted(set(lanes_raw) - set(ALL_KINDS))
        raise BudgetTableError(
            f"the lanes must be exactly {list(ALL_KINDS)}; missing {missing}, unknown {extra}"
        )
    known = _settings_fields()
    return BudgetTable(
        version=TABLE_VERSION,
        reference_cores=cores,
        reference_ram_gb=float(ram),
        lanes=tuple(_row(kind, lanes_raw[kind], known) for kind in ALL_KINDS),
    )


# --------------------------------------------------------------------------- #
# What each lane holds on disk
# --------------------------------------------------------------------------- #
def _file_with_sidecars(path: Path) -> int | None:
    """The file plus its ``-wal``/``-shm`` sidecars, or ``None`` when the file is absent.

    The same arithmetic as ``store.lane_file_bytes``, kept beside it rather than routed
    through it because the corpus is not a lane ``store`` can name.
    """
    if not path.is_file():
        return None
    total = 0
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        try:
            total += candidate.stat().st_size
        except OSError:
            continue
    return total


def corpus_path() -> Path | None:
    """The corpus file this process uses, or ``None`` when it is not a file-backed SQLite
    store (an in-memory test engine, or a non-SQLite ``DATABASE_URL``)."""
    from src.database.session import engine

    if engine.url.get_backend_name() != "sqlite":
        return None
    db = engine.url.database
    if not db or db == ":memory:":
        return None
    return Path(db)


def lane_bytes(kind: str) -> int | None:
    """Bytes the lane occupies on disk, sidecars included; ``None`` when there is nothing
    to measure. ``None`` and ``0`` stay different facts, as in ``store.lane_file_bytes``."""
    if kind == PRESS:
        path = corpus_path()
        return None if path is None else _file_with_sidecars(path)
    from src.versioned.store import lane_file_bytes

    return lane_file_bytes(kind)


def gauge_metric(kind: str) -> str:
    """The snapshot metric each lane's size is recorded under. MiB, not bytes: the
    ``stat_snapshots.value`` column is an ``Integer``, which PostgreSQL caps at 2**31 - 1
    (the Q1140 parity note), and a lane in bytes passes that at 2 GiB. In MiB the cap is
    two pebibytes; the resolution lost is one MiB per reading, stated in the method."""
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown lane {kind!r}; known lanes are {', '.join(ALL_KINDS)}")
    return f"lane_mib_{kind}"


def lane_mib(kind: str) -> int | None:
    """The gauge's reading: whole MiB, rounded down, or ``None`` (a gap, never a zero)."""
    b = lane_bytes(kind)
    return None if b is None else b // MIB


# --------------------------------------------------------------------------- #
# Growth
# --------------------------------------------------------------------------- #
def growth_from_series(
    series: list[dict[str, Any]],
    *,
    recording_began_at: str | None,
    min_span_days: int = GROWTH_MIN_SPAN_DAYS,
) -> dict[str, Any]:
    """The rate between the first and last reading of ``series`` (``[{"t": iso, "n": MiB}]``,
    oldest first), or the named reason there is none. Pure: the tests drive it directly."""
    base: dict[str, Any] = {
        "window_days": GROWTH_WINDOW_DAYS,
        "min_span_days": min_span_days,
        "samples": len(series),
        "recording_began_at": recording_began_at,
    }
    if not series:
        return {**base, "measured": False, "reason": "no_history"}
    first, last = series[0], series[-1]
    span_s = (datetime.fromisoformat(last["t"]) - datetime.fromisoformat(first["t"])).total_seconds()
    span_days = span_s / 86400
    base["span_days"] = round(span_days, 1)
    if len(series) < 2 or span_days < min_span_days:
        return {**base, "measured": False, "reason": "too_short"}
    delta = (int(last["n"]) - int(first["n"])) * MIB
    return {
        **base,
        "measured": True,
        "from": first["t"],
        "to": last["t"],
        "delta_bytes": delta,
        "per_30_days_bytes": int(round(delta * 30 / span_days)),
    }


def lane_growth(session, kind: str, *, size_state: str) -> dict[str, Any]:
    """Growth for one lane from its recorded gauge, or the reason there is none."""
    if size_state != "present":
        return {
            "window_days": GROWTH_WINDOW_DAYS,
            "min_span_days": GROWTH_MIN_SPAN_DAYS,
            "samples": 0,
            "measured": False,
            "reason": size_state,
        }
    from src.database.snapshots import metric_history

    try:
        history = metric_history(session, metric=gauge_metric(kind), days=GROWTH_WINDOW_DAYS)
    except Exception:  # noqa: BLE001 - a storage panel must not fail on a history read
        _LOG.warning("lane growth read failed for %s", kind, exc_info=True)
        return {
            "window_days": GROWTH_WINDOW_DAYS,
            "min_span_days": GROWTH_MIN_SPAN_DAYS,
            "samples": 0,
            "measured": False,
            "reason": "unreadable",
        }
    return growth_from_series(history.get("series") or [], recording_began_at=history.get("recording_began_at"))


# --------------------------------------------------------------------------- #
# The report Settings -> Storage draws
# --------------------------------------------------------------------------- #
def _device(path: Path | None) -> int | None:
    if path is None:
        return None
    target = path
    try:
        while not target.exists() and target.parent != target:
            target = target.parent
        return os.stat(target).st_dev
    except OSError:
        return None


def setting_bounds(setting: str | None) -> tuple[int, int] | None:
    """The whole-GB range the server accepts for a budget setting, or ``None``.

    A row whose setting has no bounds here is shown but NOT offered for editing: a
    number field with no range would accept what ``PUT /api/scheduler/config`` then
    refuses. ``tests/test_lane_budgets.py`` asserts every setting the table names has
    bounds, so that state is a test failure rather than a quietly read-only row.
    """
    if setting == "wiki_lane_budget_gb":
        from src.scheduler.settings import WIKI_LANE_BUDGET_GB_MAX, WIKI_LANE_BUDGET_GB_MIN

        return WIKI_LANE_BUDGET_GB_MIN, WIKI_LANE_BUDGET_GB_MAX
    return None


def _budget_block(row: LaneBudget | None, settings: Any, size: int | None) -> dict[str, Any]:
    if row is None:
        # The table could not be read: every key present and empty, so the UI's one
        # shape covers this state too, and the report's table_error says why.
        return {
            "published_gb": None, "reason": None, "ruling": None, "gb": None, "source": None,
            "used_share": None, "exhausted": None, "setting": None, "min_gb": None, "max_gb": None,
        }
    gb: int | None = row.budget_gb
    source: str | None = "published" if gb is not None else None
    if row.setting is not None:
        mine = getattr(settings, row.setting, None)
        if isinstance(mine, int) and not isinstance(mine, bool) and mine > 0:
            gb = mine
            # "yours" only when it DIFFERS: a stored copy of the default is still the
            # published number, and the settings store cannot tell the two apart anyway.
            source = "published" if mine == row.budget_gb else "yours"
    bounds = setting_bounds(row.setting)
    out: dict[str, Any] = {
        "published_gb": row.budget_gb,
        "reason": row.reason,
        "ruling": row.ruling,
        "gb": gb,
        "source": source,
        "used_share": None,
        "exhausted": None,
        # Editable only where the server's own bounds are known (see setting_bounds).
        "setting": row.setting if bounds is not None else None,
        "min_gb": bounds[0] if bounds is not None else None,
        "max_gb": bounds[1] if bounds is not None else None,
    }
    if gb is not None and size is not None:
        total = gb * BYTES_PER_GB
        # NOT rounded: a 120 KiB lane under 20 GB is a share of 0.0000057, which four
        # decimals turned into 0.0 -- and the panel then drew "0% used" for a lane that
        # holds something (found in the browser walk). The client formats it.
        out["used_share"] = size / total
        # The Wikipedia lane's own rule (``tiers.BudgetState.exhausted``): only a
        # measurement exhausts a budget.
        out["exhausted"] = size >= total
    return out


def storage_report(session) -> dict[str, Any]:
    """Everything Settings -> Storage draws, measured now. Never raises for a missing
    lane, an unreadable table or an unreadable history: each is a named state."""
    from src.config.hardware_reading import boot_reading, disk_bytes, read_hardware
    from src.paths import data_dir
    from src.scheduler.settings import load_settings

    table: BudgetTable | None
    table_error: str | None = None
    try:
        table = load_table()
    except BudgetTableError as exc:
        table, table_error = None, str(exc)

    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001 - the published rows still render without it
        _LOG.warning("storage report could not read the scheduler settings", exc_info=True)
        settings = None

    reading = boot_reading()
    if reading is None:
        # A process that never ran the lifespan (a test client, a script) reads now,
        # and says so rather than presenting the reading as a boot one.
        reading = read_hardware()
        reading["when"] = "now"

    folder = data_dir()
    free, total = disk_bytes(folder)
    folder_dev = _device(folder)

    lanes: list[dict[str, Any]] = []
    for kind in ALL_KINDS:
        size = lane_bytes(kind)
        if size is not None:
            size_state = "present"
        elif kind == PRESS:
            size_state = "unmeasurable" if corpus_path() is None else "absent"
        else:
            size_state = "absent"
        row = table.row(kind) if table is not None else None
        entry: dict[str, Any] = {
            "kind": kind,
            "implemented": True if kind == PRESS else lane(kind).implemented,
            "size_state": size_state,
            "bytes": size,
            "budget": _budget_block(row, settings, size),
            "growth": lane_growth(session, kind, size_state=size_state),
        }
        if kind == PRESS:
            # DATABASE_URL can put the corpus on another drive; then the disk line
            # below is not its disk, and the row says what is.
            path = corpus_path()
            dev = _device(path.parent if path is not None else None)
            if dev is not None and folder_dev is not None and dev != folder_dev:
                entry["other_volume_free_bytes"] = disk_bytes(path.parent)[0] if path else None
        lanes.append(entry)

    # The room the numeric budgets can still take, beside the room the drive has. Not a
    # projection: no rate enters it, only today's sizes and today's budgets.
    claimable: int | None = None
    budgeted = [e for e in lanes if e["budget"]["gb"] is not None]
    if budgeted:
        claimable = sum(max(0, e["budget"]["gb"] * BYTES_PER_GB - (e["bytes"] or 0)) for e in budgeted)
    # THREE STATES: fits, does not fit, or unknown -- never "fits" because the free space
    # could not be read, which would be a reassurance nobody measured.
    budgets_fit: bool | None = None
    if claimable is not None and free is not None:
        budgets_fit = claimable <= free

    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "table": None,
        "table_error": table_error,
        "reading": reading,
        "disk": {"free_bytes": free, "total_bytes": total},
        "lanes": lanes,
        "claimable_bytes": claimable,
        "budgets_fit": budgets_fit,
        "method": (
            "Sizes: each lane's database file with its -wal and -shm sidecars, read with stat. "
            "Budgets: configs/lane_budgets.yml, and your own value where the lane has a setting. "
            f"Growth: the lane's own size, recorded at most hourly in whole MiB; the change "
            f"between the first and last reading in the last {GROWTH_WINDOW_DAYS} days, over "
            f"the wall-clock time between them, shown only from {GROWTH_MIN_SPAN_DAYS} days of "
            "span. A rate, never a forecast. Disk left: shutil.disk_usage on the data folder. "
            "1 GB = 1024^3 bytes. Nothing is sent anywhere."
        ),
    }
    if table is not None:
        out["table"] = {
            "version": table.version,
            "reference_machine": {
                "cores": table.reference_cores,
                "ram_gb": table.reference_ram_gb,
                "ram_bytes": table.reference_ram_bytes,
            },
        }
    return out
