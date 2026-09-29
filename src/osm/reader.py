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
  (:class:`_AdaptiveLocations`). Time is the cost that remains: pure Python is one to two
  orders of magnitude slower than pyosmium (FROM MEMORY; the country row records the real
  seconds), which is why the lane still recommends the add-on for anything large.

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


def memory_budget_bytes() -> int | None:
    """How much the pure-Python path may hold in memory: a share of what is available now."""
    avail = available_memory_bytes()
    return None if avail is None else int(avail * MEMORY_SHARE)


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

    def __init__(self, workdir: Path, budget: int | None) -> None:
        self._workdir = workdir
        self.budget = budget
        self._max = None if budget is None else budget // DICT_BYTES_PER_NODE
        self._d: dict[int, tuple[float, float]] | None = {} if budget is not None else None
        self._disk: _SqliteLocations | None = None if budget is not None else _SqliteLocations(workdir)

    @property
    def spilled(self) -> bool:
        return self._disk is not None

    def set(self, node_id: int, lat: float, lon: float) -> None:
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
        return _AdaptiveLocations(workdir, memory_budget_bytes())


# --- pyosmium --------------------------------------------------------------- #
class _OsmiumLocations:
    """pyosmium's own sparse index: in memory for a small extract, a file for a large one.

    The file variant holds the coordinates of every node inside the country's bounding box
    (16 bytes each). It sits in the lane's work directory under the data directory and is
    deleted when the ingest ends, success or failure: node coordinates are public data, but
    WHICH box was cut says which country the operator chose.
    """

    def __init__(self, workdir: Path, *, on_disk: bool) -> None:
        import osmium.index

        self._file: Path | None = None
        self._map: Any
        if on_disk:
            workdir.mkdir(parents=True, exist_ok=True)
            self._file = workdir / "osm-locations.idx"
            self._map = osmium.index.create_map(f"sparse_file_array,{self._file}")
        else:
            self._map = osmium.index.create_map("sparse_mem_array")
        from osmium.osm import Location

        self._loc = Location

    def set(self, node_id: int, lat: float, lon: float) -> None:
        self._map.set(node_id, self._loc(lon, lat))

    def set_location(self, node_id: int, loc) -> None:
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
        return _OsmiumLocations(workdir, on_disk=size > self.ON_DISK_ABOVE)


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

