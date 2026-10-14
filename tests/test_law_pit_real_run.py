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
import re
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
def _OK(url):
    return url.startswith("https://gazette.zzz.test/")


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
        report = R.run(s, f, _ROW, day="2019-06-01", today="2025-01-01", url_ok=_OK)
    assert report["verdict"] == "found", report
    assert f.asked == [_PIT, _NOW]  # exactly two GETs, both composed from the row
    assert report["search_on_2019_day"]["matched"] == 1 and report["search_on_today"]["matched"] == 0
    assert [v["dating"] for v in report["versions"]] == ["official", "official"]
    assert report["versions"][0]["valid_from"] == "2019-06-01"


def test_a_source_that_states_no_date_cannot_answer_a_past_day(corpus):
    f = _Fetcher({_PIT: _v("act.v1", undated=True), _NOW: _v("act.v2", undated=True)})
    with corpus() as s:
        report = R.run(s, f, _ROW, day="2019-06-01", today="2099-01-01", url_ok=_OK)
    assert report["verdict"] == "not-found", report
    assert "observation" in report["why"]
    assert {v["dating"] for v in report["versions"]} == {"observed"}


def test_two_identical_captures_show_nothing(corpus):
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v1")})
    with corpus() as s:
        report = R.run(s, f, _ROW, today="2025-01-01", url_ok=_OK)
    assert report["verdict"] == "not-decisive", report
    assert "phrase" not in report


def test_a_refused_capture_is_kept_verbatim_and_nothing_is_searched(corpus):
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v2")}, refuse=(_PIT,))
    with corpus() as s:
        report = R.run(s, f, _ROW, today="2025-01-01", url_ok=_OK)
    assert report["verdict"] == "fetch-refused" and _PIT in report["why"]
    assert len(report["captures"]) == 1 and "search_on_2019_day" not in report


def _main(monkeypatch, tmp_path, *args: str, data_dir: Path | None):
    """The script's main() in this process with the fetcher replaced by one that fails the test if it is ever
    built: a regressed guard then fails here, and cannot reach a network or write a default data directory."""
    import src.ingest as ingest

    def _never(*_a, **_k):
        raise AssertionError("the guard did not hold: the fetcher was built")

    monkeypatch.setattr(ingest, "EthicalFetcher", _never)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if data_dir is None:
        monkeypatch.delenv("OO_DATA_DIR", raising=False)
    else:
        monkeypatch.setenv("OO_DATA_DIR", str(data_dir))
    with pytest.raises(SystemExit) as exc:
        R.main(list(args))
    return str(exc.value)


def test_it_refuses_without_online_and_names_the_host(monkeypatch, tmp_path):
    said = _main(monkeypatch, tmp_path, data_dir=tmp_path / "fresh")
    named = re.search(r"contacts (\S+) \(", said)
    assert "--online" in said and named and named.group(1) == R.HOST
    fresh = tmp_path / "fresh"
    assert not fresh.exists() or not any(fresh.iterdir())  # no database, no setting: nothing was written


def test_it_refuses_a_store_someone_uses(monkeypatch, tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    assert "not empty" in _main(monkeypatch, tmp_path, "--online", data_dir=tmp_path)
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "x"


def test_it_refuses_without_a_scratch_directory_at_all(monkeypatch, tmp_path):
    assert "OO_DATA_DIR" in _main(monkeypatch, tmp_path, "--online", data_dir=None)


def test_a_phrase_given_that_the_current_text_also_holds_is_not_decisive(corpus):
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v2")})
    with corpus() as s:
        report = R.run(s, f, _ROW, phrase="This Act establishes the standards", today="2025-01-01", url_ok=_OK)
    assert report["verdict"] == "not-decisive", report


def test_the_index_and_the_picker_read_words_alike():
    """A hyphen separates words and a number is a word, as in the FTS5 tokenizer, so a phrase cannot differ
    between the texts by punctuation alone and cannot span a number the index would keep."""
    assert R.pick_phrase("the data-protection authority shall publish a list", "the data protection authority shall publish a list") is None
    phrase = R.pick_phrase("processing under subsection 2 by a organisation is lawful", "processing under subsection 2 by a processor is lawful")
    assert phrase and "2" in phrase.split()


def test_found_needs_today_to_find_nothing(corpus, monkeypatch):
    """Mutation guard: if today's search finds the words in ANY version, the verdict is not `found`."""
    import src.law.pit_search as pit

    real = pit.search

    def _everywhere(db, query, *, on=None, **kw):
        out = real(db, query, on=on, **kw)
        if on == "2025-01-01":
            out = {**out, "matched": 1, "hits": [{"version_id": -1}]}
        return out

    monkeypatch.setattr(pit, "search", _everywhere)
    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v2")})
    with corpus() as s:
        report = R.run(s, f, _ROW, day="2019-06-01", today="2025-01-01", url_ok=_OK)
    assert report["verdict"] == "not-found", report


def test_the_default_act_is_in_the_catalogue_on_the_publishers_host():
    row = R._catalogue_row(R.DEFAULT_TITLE)
    assert row and R.allowed_url(row["official_url"]) and R.allowed_url(row["url"])
    assert R._catalogue_row("no such act anywhere") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.legislation.gov.uk.evil.test/ukpga/2018/12/data.xml",   # lookalike by suffix
        "https://evil.test/www.legislation.gov.uk/ukpga/2018/12/data.xml",   # the host in the path
        "https://evil.test/?u=https://www.legislation.gov.uk/",              # the host in the query
        "https://www.legislation.gov.uk@evil.test/ukpga/2018/12/data.xml",   # the host as userinfo
        "https://user:pw@www.legislation.gov.uk/ukpga/2018/12/data.xml",     # userinfo
        "https://www.legislation.gov.uk:8443/ukpga/2018/12/data.xml",        # a port
        "http://www.legislation.gov.uk/ukpga/2018/12/data.xml",              # not https
        "https://legislation.gov.uk/ukpga/2018/12/data.xml",                 # the apex
        "https://evil.test\\@www.legislation.gov.uk/ukpga/2018/12/data.xml",  # backslash: a browser reads evil.test
        "https://www.legislation.gov.uk /ukpga/2018/12/data.xml",            # whitespace
        "ftp://www.legislation.gov.uk/ukpga/2018/12/data.xml",
        "https://www.legislation.gov.uk/ukpga/a\\b/data.xml",                  # a backslash in the PATH: only that clause refuses it
        "https://www.legislation.gov.uk/ukpga/a b/data.xml",                 # a space in the path
        "https://www.legislation.gov.uk/ukpga/a\nb/data.xml",                # a newline in the path
        "https://www.legislation.gov.uk/ukpga/a\x00b/data.xml",              # a control character in the path
        "",
    ],
)
def test_only_https_on_exactly_the_publishers_host_is_allowed(url):
    assert R.allowed_url(url) is False


def test_the_publishers_own_urls_are_allowed():
    assert R.allowed_url("https://www.legislation.gov.uk/ukpga/2018/12/2019-06-01/data.xml") is True
    assert all(R.allowed_url(u) for u in R.capture_urls("https://www.legislation.gov.uk/ukpga/2018/12", "2019-06-01"))


def test_the_default_refuses_any_other_host_before_a_request_or_a_write(corpus):
    """run()'s default rule is the real one: the fixture host is refused, the fetcher is never asked, and no
    document row is written."""
    from src.database.models import LawDocument

    f = _Fetcher({_PIT: _v("act.v1"), _NOW: _v("act.v2")})
    with corpus() as s:
        report = R.run(s, f, _ROW, today="2025-01-01")
        assert s.query(LawDocument).count() == 0
    assert report["verdict"] == "fetch-refused" and "refused before any request" in report["why"]
    assert f.asked == []


def test_the_url_fetched_is_the_one_checked_not_the_row_url(corpus):
    """A row whose `url` is on the publisher but whose `official_url` is elsewhere fetches from official_url, so
    it is official_url's host that is judged."""
    row = {**_ROW, "url": "https://www.legislation.gov.uk/ukpga/2018/12/data.xml", "official_url": "https://evil.test/act"}
    f = _Fetcher({})
    with corpus() as s:
        report = R.run(s, f, row)
    assert report["verdict"] == "fetch-refused" and f.asked == []


def test_the_catalogue_row_must_be_on_the_publisher_for_both_urls(monkeypatch):
    import src.law.catalog as catalog

    good = {"title": "An Act", "url": "https://www.legislation.gov.uk/ukpga/1/contents", "official_url": "https://www.legislation.gov.uk/ukpga/1"}
    for bad in (
        {**good, "official_url": "https://evil.test/ukpga/1"},
        {**good, "url": "http://www.legislation.gov.uk/ukpga/1/contents"},
        {**good, "official_url": "https://legislation.gov.uk/ukpga/1"},
    ):
        monkeypatch.setattr(catalog, "load_legal_catalog", lambda bad=bad: {"documents": [bad]})
        assert R._catalogue_row("An Act") is None
    monkeypatch.setattr(catalog, "load_legal_catalog", lambda: {"documents": [good]})
    assert R._catalogue_row("An Act")["official_url"] == good["official_url"]


class _Resp:
    def __init__(self, status: int, url: str, location: str | None = None) -> None:
        self.status_code = status
        self.url = url
        self.headers = {"Location": location} if location else {}

    def close(self) -> None:
        pass


def _drive(monkeypatch, answers: dict[str, _Resp]):
    """The real fetcher class with its HTTP session's `get` and the base `_guard_target` (a DNS lookup) replaced
    by recorders, so the REAL redirect loop runs and nothing touches a network. Returns (fetcher, requests asked,
    hosts handed to the base guard)."""
    import requests

    import src.ingest as ingest

    asked: list[str] = []
    guarded: list[str] = []
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: asked.append(url) or answers[url])
    monkeypatch.setattr(ingest.EthicalFetcher, "_guard_target", lambda self, host: guarded.append(host))
    return R.make_fetcher(), asked, guarded


def test_a_hop_to_the_publisher_is_followed_and_the_base_guard_still_runs(monkeypatch):
    first, second = "https://www.legislation.gov.uk/a", "https://www.legislation.gov.uk/b"
    fetcher, asked, guarded = _drive(monkeypatch, {first: _Resp(302, first, second), second: _Resp(200, second)})
    resp, final = fetcher._guarded_redirect_get(first)
    assert asked == [first, second] and final == second and resp.status_code == 200
    assert guarded == [R.HOST]  # the override hands the allowed host on to the app's SSRF guard (the super() call)


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.test/x",                                    # another host: the hop guard
        "https://evil.test\\@www.legislation.gov.uk/x",            # urlparse reads www.legislation.gov.uk, urllib3 evil.test
        "http://www.legislation.gov.uk/x",                        # a downgrade on the right host
        "https://www.legislation.gov.uk:8443/x",                  # a port on the right host
        "https://www.legislation.gov.uk@evil.test/x",             # userinfo
    ],
)
def test_a_redirect_that_leaves_the_publisher_is_refused_before_it_is_requested(monkeypatch, location):
    import src.ingest as ingest

    first = "https://www.legislation.gov.uk/a"
    fetcher, asked, _guarded = _drive(monkeypatch, {first: _Resp(302, first, location)})
    with pytest.raises(ingest.BlockedTarget):
        fetcher._guarded_redirect_get(first)
    assert asked == [first]  # the hop's own request was never made


def test_the_page_and_robots_requests_are_judged_too(monkeypatch):
    import src.ingest as ingest

    fetcher, asked, _guarded = _drive(monkeypatch, {})
    with pytest.raises(ingest.BlockedTarget):
        fetcher._guarded_redirect_get("https://evil.test/robots.txt")
    assert asked == []


def test_the_fetcher_refuses_another_hosts_name_and_an_answer_from_one(monkeypatch):
    import src.ingest as ingest

    fetcher = R.make_fetcher()
    with pytest.raises(ingest.BlockedTarget):
        fetcher._guard_target("evil.test")
    with pytest.raises(ingest.BlockedTarget):
        fetcher._guard_target("legislation.gov.uk")

    class _Answer:
        final_url = "https://evil.test/elsewhere"

    monkeypatch.setattr(ingest.EthicalFetcher, "fetch", lambda self, url, *a, **k: _Answer())
    with pytest.raises(ingest.FetchError, match="refused"):
        R.make_fetcher().fetch("https://www.legislation.gov.uk/ukpga/2018/12/data.xml")
