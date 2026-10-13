"""Row G's real-source check (scripts/law_pit_real_run.py) says what it measured, and refuses what it must.

The script is the real half of the gate's closing clause («a law's 2019 text is findable by point-in-time
search ... on one real source»). The real run needs www.legislation.gov.uk (R125/R132), which this suite
never touches; what is pinned here is the decision logic on the fixture jurisdiction, served by a stand-in
fetcher keyed by URL, so that the run on the real site can only fail for a reason the report states:
the verdict is `found` only when the 2019 words are placed on the 2019 day by the source's own date and
are not found today; a source that states no date cannot answer a past day; two identical captures show
nothing; a refused capture is kept verbatim.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.ingest import FetchError
from src.versioned import store

ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = ROOT / "tests" / "fixtures" / "law" / "synthetic"
_SPEC = importlib.util.spec_from_file_location("law_pit_real_run", ROOT / "scripts" / "law_pit_real_run.py")
assert _SPEC and _SPEC.loader
R = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(R)

_ROW = {
    "jurisdiction": "ZZZ", "title": "Measurement Standards Act", "url": "https://gazette.zzz.test/act/2019/7/data.xml",
    "official_url": "https://gazette.zzz.test/act/2019/7", "category": "legislation", "consolidated": True,
    "language": "zxx",
}
_PIT, _NOW = R.capture_urls(_ROW["official_url"], "2019-06-01")


class _Result:
    def __init__(self, body: bytes) -> None:
        self.raw_content = body
        self.content = body.decode("utf-8")
        self.content_type = "application/xml"


class _Fetcher:
    """Serves a body per URL; a URL it does not know is refused the way the real fetcher refuses."""

    def __init__(self, bodies: dict[str, bytes], refuse: tuple[str, ...] = ()) -> None:
        self.bodies, self.refuse, self.asked = bodies, refuse, []

    def fetch(self, url, **_kw):
        self.asked.append(url)
        if url in self.refuse or url not in self.bodies:
            raise FetchError(f"refused: {url}")
        return _Result(self.bodies[url])


def _v(name: str, *, undated: bool = False) -> bytes:
    text = (_FIXTURES / f"{name}.clml.xml").read_text(encoding="utf-8")
    if undated:
        text = "\n".join(line for line in text.splitlines() if "dct:valid" not in line)
    return text.encode("utf-8")


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    engine = create_engine(f"sqlite:///{tmp_path / 'corpus.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    try:
        store.create_lane("law")
        yield sessionmaker(bind=engine, future=True)
    finally:
        store.dispose_all()
        engine.dispose()


def test_the_urls_are_composed_from_the_catalogue_row_not_typed():
    assert R.capture_urls("https://h.test/ukpga/2018/12/", "2019-06-01") == (
        "https://h.test/ukpga/2018/12/2019-06-01/data.xml",
        "https://h.test/ukpga/2018/12/data.xml",
    )


def test_a_phrase_is_picked_only_from_words_the_old_text_has_and_the_new_one_lacks():
    old = "In this Act, measurement means a quantity determined by comparison with a standard maintained under section 4."
    new = "In this Act, measurement means a quantity determined by comparison with a published standard maintained under section 4."
    phrase = R.pick_phrase(old, new)
    assert phrase and phrase in " ".join(R._WORD.findall(old.lower())) and phrase not in " ".join(R._WORD.findall(new.lower()))
    assert R.pick_phrase(old, old) is None  # the same text: nothing to find


def test_the_2019_text_is_found_on_the_2019_day_and_not_today(corpus):
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v2")})
    with corpus() as s:
        report = R.run(s, f, _ROW, day="2019-06-01", today="2025-01-01")
    assert report["verdict"] == "found", report
    assert f.asked == [_PIT, _NOW]  # exactly two GETs, both composed from the row
    assert report["search_on_2019_day"]["matched"] == 1 and report["search_on_today"]["matched"] == 0
    assert [v["dating"] for v in report["versions"]] == ["official", "official"]
    assert report["versions"][0]["valid_from"] == "2019-06-01"


def test_a_source_that_states_no_date_cannot_answer_a_past_day(corpus):
    f = _Fetcher({_PIT: _v("act.v1", undated=True), _NOW: _v("act.v2", undated=True)})
    with corpus() as s:
        report = R.run(s, f, _ROW, day="2019-06-01", today="2099-01-01")
    assert report["verdict"] == "not-found", report
    assert "observation" in report["why"]
    assert {v["dating"] for v in report["versions"]} == {"observed"}


def test_two_identical_captures_show_nothing(corpus):
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v1")})
    with corpus() as s:
        report = R.run(s, f, _ROW, today="2025-01-01")
    assert report["verdict"] == "not-decisive", report
    assert "phrase" not in report


def test_a_refused_capture_is_kept_verbatim_and_nothing_is_searched(corpus):
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v2")}, refuse=(_PIT,))
    with corpus() as s:
        report = R.run(s, f, _ROW, today="2025-01-01")
    assert report["verdict"] == "fetch-refused" and _PIT in report["why"]
    assert len(report["captures"]) == 1 and "search_on_2019_day" not in report


def _script(*args: str, data_dir: Path | None, online_env: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "OO_DB_PLAINTEXT": "1", "OO_AUTOSEED": "0", "OO_NO_SCHEDULER": "1"}
    env.pop("DATABASE_URL", None)
    env.pop("OO_DATA_DIR", None)
    if data_dir is not None:
        env["OO_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "law_pit_real_run.py"), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


def test_it_refuses_without_online_and_names_the_host(tmp_path):
    done = _script(data_dir=tmp_path / "fresh")
    assert done.returncode != 0
    named = re.search(r"contacts (\S+) \(", done.stderr)
    assert "--online" in done.stderr and named and named.group(1) in R._HOSTS
    fresh = tmp_path / "fresh"
    assert not fresh.exists() or not any(fresh.iterdir())  # no database, no setting: nothing was written


def test_it_refuses_a_store_someone_uses(tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    done = _script("--online", data_dir=tmp_path)
    assert done.returncode != 0 and "not empty" in done.stderr
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "x"


def test_it_refuses_without_a_scratch_directory_at_all():
    done = _script("--online", data_dir=None)
    assert done.returncode != 0 and "OO_DATA_DIR" in done.stderr


def test_the_default_act_is_in_the_catalogue_on_the_publishers_host():
    from urllib.parse import urlparse

    row = R._catalogue_row(R.DEFAULT_TITLE)
    assert row and urlparse(row["official_url"]).hostname in R._HOSTS
    assert R._catalogue_row("no such act anywhere") is None
