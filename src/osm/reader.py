"""The reader seam: ``pyosmium`` with the ``[geo]`` extra, else pure Python, at any size.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q808 = a: «A ``[geo]`` extra with ``pyosmium`` for the extract pass; ``.osc`` diffs are XML and
stay pure Python; without the extra the lane says so and offers the small-country path.»

:func:`open_extract` chooses, and says which it chose (``Extract.name`` is recorded on the
country row):

* the ``[geo]`` extra importable -> :class:`PyosmiumExtract`, any size;
* not importable -> :class:`PythonExtract`, ALSO any size (R77, the maintainer's answer 15 of
  2026-09-29: «have the limit be adjusted based on the user hardware and available resources.
  But I'd rather not put limits on anything»). The fixed 256 MiB cap is gone. What bounded
  that path was memory, not the file: every node location inside the country's box is held
  while the ways are assembled, at :data:`DICT_BYTES_PER_NODE` in a Python dict. So the
  locations stay in memory while they fit :data:`MEMORY_SHARE` of what the system reports
  available when the ingest starts, and move to a work file past that
  (:class:`_AdaptiveLocations`). Time is the cost that remains: pure Python cut a 45 MB
  composite country 1.4 times slower than pyosmium (902 s against 642 s, where the database writes dominate;
  ``docs/audit/osm-real-extract-2026-10-15/README.md``), and a file whose cost is decoding was not measured, so the lane still
  recommends the add-on for anything large (the country row records the real seconds).

:class:`GeoExtraMissing` is raised only when pyosmium is ASKED for and not installed.

BOTH BACKENDS ANSWER THE SAME FIVE QUESTIONS, and ``tests/test_osm_ingest.py`` runs the whole
ingest through each on the fixture and compares the rows, so the two paths cannot quietly
diverge. The questions are shaped by the passes in ``src/osm/ingest.py``: the relations; some
ways by id; some nodes by id; then one pass in file order that stores every location inside a
bounding box and hands back only the TAGGED objects. That last one is where a continent's
billions of untagged vertices are spent, so each backend does it in its cheapest way.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from src.osm import pbf
from src.osm.pbf import Header, Member, Node, Relation, Way

class GeoExtraMissing(RuntimeError):
    """``pyosmium`` was asked for (``reader="pyosmium"`` or ``OO_OSM_READER``) and is not installed."""


def pyosmium_version() -> str | None:
    """The installed ``osmium`` package's version, or ``None`` when the extra is absent."""
    try:
        from importlib.metadata import version

        import osmium  # noqa: F401
    except ImportError:
        return None
    try:
        return version("osmium")
    except Exception:  # noqa: BLE001 - importable but unversioned is still installed
        return "unknown"


class LocationStore(Protocol):
    def set(self, node_id: int, lat: float, lon: float) -> None: ...
    def get(self, node_id: int) -> tuple[float, float] | None: ...
    def close(self) -> None: ...
    def describe(self) -> dict[str, Any]: ...


class Extract(Protocol):
    name: str
    path: Path

    def header(self) -> Header: ...
    def relations(self) -> Iterator[Relation]: ...
    def ways_by_id(self, ids: set[int]) -> Iterator[Way]: ...
    def nodes_by_id(self, ids: set[int]) -> Iterator[Node]: ...
    def scan(
        self, bbox: tuple[float, float, float, float], locations: LocationStore
    ) -> Iterator[Node | Way | Relation]: ...
    def location_store(self, workdir: Path) -> LocationStore: ...


# --- pure Python ------------------------------------------------------------ #
#: What one node location costs in a Python dict (int key -> (lat, lon) tuple), measured with
#: ``tracemalloc`` on a million random entries under CPython 3.13 (182 bytes, 2026-09-29),
#: rounded up. ``tests/test_osm_reader_memory.py`` re-measures it.
DICT_BYTES_PER_NODE = 190

#: The share of the memory the system reports AVAILABLE that the pure-Python path may fill
#: before it moves the node locations to a file (R77: the limit follows the machine).
MEMORY_SHARE = 0.5


def available_memory_bytes() -> int | None:
    """The memory the system reports available, or None when it cannot be read.

    psutil when installed (an optional extra), else Linux's ``/proc/meminfo``. None is a
    state, not a zero: the reader then keeps the locations in a file from the start.
    """
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:  # noqa: BLE001 - psutil is an optional extra; unreadable is a state
        pass
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


#: Where the kernel mounts the cgroup tree, and the file that says which cgroup THIS process is in. Parameters of
#: :func:`cgroup_reading` so a test can point at a tree of its own.
CGROUP_ROOT = "/sys/fs/cgroup"
PROC_CGROUP = "/proc/self/cgroup"

#: (source, directory under the root, limit file, usage file) for cgroup v2, then v1.
CGROUP_LAYOUTS: tuple[tuple[str, str, str, str], ...] = (
    ("cgroup_v2", "", "memory.max", "memory.current"),
    ("cgroup_v1", "memory", "memory.limit_in_bytes", "memory.usage_in_bytes"),
)

#: A limit at or above this is the kernel's "no limit" (v1 reports 2**63 less a page; v2 says ``max``).
_NO_LIMIT_AT = 1 << 60


def _own_cgroup_paths(proc_cgroup: str, notes: list[str]) -> tuple[dict[str, str], bool, bool]:
    """``({"cgroup_v2": "/a/b", "cgroup_v1": "/a"}, unreadable, was_read)``: where in each tree this process sits.

    A process in a child cgroup has its limit there or in an ancestor, NOT necessarily at the mount root (a systemd service with
    ``MemoryMax=``, a container started without its own cgroup namespace). A file that does not exist (no Linux cgroups at all) is
    the common case and means "the root is all there is"; one that exists and cannot be read is a limit we cannot see.
    """
    try:
        with open(proc_cgroup, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        notes.append(f"{proc_cgroup} is absent: only the cgroup mount root can be read")
        return {}, False, False
    except (OSError, ValueError) as exc:
        notes.append(f"{proc_cgroup} is unreadable ({type(exc).__name__}): this process's own cgroup is unknown")
        return {}, True, False
    paths: dict[str, str] = {}
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _hier, controllers, path = parts
        if controllers == "":  # the unified (v2) hierarchy: "0::/path"
            paths["cgroup_v2"] = path
        elif "memory" in controllers.split(","):
            paths["cgroup_v1"] = path
    return paths, False, True


def _read_int_file(path: str) -> tuple[str, int | None, str | None]:
    """``("ok", n, None)``, ``("absent", None, None)``, ``("no_limit", None, raw)`` or ``("bad", None, reason)``."""
    try:
        with open(path, encoding="ascii") as fh:
            raw = fh.read().strip()
    except FileNotFoundError:
        return "absent", None, None
    except (OSError, ValueError) as exc:
        return "bad", None, f"unreadable ({type(exc).__name__})"
    if raw == "max":
        return "no_limit", None, raw
    if not raw.isdigit():
        return "bad", None, "unparseable"  # an empty or garbled file is not "no limit"
    n = int(raw)
    if n >= _NO_LIMIT_AT:
        return "no_limit", None, raw[:20]
    return "ok", n, None


def cgroup_reading(
    root: str = CGROUP_ROOT, proc_cgroup: str = PROC_CGROUP, layouts: tuple[tuple[str, str, str, str], ...] = CGROUP_LAYOUTS
) -> dict[str, Any]:
    """What the cgroups this process is in say about a memory limit, and WHY when they say nothing.

    ``{"source", "limit_bytes", "headroom_bytes", "path", "unreadable", "notes": [...]}``. The process's own cgroup is found in
    ``/proc/self/cgroup`` and every ancestor up to the mount root is read; the TIGHTEST headroom (limit less usage) wins, since the
    kernel kills at the first limit reached. Absent, unreadable, unparseable and "no limit set" are different facts and each is named
    in ``notes``; when a limit or its usage exists and cannot be read, ``unreadable`` is True and ``headroom_bytes`` is None so
    that a caller takes its cautious branch, never "unlimited". (``headroom_bytes`` None with ``unreadable`` False is "no limit at any
    level that could be read"; ``own_dir_missing`` says the process's own cgroup directory is not in the mount, so a limit set there
    was not read, and :func:`memory_room` still bounds the room by ``MemAvailable``.) Usage includes page cache, which the kernel reclaims before it kills: the headroom is a LOWER bound.
    """
    notes: list[str] = []
    own, unreadable, proc_read = _own_cgroup_paths(proc_cgroup, notes)
    best: dict[str, Any] | None = None
    own_dir_missing = False
    for source, sub, limit_name, usage_name in layouts:
        mounted = os.path.isfile(os.path.join(root, "cgroup.controllers")) if not sub else os.path.isdir(os.path.join(root, sub))
        if source not in own and proc_read and mounted:
            notes.append(f"{source}: {proc_cgroup} has no line for it, so only the mount root was read")
        path = own.get(source, "/")
        parts = [p for p in path.split("/") if p and p != ".."]
        if parts and not os.path.isdir(os.path.join(root, sub, *parts)):
            # Docker on cgroup v1 without a cgroup namespace shows the container's host path here while the mount root IS the
            # container's cgroup, so this is legitimate; it is also what a tree we cannot see looks like. Named either way: the
            # limit at this level, if any, was not read, and the levels above it were.
            own_dir_missing = True
            notes.append(
                f"{source}: the cgroup directory {path!r} that {proc_cgroup} names is not in the mount, so a limit set there was "
                "not read; its ancestors and the mount root were"
            )
        # from the process's own cgroup up to the mount root
        for depth in range(len(parts), -1, -1):
            rel = "/".join(parts[:depth])
            base = os.path.join(root, sub, rel) if rel else os.path.join(root, sub)
            where = f"{source}:/{rel}"
            kind, limit, why = _read_int_file(os.path.join(base, limit_name))
            if kind == "absent":
                notes.append(f"{where}: {limit_name} is absent")
                continue
            if kind == "no_limit":
                notes.append(f"{where}: no limit is set ({why!r})")
                continue
            if kind == "bad" or limit is None:
                notes.append(f"{where}: {limit_name} is {why}")
                unreadable = True
                continue
            ukind, used, uwhy = _read_int_file(os.path.join(base, usage_name))
            if ukind != "ok" or used is None:
                notes.append(f"{where}: usage is {uwhy or ukind}, so this limit's headroom is unknown (never counted as free)")
                unreadable = True
                continue
            head = max(0, limit - used)
            if best is None or head < best["headroom_bytes"]:
                best = {"source": source, "limit_bytes": limit, "headroom_bytes": head, "path": f"/{rel}"}
    if unreadable:
        return {"source": None, "limit_bytes": None, "headroom_bytes": None, "path": None, "unreadable": True,
                "own_dir_missing": own_dir_missing, "notes": notes}
    if best is None:
        return {"source": None, "limit_bytes": None, "headroom_bytes": None, "path": None, "unreadable": False,
                "own_dir_missing": own_dir_missing, "notes": notes}
    return {**best, "unreadable": False, "own_dir_missing": own_dir_missing, "notes": notes}


def cgroup_headroom_bytes() -> int | None:
    """What a container's memory limit leaves free, or None when there is no limit to read (or it cannot be read).

    psutil and ``/proc/meminfo`` report the HOST's memory; inside a container with a lower limit
    the kernel kills the process at that limit, so the budget must not exceed it.
    """
    return cgroup_reading()["headroom_bytes"]


def memory_room() -> dict[str, Any]:
    """The memory this process may use, from the tighter of a cgroup's headroom and the system's available memory.

    ``{"room_bytes", "source": "cgroup_v1" | "cgroup_v2" | "mem_available" | None, "notes": [...]}``. ``room_bytes`` is None when
    NOTHING could be read AND when a cgroup limit exists that could not be (the notes say which): a caller then takes the cautious
    branch, never "unlimited".
    """
    cg = cgroup_reading()
    notes = list(cg["notes"])
    avail = available_memory_bytes()
    if avail is None:
        notes.append("MemAvailable is unreadable (psutil and /proc/meminfo both failed)")
    if cg.get("unreadable"):
        notes.append("a cgroup limit or its usage could not be read, so no room is claimed")
        return {"room_bytes": None, "source": None, "notes": notes}
    room, source = avail, ("mem_available" if avail is not None else None)
    head = cg["headroom_bytes"]
    if head is not None and (room is None or head < room):
        room, source = head, cg["source"]
    return {"room_bytes": room, "source": source, "notes": notes}


def memory_budget_bytes(room: dict[str, Any] | None = None) -> int | None:
    """How much the pure-Python path may hold in memory: a share of the room :func:`memory_room` reads,
    None (the file from the start) when the room cannot be read.

    The same reading the pyosmium guard uses, so the two readers take the same branch on one machine. (On main an unreadable
    cgroup usage fell through to ``MemAvailable`` alone; it now takes the file from the start, the cautious side.)
    """
    room_bytes = (room if room is not None else memory_room())["room_bytes"]
    if room_bytes is None:
        return None
    return int(room_bytes * MEMORY_SHARE)


class _SqliteLocations:
    """Node locations in a work file: no memory ceiling, slower than the dict.

    Like pyosmium's file index it sits in the lane's work directory and is deleted when the
    ingest ends, success or failure (which box was cut says which country was chosen).
    """

    _BATCH = 50_000

    def __init__(self, workdir: Path) -> None:
        import sqlite3

        workdir.mkdir(parents=True, exist_ok=True)
        self._file = workdir / "osm-locations.sqlite"
        self._file.unlink(missing_ok=True)
        self._con = sqlite3.connect(self._file)
        self._con.execute("PRAGMA journal_mode=OFF")
        self._con.execute("PRAGMA synchronous=OFF")
        self._con.execute("CREATE TABLE loc (id INTEGER PRIMARY KEY, lat REAL, lon REAL)")
        self._pending: list[tuple[int, float, float]] = []

    def set(self, node_id: int, lat: float, lon: float) -> None:
        self._pending.append((node_id, lat, lon))
        if len(self._pending) >= self._BATCH:
            self._flush()

    def set_many(self, items) -> None:
        self._con.executemany("INSERT OR REPLACE INTO loc VALUES (?, ?, ?)", items)

    def _flush(self) -> None:
        if self._pending:
            self.set_many(self._pending)
            self._pending = []

    def get(self, node_id: int) -> tuple[float, float] | None:
        self._flush()
        row = self._con.execute("SELECT lat, lon FROM loc WHERE id = ?", (node_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def close(self) -> None:
        try:
            self._con.close()
        finally:
            self._file.unlink(missing_ok=True)


class _AdaptiveLocations:
    """A dict while it fits the memory budget, then a work file (R77: no fixed file-size cap).

    The budget is read once, when the ingest starts. ``spilled`` says which one held the
    locations, so the ingest can report it; ``budget`` is None when the memory could not be
    read, and the file is then used from the first node.
    """

    def __init__(self, workdir: Path, budget: int | None, room: dict[str, Any] | None = None) -> None:
        self._workdir = workdir
        self.budget = budget
        self._room = room or {}
        self._max = None if budget is None else budget // DICT_BYTES_PER_NODE
        self._d: dict[int, tuple[float, float]] | None = {} if budget is not None else None
        self._disk: _SqliteLocations | None = None if budget is not None else _SqliteLocations(workdir)
        self._set_calls = 0

    @property
    def spilled(self) -> bool:
        return self._disk is not None

    def describe(self) -> dict[str, Any]:
        """Which store held the locations and what it cost, for the run record (no behaviour of its own)."""
        in_memory = self._d is not None
        return {
            "index": "python_dict" if in_memory else "sqlite_file",
            "rule": "memory budget unreadable: the file from the first node" if self.budget is None
            else f"a dict while it fits {MEMORY_SHARE:.0%} of the memory room read at the start (the tighter of the cgroup and "
            "MemAvailable), a file past that",
            "budget_bytes": self.budget,
            "room_bytes": self._room.get("room_bytes"),
            "room_source": self._room.get("source"),
            "room_notes": self._room.get("notes", []),
            "nodes_set": self._set_calls,
            # Stated, not sampled: DICT_BYTES_PER_NODE per held location (the dict's own cost; resident memory ran about 14% above it
            # on the 16x composite, see the audit README); the file holds none.
            "memory_bytes_settled": len(self._d) * DICT_BYTES_PER_NODE if self._d is not None else 0,
        }

    def set(self, node_id: int, lat: float, lon: float) -> None:
        self._set_calls += 1
        if self._d is not None:
            self._d[node_id] = (lat, lon)
            if self._max is not None and len(self._d) > self._max:
                self._disk = _SqliteLocations(self._workdir)
                self._disk.set_many((k, v[0], v[1]) for k, v in self._d.items())
                self._d = None
            return
        assert self._disk is not None
        self._disk.set(node_id, lat, lon)

    def get(self, node_id: int) -> tuple[float, float] | None:
        if self._d is not None:
            return self._d.get(node_id)
        assert self._disk is not None
        return self._disk.get(node_id)

    def close(self) -> None:
        if self._d is not None:
            self._d.clear()
        if self._disk is not None:
            self._disk.close()


class PythonExtract:
    name = "python"

    def __init__(self, path: Path) -> None:
        self.path = path

    def header(self) -> Header:
        return pbf.read_header(self.path)

    def relations(self) -> Iterator[Relation]:
        for r in pbf.iter_elements(self.path, nodes=False, ways=False):
            if isinstance(r, Relation) and r.tags:
                yield r

    def ways_by_id(self, ids: set[int]) -> Iterator[Way]:
        for w in pbf.iter_elements(self.path, nodes=False, relations=False):
            if isinstance(w, Way) and w.id in ids:
                yield w

    def nodes_by_id(self, ids: set[int]) -> Iterator[Node]:
        for n in pbf.iter_elements(self.path, ways=False, relations=False):
            if isinstance(n, Node) and n.id in ids:
                yield n

    def scan(self, bbox, locations) -> Iterator[Node | Way | Relation]:
        min_lat, min_lon, max_lat, max_lon = bbox
        for el in pbf.iter_elements(self.path):
            if isinstance(el, Node):
                if min_lat <= el.lat <= max_lat and min_lon <= el.lon <= max_lon:
                    locations.set(el.id, el.lat, el.lon)
                    if el.tags:
                        yield el
            elif el.tags:
                yield el

    def location_store(self, workdir: Path) -> LocationStore:
        room = memory_room()
        return _AdaptiveLocations(workdir, memory_budget_bytes(room), room)


# --- pyosmium --------------------------------------------------------------- #
#: The in-memory location index is one vector that grows by doubling its capacity, and while it reallocates the process holds the old
#: buffer and the new one with every entry copied: TWICE the settled bytes at each doubling (``location_probe.py`` measured 32.0
#: bytes a location right after a doubling, N=4,194,305, and 1,024 MiB at 2**25 entries = 2 x 512 MiB; the 1.68 read from the
#: 40 million point sat between two doublings and under-stated it). The guard compares 2 x settled, the envelope of every doubling.
LOCATION_GROWTH_PEAK_FACTOR = 2.0

#: What the rest of the cut held besides the locations on the largest composite run (2.88 million objects, 3.5 GiB envelope): 823 MiB
#: peak less 282 MiB of settled locations (18.49 million x 16 B) is 541 MiB, rounded up to 600 MiB. It is the room the guard leaves
#: for everything that is not the index (Python heap, SQLite, batches, the kept ids); at a hundred times that size it will be larger,
#: and the guard then errs toward stopping too late, which the run record's ``location_index`` figures show.
LOCATION_REST_OF_CUT_BYTES = 600 * 1024 * 1024

#: The fewest locations worth keeping in memory under the guard: below a million (about 2.5 MB of extract at the 16x composite's
#: 0.404 locations per file byte) the guard would stop an ordinary city extract on a room it should not have been chosen for, so a
#: room that cannot hold this many takes the file index up front, with the reason in the record.
LOCATION_MIN_IN_MEMORY = 1_000_000


def location_capacity(room_bytes: int, entry_bytes: int = 16) -> int:
    """How many locations the in-memory index may take in ``room_bytes`` before its doubling peak plus the rest of the cut pass it."""
    return int(max(0, room_bytes - LOCATION_REST_OF_CUT_BYTES) / LOCATION_GROWTH_PEAK_FACTOR / entry_bytes)


#: ``OO_OSM_LOCATION_INDEX=file`` keeps the locations in a work file whatever the extract's size: the way out of a
#: :class:`LocationIndexTooLarge` stop, and a way to compare the two indexes on one file.
LOCATION_INDEX_ENV = "OO_OSM_LOCATION_INDEX"


def location_index_choice() -> str | None:
    """``"file"`` when :data:`LOCATION_INDEX_ENV` asks for the file index, None when it is unset or says ``auto``.

    Anything else is a typo and is refused by name: an operator who typed ``OO_OSM_LOCATION_INDEX=disk`` to get out of a
    :class:`LocationIndexTooLarge` stop must not get the in-memory index again without being told.
    """
    raw = os.environ.get(LOCATION_INDEX_ENV, "").strip().lower()
    if raw in ("", "auto"):
        return None
    if raw == "file":
        return "file"
    raise ValueError(f"{LOCATION_INDEX_ENV} must be 'file' or 'auto' (or unset), not {raw[:20]!r}")


class LocationIndexTooLarge(RuntimeError):
    """The in-memory node-location index would pass the memory this process has; the scan stopped before the kernel could kill it.

    The extract is under the file-size threshold that picks the in-memory index and denser in nodes than that rule assumes. The
    message carries the figures (they are numbers, not paths or secrets) so the run record states what was measured.
    """


class _OsmiumLocations:
    """pyosmium's own sparse index: in memory for a small extract, a file for a large one.

    The file variant holds the coordinates of every node inside the country's bounding box
    (16 bytes each). It sits in the lane's work directory under the data directory and is
    deleted when the ingest ends, success or failure: node coordinates are public data, but
    WHICH box was cut says which country the operator chose.
    """

    #: What libosmium's sparse index holds per location: an 8-byte id and an 8-byte location, 16.0 bytes each once settled
    #: (``docs/audit/osm-real-extract-2026-10-15/location_probe.py``). The in-memory variant is one growing vector, and while it
    #: grows the process briefly holds the old buffer and the new one (2.0 times the settled figure at each doubling,
    #: see ``LOCATION_GROWTH_PEAK_FACTOR``), so the run record's figure is the SETTLED bytes, arithmetic from this constant, not a peak.
    ENTRY_BYTES = 16

    def __init__(
        self, workdir: Path, *, on_disk: bool, extract_bytes: int | None = None, rule: str | None = None,
        room: dict[str, Any] | None = None,
    ) -> None:
        import osmium.index

        self._file: Path | None = None
        self._map: Any
        self._on_disk = on_disk
        self._extract_bytes = extract_bytes
        self._rule = rule
        self._room = room or {}
        self._set_calls = 0
        #: The most locations the in-memory index may take before its growth peak plus the rest of the cut passes the room read at
        #: the start; None when it is a file or the room was not read (then the cautious file branch was already taken).
        self._max_locations: int | None = None
        room_bytes = self._room.get("room_bytes")
        if not on_disk and room_bytes is not None:
            self._max_locations = location_capacity(room_bytes, self.ENTRY_BYTES)
        if on_disk:
            workdir.mkdir(parents=True, exist_ok=True)
            self._file = workdir / "osm-locations.idx"
            self._map = osmium.index.create_map(f"sparse_file_array,{self._file}")
        else:
            self._map = osmium.index.create_map("sparse_mem_array")
        from osmium.osm import Location

        self._loc = Location

    def _stop(self) -> None:
        stored = self._set_calls - 1  # the location that tripped the check was never stored
        held = stored * self.ENTRY_BYTES
        raise LocationIndexTooLarge(
            f"the node-location index held {stored} locations ({held} bytes settled); with its doubling peak "
            f"({LOCATION_GROWTH_PEAK_FACTOR}x, measured) and the rest of the cut ({LOCATION_REST_OF_CUT_BYTES} bytes, measured) "
            f"that passes the {self._room.get('room_bytes')} bytes this process has ({self._room.get('source')}); stopped before "
            f"the kernel could kill it. This extract ({self._extract_bytes} bytes) is denser in nodes than the file-size rule "
            f"assumes: set {LOCATION_INDEX_ENV}=file to keep the locations in a work file"
        )

    def describe(self) -> dict[str, Any]:
        """Which index was chosen, by which rule, and the bytes it holds (no behaviour of its own)."""
        held = self._set_calls * self.ENTRY_BYTES
        return {
            "index": "sparse_file_array" if self._on_disk else "sparse_mem_array",
            "rule": self._rule,
            "extract_bytes": self._extract_bytes,
            "nodes_set": self._set_calls,
            "entry_bytes": self.ENTRY_BYTES,
            "memory_bytes_settled": 0 if self._on_disk else held,
            "file_bytes_settled": held if self._on_disk else 0,
            # The guard's inputs, read once when the index was made: where the room came from, what it was, and how many
            # locations the in-memory index could take before its measured growth peak plus the rest of the cut passed it.
            "room_bytes": self._room.get("room_bytes"),
            "room_source": self._room.get("source"),
            "room_notes": self._room.get("notes", []),
            "max_locations_in_memory": self._max_locations,
        }

    def set(self, node_id: int, lat: float, lon: float) -> None:
        self._set_calls += 1
        if self._max_locations is not None and self._set_calls > self._max_locations:
            self._stop()
        self._map.set(node_id, self._loc(lon, lat))

    def set_location(self, node_id: int, loc) -> None:
        self._set_calls += 1
        if self._max_locations is not None and self._set_calls > self._max_locations:
            self._stop()
        self._map.set(node_id, loc)

    def get(self, node_id: int) -> tuple[float, float] | None:
        try:
            loc = self._map.get(node_id)
        except KeyError:
            return None
        return (round(loc.lat, 7), round(loc.lon, 7))

    def close(self) -> None:
        try:
            self._map.clear()
        finally:
            self._map = None
            if self._file is not None:
                self._file.unlink(missing_ok=True)


def _tags(o) -> dict[str, str]:
    return {t.k: t.v for t in o.tags}


def _meta(o):
    ts = o.timestamp
    # pyosmium hands back 1970-01-01 for an object with no timestamp; absent is absent.
    return (o.version or None, ts if ts is not None and ts.timestamp() > 0 else None)


_OSMIUM_MEMBER = {"n": "n", "w": "w", "r": "r"}


def _rel(o) -> Relation:
    v, ts = _meta(o)
    return Relation(
        o.id,
        v,
        ts,
        _tags(o),
        tuple(Member(_OSMIUM_MEMBER.get(m.type, "?"), m.ref, m.role) for m in o.members),
    )


def _way(o) -> Way:
    v, ts = _meta(o)
    return Way(o.id, v, ts, _tags(o), tuple(n.ref for n in o.nodes))


def _node(o) -> Node:
    v, ts = _meta(o)
    loc = o.location
    return Node(o.id, v, ts, _tags(o), round(loc.lat, 7), round(loc.lon, 7))


class PyosmiumExtract:
    name = "pyosmium"

    #: Above this, the location index goes to a file rather than RAM.
    ON_DISK_ABOVE = 512 * 1024 * 1024

    def __init__(self, path: Path) -> None:
        self.path = path

    def header(self) -> Header:
        import osmium

        hdr = Header(writing_program=None)
        reader = osmium.io.Reader(str(self.path), osmium.osm.osm_entity_bits.NOTHING)
        try:
            h = reader.header()
            stamp = h.get("osmosis_replication_timestamp") or h.get("timestamp")
            if stamp:
                from datetime import datetime

                try:
                    hdr.replication_timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    hdr.replication_timestamp = None
            seq = h.get("osmosis_replication_sequence_number")
            hdr.replication_sequence = int(seq) if seq and seq.isdigit() else None
            hdr.writing_program = h.get("generator") or None
            box = h.box()
            if box.valid():
                hdr.bbox = (box.bottom_left.lon, box.bottom_left.lat, box.top_right.lon, box.top_right.lat)
        finally:
            reader.close()
        return hdr

    def relations(self) -> Iterator[Relation]:
        import osmium

        fp = osmium.FileProcessor(str(self.path), osmium.osm.RELATION).with_filter(osmium.filter.EmptyTagFilter())
        for o in fp:
            yield _rel(o)

    def ways_by_id(self, ids: set[int]) -> Iterator[Way]:
        import osmium

        if not ids:
            return
        fp = osmium.FileProcessor(str(self.path), osmium.osm.WAY).with_filter(osmium.filter.IdFilter(ids))
        for o in fp:
            yield _way(o)

    def nodes_by_id(self, ids: set[int]) -> Iterator[Node]:
        import osmium

        if not ids:
            return
        fp = osmium.FileProcessor(str(self.path), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(ids))
        for o in fp:
            yield _node(o)

    def scan(self, bbox, locations) -> Iterator[Node | Way | Relation]:
        import osmium

        min_lat, min_lon, max_lat, max_lon = bbox
        set_loc = getattr(locations, "set_location", None)
        o: Any
        for o in osmium.FileProcessor(str(self.path)):
            if o.is_node():
                loc = o.location
                if not loc.valid():
                    continue
                lat = loc.lat
                lon = loc.lon
                if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                    if set_loc is not None:
                        set_loc(o.id, loc)
                    else:
                        locations.set(o.id, lat, lon)
                    if o.tags:
                        yield _node(o)
            elif o.tags:
                yield _way(o) if o.is_way() else _rel(o)

    def location_store(self, workdir: Path) -> LocationStore:
        size = self.path.stat().st_size
        big = f"the extract file is above {self.ON_DISK_ABOVE} bytes (the file's size, not its node count)"
        if location_index_choice() == "file":
            return _OsmiumLocations(workdir, on_disk=True, extract_bytes=size, rule=f"{LOCATION_INDEX_ENV}=file asked for the file index")
        if size > self.ON_DISK_ABOVE:
            return _OsmiumLocations(workdir, on_disk=True, extract_bytes=size, rule=big)
        room = memory_room()
        if room["room_bytes"] is not None and location_capacity(room["room_bytes"]) < LOCATION_MIN_IN_MEMORY:
            return _OsmiumLocations(
                workdir, on_disk=True, extract_bytes=size, room=room,
                rule=f"the memory room ({room['room_bytes']} bytes, {room['source']}) holds fewer than {LOCATION_MIN_IN_MEMORY} locations "
                f"once the doubling peak and the rest of the cut are counted: the file index, not an in-memory one that would stop on any real extract",
            )
        if room["room_bytes"] is None:
            # Nothing could be read: the cautious branch, as the pure-Python path takes (a limit that cannot be read is not no limit).
            why = "; ".join(room["notes"]) or "no reading"
            return _OsmiumLocations(
                workdir, on_disk=True, extract_bytes=size, room=room,
                rule=f"the memory this process may use could not be read ({why}): the file index, never an unlimited in-memory one",
            )
        return _OsmiumLocations(
            workdir, on_disk=False, extract_bytes=size, room=room,
            rule=f"the extract file is at or below {self.ON_DISK_ABOVE} bytes (the file's size, not its node count) and its "
            "growth peak is checked against the memory this process has while the scan runs",
        )


def open_extract(path: str | Path, *, reader: str | None = None) -> Extract:
    """The backend for ``path``. ``reader`` forces ``"pyosmium"`` or ``"python"`` (tests, CLI).

    ``OO_OSM_READER`` does the same from the environment, so an operator can compare the two
    on a small file without editing code.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"no extract at {p.name}")
    choice = reader or os.environ.get("OO_OSM_READER") or None
    have_osmium = pyosmium_version() is not None
    if choice == "pyosmium" or (choice is None and have_osmium):
        if not have_osmium:
            raise GeoExtraMissing("the pyosmium reader was requested but the [geo] extra is not installed")
        return PyosmiumExtract(p)
    return PythonExtract(p)

