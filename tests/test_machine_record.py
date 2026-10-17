"""The manifest's ``machine`` block: the build, the libraries, the memory tier and what was set (R119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT MUST NOT REGRESS, one test each:

1. The record is in the manifest of EVERY build, including one whose members were declined or
   failed, and it is taken BEFORE the members run (a header is the machine as the build found it).
2. It names the switches that are set and never a value: the passphrase's own variable is one of
   them, and neither it nor any other value reaches the record.
3. Every reading is its own: one that cannot be taken says so with its reason and the others stand;
   a build never fails for want of the header.
4. It repeats nothing another member carries (the plan's redundancy rule): no hardware block, no
   transport, nothing the manifest's ``run.hardware`` holds.
5. It stays inside the budget the plan states for it (20 KB).
6. It says which XML driver feedparser uses in this process (``feed_xml``, R179), read WITHOUT importing
   the driver, and the section costs the archive no bytes: two sentences of the same block were
   shortened by what it adds.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import xml.sax.expatreader  # noqa: F401 - imported up front so a parse that falls through to expat finds it
import zipfile

import feedparser
import pytest

from src.api.diagnostics import bundle as B
from src.monitoring import machine_record as MR

SECRET = "pass-phrase \"with' quotes \\ and é"


@pytest.fixture(autouse=True)
def _no_gate(monkeypatch):
    monkeypatch.setattr(B, "ram_declined_reason", lambda *a, **k: None)


def _build(members, **kw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        B._write_all_diagnostics_zip(members, z, **kw)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        return json.loads(z.read("manifest.json")), set(z.namelist())


def test_the_record_has_its_sections_and_reads_the_libraries():
    block = MR.machine_block()
    assert block["version"] == MR.MACHINE_RECORD_VERSION
    for key in ("taken_at", "build", "process", "versions", "memory", "allocator", "environment", "feed_xml"):
        assert key in block, key
    versions = block["versions"]
    assert versions["python"].count(".") >= 1
    assert versions["sqlite"].count(".") >= 1
    # the other three are a string or a stated reason, never an empty value
    for lib in ("sqlcipher", "duckdb", "libc"):
        value = versions[lib]
        assert (isinstance(value, str) and value) or (isinstance(value, dict) and value.get("unavailable")), lib
    # the tier the process was resolved to, beside the one the machine gives now
    assert {"resolved", "now", "tier_differs"} <= set(block["memory"])
    assert block["build"]["code"] is not None
    assert block["process"]["pid"] > 0


def test_the_record_is_in_the_manifest_even_when_a_member_is_declined_or_fails(monkeypatch):
    def boom():
        raise RuntimeError("a member that fails")

    monkeypatch.setattr(B, "ram_declined_reason", lambda name, **k: "declined for the test" if name == "no.json" else None)
    manifest, names = _build([("ok.json", lambda: {"a": 1}), ("no.json", lambda: {"b": 2}), ("bad.json", boom)])
    assert "machine" in manifest
    assert manifest["machine"]["version"] == MR.MACHINE_RECORD_VERSION
    assert "no.json.declined.txt" in names and "bad.json.error.txt" in names


def test_the_record_is_taken_before_the_members_run(monkeypatch):
    order = []
    real = MR.machine_block

    def taken():
        order.append("record")
        return real()

    monkeypatch.setattr(MR, "machine_block", taken)
    _build([("a.json", lambda: order.append("member") or {"x": 1})])
    assert order[0] == "record", "the header is the machine as the build FOUND it"


def test_only_the_names_of_the_switches_are_read_never_a_value(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", SECRET)
    monkeypatch.setenv("OO_SOMETHING_ELSE", "a value that must not appear")
    monkeypatch.setenv("NOT_OURS", "not listed")
    block = MR.machine_block()
    env = block["environment"]
    assert "OO_DB_PASSPHRASE" in env["set_names"] and "OO_SOMETHING_ELSE" in env["set_names"]
    assert "NOT_OURS" not in env["set_names"]
    assert env["set_names"] == sorted(env["set_names"])
    text = json.dumps(block, ensure_ascii=False)
    assert "a value that must not appear" not in text
    for form in (SECRET, SECRET.replace("'", "''"), json.dumps(SECRET), repr(SECRET)):
        assert form not in text and form[1:-1] not in text
    manifest, _ = _build([("a.json", lambda: {"x": 1})])
    assert SECRET not in json.dumps(manifest, ensure_ascii=False)


def test_a_reading_that_cannot_be_taken_says_so_and_the_others_stand(monkeypatch):
    import src.config.memory_budget as budget

    def broken():
        raise OSError("the secret path /home/x must not be named")

    monkeypatch.setattr(budget, "reading_vs_now", broken)
    block = MR.machine_block()
    assert block["memory"]["reading_vs_now"] == {"unavailable": "OSError"}, "the type, never the text"
    assert isinstance(block["memory"]["available_now_mb"], float)
    assert block["versions"]["sqlite"] and block["allocator"]
    assert "/home/x" not in json.dumps(block)


def test_a_failure_of_the_whole_record_costs_the_build_nothing(monkeypatch):
    def explode(*a, **k):
        raise ValueError("everything is broken")

    monkeypatch.setattr(MR, "_build", explode)
    block = MR.machine_block()
    assert block == {"version": MR.MACHINE_RECORD_VERSION, "unavailable": "ValueError"}
    # and through the build's own wrapper, an import that fails is a reason as well
    monkeypatch.setattr(MR, "machine_block", explode)
    assert B._machine_record_block() == {"unavailable": "ValueError"}
    manifest, _ = _build([("a.json", lambda: {"x": 1})])
    assert manifest["machine"] == {"unavailable": "ValueError"}


def test_the_record_repeats_nothing_another_member_carries():
    block = MR.machine_block()
    flat = json.dumps(block)
    for held_elsewhere in ("cpu_model", "cpu_physical_cores", "swap_total_bytes", "disk_free_bytes", "transport"):
        assert held_elsewhere not in flat.replace(block["not_here"], ""), held_elsewhere
    assert "wiki-lane-history.json" in block["not_here"] and "run.hardware" in block["not_here"]


def test_the_record_stays_inside_its_budget(monkeypatch):
    for i in range(300):
        monkeypatch.setenv(f"OO_SWITCH_{i:03d}_WITH_A_FAIRLY_LONG_NAME", "v")
    assert len(json.dumps(MR.machine_block(), ensure_ascii=False).encode()) < 20 * 1024


# --------------------------------------------------------------------------
# feed_xml: which XML driver feedparser uses (R179)
# --------------------------------------------------------------------------
_FEED = (
    b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
    b"<link>https://example.org/</link><description>d</description>"
    b"<item><title>One</title><link>https://example.org/1</link><guid>1</guid></item>"
    b"</channel></rss>"
)

#: What a driver module written by the test does: leave a marker file when it is IMPORTED, and hand back
#: a real expat parser, so a feed parse that reaches it still reads the feed.
_DRIVER_SOURCE = (
    "import pathlib, xml.sax.expatreader\n"
    "pathlib.Path(__file__).with_name('imported.marker').write_text('imported')\n"
    "def create_parser():\n"
    "    return xml.sax.expatreader.create_parser()\n"
)


@pytest.fixture
def driver_dir(monkeypatch, tmp_path):
    """A directory first on ``sys.path`` holding a ``drv_libxml2.py`` that writes a marker when imported,
    with the name not in ``sys.modules`` and feedparser's list set to its default. The module is gone again
    afterwards, whatever the test did."""
    (tmp_path / "drv_libxml2.py").write_text(_DRIVER_SOURCE, encoding="utf-8")
    monkeypatch.delitem(sys.modules, "drv_libxml2", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(feedparser.api, "PREFERRED_XML_PARSERS", ["drv_libxml2"])
    yield tmp_path
    sys.modules.pop("drv_libxml2", None)


def test_a_driver_on_the_path_is_found_without_being_imported(driver_dir):
    got = MR._feed_xml()
    assert got == {"preferred": "drv_libxml2", "drv_libxml2": "found_not_loaded"}
    # red without the fix: a probe that imports the driver (``__import__``, ``make_parser``) leaves the marker
    assert not (driver_dir / "imported.marker").exists(), "the record imported the driver"
    assert "drv_libxml2" not in sys.modules


def test_a_feed_parse_that_reaches_the_driver_turns_found_into_loaded(driver_dir):
    assert MR._feed_xml()["drv_libxml2"] == "found_not_loaded"
    parsed = feedparser.parse(_FEED)
    assert (driver_dir / "imported.marker").exists(), "the parse did not reach the driver"
    assert [e.link for e in parsed.entries] == ["https://example.org/1"]
    assert MR._feed_xml() == {"preferred": "drv_libxml2", "drv_libxml2": "loaded"}


def test_no_driver_anywhere_reads_absent_and_a_parse_still_works(monkeypatch, tmp_path):
    """The control: the same parse with the name findable nowhere falls through to expat and the record says so
    (a ``None`` entry in ``sys.modules`` is no stand-in for that: ``make_parser`` re-raises for a name it finds there)."""
    monkeypatch.setattr(feedparser.api, "PREFERRED_XML_PARSERS", ["drv_libxml2"])
    monkeypatch.delitem(sys.modules, "drv_libxml2", raising=False)
    monkeypatch.setattr(sys, "path", [str(tmp_path)])  # an empty directory
    assert len(feedparser.parse(_FEED).entries) == 1
    assert MR._feed_xml() == {"preferred": "drv_libxml2", "drv_libxml2": "absent"}


def test_absent_when_the_import_path_holds_no_such_module(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "drv_libxml2", raising=False)
    monkeypatch.setattr(sys, "path", [str(tmp_path)])  # an empty directory: nothing named drv_libxml2 anywhere
    assert MR._feed_xml()["drv_libxml2"] == "absent"


def test_a_module_without_a_spec_in_sys_modules_reads_loaded_not_unavailable(monkeypatch):
    """``importlib.util.find_spec`` raises ``ValueError`` for a module placed in ``sys.modules`` without a spec,
    so the record reads ``sys.modules`` first (red without the order: ``unavailable``)."""
    monkeypatch.setitem(sys.modules, "drv_libxml2", types.ModuleType("drv_libxml2"))
    assert MR._feed_xml()["drv_libxml2"] == "loaded"


def test_preferred_is_feedparsers_own_list_as_it_stands(monkeypatch):
    monkeypatch.setattr(feedparser.api, "PREFERRED_XML_PARSERS", [])
    assert MR._feed_xml()["preferred"] == ""
    monkeypatch.setattr(feedparser.api, "PREFERRED_XML_PARSERS", ["drv_libxml2", "other"])
    assert MR._feed_xml()["preferred"] == "drv_libxml2,other"


def test_a_feedparser_that_cannot_be_read_is_a_reason_by_class_and_the_others_stand(monkeypatch):
    monkeypatch.setitem(sys.modules, "feedparser", None)  # ``import feedparser`` now raises
    got = MR._feed_xml()
    assert list(got) == ["unavailable"] and got["unavailable"].startswith("feedparser could not be read (")
    assert "Error" in got["unavailable"] and "/" not in got["unavailable"], "the class name, never a path or a message"
    block = MR.machine_block()
    assert block["feed_xml"] == got
    assert block["versions"]["sqlite"] and block["allocator"]


def test_the_section_is_in_the_manifest_of_every_build():
    manifest, _ = _build([("a.json", lambda: {"x": 1})])
    assert set(manifest["machine"]["feed_xml"]) == {"preferred", "drv_libxml2"}  # feedparser is a hard dependency
    assert manifest["machine"]["version"] == MR.MACHINE_RECORD_VERSION == 2


#: The bytes of the two sentences this section's neighbours carried on main before it, in the manifest's own
#: encoding: ``not_here`` (166) and ``environment.method`` (92). The section is paid for out of them, so the
#: UNCOMPRESSED manifest does not grow (the diagnostics part has no room to give). The compressed archive was
#: measured separately (DEFLATE level 9 of the block against main's: smaller in every shape listed below).
_FREED_BY_THE_SHORTENED_SENTENCES = 166 + 92


def _manifest_bytes(machine: dict) -> int:
    return len(json.dumps({"machine": machine}, ensure_ascii=False, indent=2).encode())


def test_the_driver_section_costs_the_uncompressed_manifest_no_bytes(monkeypatch):
    """The shapes are built from the code's OWN strings (the module's state names and feedparser's live list),
    so a longer value or a longer list breaks this, which a hand-typed literal could not.

    Outside the pin by design: the shape where ``find_spec`` itself fails (a reason by class, 128 B with
    ``ValueError``), which cannot arise while ``sys.modules`` is read first except in a race."""
    empty = _manifest_bytes({})
    preferred = ",".join(feedparser.api.PREFERRED_XML_PARSERS)
    shapes = [{"preferred": preferred, MR._FEED_DRIVER: state} for state in MR._DRIVER_STATES]
    with monkeypatch.context() as unreadable:
        unreadable.setitem(sys.modules, "feedparser", None)
        shapes.append(MR._feed_xml())  # the real output when feedparser cannot be imported
    assert len(shapes) == len(MR._DRIVER_STATES) + 1
    widest = max(_manifest_bytes({"feed_xml": shape}) - empty for shape in shapes)
    block = MR.machine_block()
    now = widest + len(block["not_here"].encode()) + len(block["environment"]["method"].encode())
    assert now <= _FREED_BY_THE_SHORTENED_SENTENCES, (
        f"the driver section (widest {widest} B) and the two sentences it was paid out of now take {now} B, "
        f"more than the {_FREED_BY_THE_SHORTENED_SENTENCES} B they took before it"
    )


def test_a_find_spec_that_fails_is_a_reason_by_class_never_a_message(monkeypatch):
    def broken(name):
        raise OSError("/home/x/secret-path must not be named")

    monkeypatch.delitem(sys.modules, "drv_libxml2", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", broken)
    got = MR._feed_xml()
    assert got["drv_libxml2"] == {"unavailable": "OSError"}
    assert "/home/x" not in json.dumps(got)


def test_a_none_entry_in_sys_modules_reads_absent_as_the_docstring_says(monkeypatch):
    """The known wrong reading, pinned so the docstring that admits it stays true: ``make_parser`` re-raises for
    a name it finds in ``sys.modules`` as ``None`` (the parse fails, it does not fall through to expat), while
    the record, which reads ``find_spec`` there, says ``absent``. Nothing in the app writes that entry."""
    monkeypatch.setitem(sys.modules, "drv_libxml2", None)
    assert MR._feed_xml()["drv_libxml2"] == "absent"
    with pytest.raises(ImportError):
        xml.sax.make_parser(["drv_libxml2"])
    assert "absent" in (MR._feed_xml.__doc__ or "") and "``None``" in (MR._feed_xml.__doc__ or "")
