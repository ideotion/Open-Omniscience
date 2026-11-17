"""R737 (row 119): the thesaurus build tool and the check the app runs before it uses a built thesaurus.

Offline fixtures only. What is pinned is mostly refusal: the same source gives the same bytes; a file is used only
when its format and SHA-256 hold, and every other state is said with its reason; the fetch is refused without
--online, off the publisher's hosts, and on an unnamed transport; the --source path opens no connection.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import zipfile
from pathlib import Path

import pytest

from src.catalog import thesaurus_store as ts

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "data" / "skos" / "mini_scheme.rdf"
_SPEC = importlib.util.spec_from_file_location("thesaurus_build", ROOT / "scripts" / "thesaurus_build.py")
tb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tb)


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the offline build must never open a connection")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)


def _build(out: Path, source: Path = MINI, **kw):
    args = {"vintage": "2026-11-01", "license": "CC0 (fixture)", "upstream": "fixture", "languages": None, **kw}
    return tb.build("eurovoc", source, out, **args)


# --- the build ------------------------------------------------------------------------------------------------------


def test_the_same_source_gives_the_same_bytes_and_hash(tmp_path, no_network):
    s1 = _build(tmp_path / "a")
    s2 = _build(tmp_path / "b")
    a, b = (tmp_path / "a" / "eurovoc.json").read_bytes(), (tmp_path / "b" / "eurovoc.json").read_bytes()
    assert a == b and s1["output"]["sha256"] == s2["output"]["sha256"] == hashlib.sha256(a).hexdigest()
    assert a.endswith(b"\n") and a.count(b"\n") == 1, "one canonical line"
    doc = json.loads(a)
    assert doc["format"] == ts.FORMAT_VERSION and doc["source_sha256"] == hashlib.sha256(MINI.read_bytes()).hexdigest()


def test_list_order_in_the_source_does_not_change_the_output(tmp_path):
    art = {"scheme": "eurovoc", "vintage": "v", "license": "l", "upstream": "u", "languages": ["en"], "n_concepts": 1,
           "concepts": {"x": {"pref": {"en": "X"}, "alt": {"en": ["b", "a"]}, "broader": ["z", "y"]}},
           "gaps": [{"kind": "b", "detail": "2"}, {"kind": "a", "detail": "1"}]}
    flipped = json.loads(json.dumps(art))
    flipped["concepts"]["x"]["alt"]["en"].reverse()
    flipped["concepts"]["x"]["broader"].reverse()
    flipped["gaps"].reverse()
    one = ts.canonical_bytes(tb.canonical_artifact(art, source_sha256="s"))
    two = ts.canonical_bytes(tb.canonical_artifact(flipped, source_sha256="s"))
    assert one == two


def test_the_summary_is_small_counts_and_hashes_with_no_label_and_no_path(tmp_path):
    s = _build(tmp_path / "out", languages=("en",))
    raw = (tmp_path / "out" / "eurovoc.summary.json").read_bytes()
    assert len(raw) < tb.SUMMARY_MAX_BYTES < 200 * 1024
    assert json.loads(raw) == s
    assert s["tool_version"] == ts.BUILD_TOOL_VERSION and s["format"] == ts.FORMAT_VERSION
    assert "name" not in s["source"] and MINI.name not in raw.decode("utf-8") and str(tmp_path) not in raw.decode("utf-8"), \
        "no file name and no path: the hash identifies the source"
    assert s["source"]["kind"] == "xml" and s["source"]["member_sha256"] is None
    built = json.loads((tmp_path / "out" / "eurovoc.json").read_text(encoding="utf-8"))
    for c in built["concepts"].values():
        for label in c["pref"].values():
            assert label not in raw.decode("utf-8"), "the summary carries counts, never a label"
    assert s["counts"]["concepts_kept"] == built["n_concepts"] and s["counts"]["concepts_seen"] >= built["n_concepts"]


def test_a_zip_source_is_read_and_a_zip_with_several_xml_members_needs_one_named(tmp_path):
    one = tmp_path / "one.zip"
    with zipfile.ZipFile(one, "w") as zf:
        zf.write(MINI, "eurovoc.rdf")
        zf.writestr("readme.txt", "x")
    s = _build(tmp_path / "z", source=one)
    assert s["source"]["member"] == "eurovoc.rdf" and s["source"]["kind"] == "zip"
    assert s["source"]["member_sha256"] == hashlib.sha256(MINI.read_bytes()).hexdigest(), "the member's own bytes"
    assert (tmp_path / "z" / "eurovoc.json").stat().st_mode & 0o777 == 0o644, "readable by the app as another user"
    two = tmp_path / "two.zip"
    with zipfile.ZipFile(two, "w") as zf:
        zf.write(MINI, "a.rdf")
        zf.write(MINI, "b.rdf")
    with pytest.raises(tb.BuildRefused, match="--member"):
        _build(tmp_path / "y", source=two)
    assert _build(tmp_path / "y", source=two, member="b.rdf")["source"]["member"] == "b.rdf"


def test_a_member_larger_than_the_cap_is_refused_whatever_its_header_says(tmp_path, monkeypatch):
    z = tmp_path / "big.zip"
    with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(MINI, "eurovoc.rdf")
    with pytest.raises(tb.BuildRefused, match="max-mb"):
        _build(tmp_path / "o", source=z, max_bytes=100)
    # The streaming cap, apart from the declared size: a member whose header understates it.
    with open(MINI, "rb") as fh, pytest.raises(tb._TooLarge):
        tb._Capped(fh, 100, "m").read(10_000)
    # And through the build: a header that understates the member is caught by the ZIP reader's own size check
    # (BadZipFile, named as an unreadable source), before _Capped's bound is ever reached; never a quiet over-read.
    real = tb._pick_member

    def lying(zf, member):
        info = real(zf, member)
        info.file_size = 1
        return info

    monkeypatch.setattr(tb, "_pick_member", lying)
    from src.catalog import skos

    with pytest.raises(skos.SkosError, match="BadZipFile"):
        _build(tmp_path / "o2", source=z, max_bytes=100)
    assert not (tmp_path / "o2").exists()


# --- the check the app runs ----------------------------------------------------------------------------------------


def test_every_state_is_said_with_its_reason_and_only_ok_is_loaded(tmp_path):
    d = tmp_path / "th"
    st = ts.thesaurus_status("eurovoc", d)
    assert st["state"] == "missing" and "thesaurus_build.py" in st["reason"]
    _build(d)
    st = ts.thesaurus_status("eurovoc", d)
    assert st["state"] == "ok" and st["vintage"] == "2026-11-01" and st["n_concepts"] >= 1
    art, st2 = ts.load_thesaurus("eurovoc", d)
    assert art is not None and st2["state"] == "ok" and art["scheme"] == "eurovoc"

    path, spath = d / "eurovoc.json", d / "eurovoc.summary.json"
    good, summary = path.read_bytes(), spath.read_bytes()
    tick = [path.stat().st_mtime_ns]

    def put(data: bytes) -> None:  # a new mtime each write: the status memo is keyed on (size, mtime), as a real edit moves it
        path.write_bytes(data)
        tick[0] += 1_000_000_000
        os.utime(path, ns=(tick[0], tick[0]))

    doc = json.loads(good)
    doc["vintage"] = "edited"
    put(ts.canonical_bytes(doc))
    st = ts.thesaurus_status("eurovoc", d)
    assert st["state"] == "hash_mismatch" and "SHA-256" in st["reason"]
    assert ts.load_thesaurus("eurovoc", d)[0] is None

    put(good)
    spath.unlink()
    st = ts.thesaurus_status("eurovoc", d)
    assert st["state"] == "unverified" and ts.load_thesaurus("eurovoc", d)[0] is None

    spath.write_bytes(summary)
    doc = json.loads(good)
    doc["format"] = 0
    put(ts.canonical_bytes(doc))
    assert ts.thesaurus_status("eurovoc", d)["state"] == "old_format"

    put(b"{not json")
    assert ts.thesaurus_status("eurovoc", d)["state"] == "unreadable"
    put(ts.canonical_bytes({"scheme": "agrovoc", "concepts": {}}))
    assert ts.thesaurus_status("eurovoc", d)["state"] == "unreadable", "another scheme's file is not this one"

    put(good)
    assert ts.thesaurus_status("eurovoc", d)["state"] == "ok"
    assert {s["state"] for s in ts.statuses(d)} == {"ok", "missing"}


def test_the_status_never_calls_a_release_old():
    import re

    src = (ROOT / "src" / "catalog" / "thesaurus_store.py").read_text(encoding="utf-8")
    code = src.split('"""', 2)[2]  # past the module docstring, which explains why
    assert not re.search(r"\bstale\b|max_age|timedelta", code)


# --- the fetch -----------------------------------------------------------------------------------------------------


def test_fetch_is_refused_without_online_and_off_the_publishers_hosts(capsys, tmp_path, no_network):
    common = ["--vintage", "v", "--license", "l", "--out-dir", str(tmp_path)]
    assert tb.main(["--fetch-url", "https://op.europa.eu/x.zip", *common]) == 2
    assert "--online" in capsys.readouterr().err
    for bad in ("https://evil.example/x.zip", "http://op.europa.eu/x.zip", "https://user@op.europa.eu/x",
                "https://op.europa.eu:8443/x", "https://op.europa.eu.evil.example/x", "https://evil.example\\@op.europa.eu/x"):
        assert tb.main(["--fetch-url", bad, "--online", "--clearnet", *common]) == 2, bad
        assert "refusing the fetch URL" in capsys.readouterr().err
    assert tb.main(["--scheme", "agrovoc", "--fetch-url", "https://op.europa.eu/x", "--online", *common]) == 2
    assert "--source" in capsys.readouterr().err
    assert not any(tmp_path.iterdir()), "a refusal writes nothing"


def test_fetch_refuses_an_unnamed_transport_unless_clearnet_is_said(monkeypatch, capsys, tmp_path, no_network):
    import src.entities.gazetteer_build as G

    monkeypatch.setattr(G, "transport_state", lambda: {"mode": "standard", "protected": False, "explicit": False})
    assert tb.main(["--fetch-url", "https://op.europa.eu/x.zip", "--online", "--vintage", "v", "--license", "l",
                    "--out-dir", str(tmp_path)]) == 2
    assert "--clearnet" in capsys.readouterr().err


class _Resp:
    def __init__(self, url, body=b"", status=200, headers=None):
        self.url, self._body, self.status_code, self.headers = url, body, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]


class _Session:
    def __init__(self, resp):
        self.resp, self.asked = resp, []

    def get(self, url, **kw):
        self.asked.append((url, kw))
        return self.resp


def test_a_download_is_held_to_the_hosts_after_redirects_and_to_the_size_cap(tmp_path):
    hosts = tb.PUBLISHER_HOSTS["eurovoc"]
    body = MINI.read_bytes()
    s = _Session(_Resp("https://publications.europa.eu/resource/cellar/x", body))
    assert tb.fetch_source("https://op.europa.eu/x", hosts, tmp_path / "eurovoc.source", max_bytes=1 << 20, session=s) \
        == "publications.europa.eu"
    assert (tmp_path / "eurovoc.source").read_bytes() == body and s.asked[0][1]["stream"] is True

    s = _Session(_Resp("https://evil.example/x", body))
    with pytest.raises(tb.BuildRefused, match="refusing the fetch URL"):
        tb.fetch_source("https://op.europa.eu/x", hosts, tmp_path / "e2", max_bytes=1 << 20, session=s)
    with pytest.raises(tb.BuildRefused, match="max-mb"):
        tb.fetch_source("https://op.europa.eu/x", hosts, tmp_path / "e3", max_bytes=10,
                        session=_Session(_Resp("https://op.europa.eu/x", body)))
    with pytest.raises(tb.BuildRefused, match="HTTP 404"):
        tb.fetch_source("https://op.europa.eu/x", hosts, tmp_path / "e4", max_bytes=1 << 20,
                        session=_Session(_Resp("https://op.europa.eu/x", b"", status=404)))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["eurovoc.source"], "no partial file is left behind"


def test_the_real_session_is_the_guarded_one_held_to_the_publishers_hosts(monkeypatch, tmp_path):
    import src.safety.fetcher as F

    seen = {}

    def fake(**kw):
        seen.update(kw)
        return _Session(_Resp("https://op.europa.eu/x", MINI.read_bytes()))

    monkeypatch.setattr(F, "guarded_session", fake)
    tb.fetch_source("https://op.europa.eu/x", tb.PUBLISHER_HOSTS["eurovoc"], tmp_path / "s", max_bytes=1 << 20)
    assert seen["allowed_hosts"] == ("op.europa.eu", "publications.europa.eu")


def test_the_offline_command_builds_and_prints_the_file_to_send_back(tmp_path, capsys, no_network):
    assert tb.main(["--source", str(MINI), "--vintage", "2026-11-01", "--license", "CC0", "--out-dir", str(tmp_path),
                    "--languages", "all"]) == 0
    out = capsys.readouterr().out
    assert "send back:" in out and "eurovoc.summary.json" in out
    assert ts.thesaurus_status("eurovoc", tmp_path)["state"] == "ok"


# --- the route and the measurement script -------------------------------------------------------------------------


def test_the_route_reads_the_data_directory(monkeypatch, tmp_path):
    from src.api.law import law_thesauri

    monkeypatch.setattr(ts, "thesauri_dir", lambda base=None: Path(base) if base is not None else tmp_path)
    _build(tmp_path)
    states = {s["scheme"]: s["state"] for s in law_thesauri()["thesauri"]}
    assert states == {"eurovoc": "ok", "unesco-thesaurus": "missing", "agrovoc": "missing", "iptc-media-topics": "missing"}


def test_the_measurement_script_uses_only_a_checked_thesaurus(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import topic_sample_measure as tsm

    sample = ROOT / "src" / "catalog" / "data" / "topic_sample_law_titles.json"
    code, out = tsm.run_store("eurovoc", sample, tmp_path)
    assert code == tsm.NOT_MEASURED and out["thesaurus_state"] == "missing" and "licence" in out["reason"]
    _build(tmp_path)
    code, out = tsm.run_store("eurovoc", sample, tmp_path)
    assert out["status"] == "measured" and out["thesaurus_sha256"]
    (tmp_path / "eurovoc.summary.json").unlink()
    code, out = tsm.run_store("eurovoc", sample, tmp_path)
    assert code == tsm.NOT_MEASURED and out["thesaurus_state"] == "unverified" and "measurement" not in out


def test_the_law_panel_wires_the_status_line():
    html = (ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "static" / "app-living.js").read_text(encoding="utf-8")
    assert 'id="law-thesauri"' in html
    assert 'api("/api/law/thesauri")' in js and "loadLawThesauri();" in js and "renderLawThesauri();" in js


def test_a_crafted_or_odd_file_is_a_state_never_a_crash(tmp_path):
    d = tmp_path / "th"
    _build(d)
    path, spath = d / "eurovoc.json", d / "eurovoc.summary.json"
    good, summary = path.read_bytes(), spath.read_bytes()
    # Deeply nested JSON makes the parser raise RecursionError: unreadable, and the other schemes still answer.
    path.write_bytes(b"[" * 100_000)
    assert ts.thesaurus_status("eurovoc", d)["state"] == "unreadable"
    assert [s["state"] for s in ts.statuses(d)].count("missing") == 3
    path.write_bytes(good)
    spath.write_bytes(b"[" * 100_000)
    assert ts.thesaurus_status("eurovoc", d)["state"] == "unverified"
    spath.write_bytes(summary)
    if hasattr(os, "mkfifo"):  # a FIFO would block a read: refused by its type, never opened
        path.unlink()
        os.mkfifo(path)
        assert ts.thesaurus_status("eurovoc", d)["state"] == "unreadable"


def test_a_same_size_rewrite_with_its_old_mtime_put_back_is_still_caught(tmp_path):
    d = tmp_path / "th"
    _build(d)
    path = d / "eurovoc.json"
    good = path.read_bytes()
    st = path.stat()
    assert ts.thesaurus_status("eurovoc", d)["state"] == "ok"  # memoised now
    doc = json.loads(good)
    doc["vintage"] = "2026-11-02"  # the same length as 2026-11-01
    changed = ts.canonical_bytes(doc)
    assert len(changed) == len(good)
    path.write_bytes(changed)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert ts.thesaurus_status("eurovoc", d)["state"] == "hash_mismatch"
    assert ts.load_thesaurus("eurovoc", d)[0] is None


def test_the_bytes_do_not_depend_on_the_hash_seed(tmp_path):
    import subprocess
    import sys

    outs = []
    for seed in ("1", "2"):
        out = tmp_path / seed
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "thesaurus_build.py"), "--source", str(MINI),
                            "--vintage", "v", "--license", "l", "--languages", "all", "--out-dir", str(out)],
                           capture_output=True, text=True, timeout=120, cwd=ROOT,
                           env={**os.environ, "PYTHONHASHSEED": seed})
        assert r.returncode == 0, r.stderr
        outs.append((out / "eurovoc.json").read_bytes() + (out / "eurovoc.summary.json").read_bytes())
    assert outs[0] == outs[1]


def test_online_without_a_fetch_url_is_refused_not_ignored(tmp_path, capsys):
    assert tb.main(["--source", str(MINI), "--online", "--vintage", "v", "--license", "l", "--out-dir", str(tmp_path)]) == 2
    assert "--fetch-url" in capsys.readouterr().err and not any(tmp_path.iterdir())
