"""R734 (2026-11-16): a feed or source address is written, in every report, field data file, diagnostics bundle and log line, with
its userinfo masked, every query value masked but an allowlisted harmless one, and its fragment dropped; fail closed; stable.

The helper is ``src.database.address_mask``; the writers reach it through ``failure_url``/``reported_url`` (``src.ingest.fetch_verdict``)
and ``shown_feed_key`` (``src.database.feed_key``). The RATCHETS at the bottom fail when a writer stops going through them."""

from __future__ import annotations

import ast
import pathlib

import pytest

from src.database.address_mask import (
    HARMLESS_QUERY_NAMES,
    QUERY_VALUE_MASK,
    masked_address,
    masked_query,
    query_secrets,
)
from src.database.feed_key import shown_feed_key
from src.ingest.fetch_verdict import address_secrets, failure_url, reported_url, shown_url

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------------------------------------------- the helper
@pytest.mark.parametrize(
    ("query", "written"),
    [
        ("token=abc123secret", "token=***"),
        ("format=rss&apikey=XYZ", "format=rss&apikey=***"),
        ("FORMAT=Atom", "FORMAT=Atom"),  # names compare case-insensitively, kept as written
        ("%66ormat=rss", "%66ormat=rss"),  # and percent-decoded
        ("id=7", "id=***"),  # an unknown name is masked: fail closed
        ("q=my+search", "q=***"),
        ("page=2;sig=deadbeef", "page=2;sig=***"),  # ; separates as & does
        ("lang=en/../x", "lang=***"),  # an allowlisted name with an odd-shaped value is masked all the same
        ("rss", "rss"),  # a bare allowlisted name stays
        ("3f9a0c1d2e", QUERY_VALUE_MASK),  # a bare item that is not one is masked whole: a name can be the token
        ("a b=1", QUERY_VALUE_MASK),  # a name that does not read as a plain name is masked with its value
        ("", ""),
        ("&&", "&&"),
    ],
)
def test_masked_query(query, written):
    assert masked_query(query) == written


def test_masked_address_drops_the_fragment_and_keeps_the_path():
    assert masked_address("https://news.example/rss?token=s3cret#frag") == "https://news.example/rss?token=***"
    assert masked_address("https://news.example/rss#access_token=s3cret") == "https://news.example/rss"
    assert masked_address("https://news.example/@me/rss") == "https://news.example/@me/rss"


def test_masking_is_stable_and_unsalted():
    """Two instances write the same text for the same address (no salt, no per-run state), so their rows still match."""
    url = "https://news.example/rss?cat=7&key=abcdef"
    assert {masked_address(url) for _ in range(5)} == {"https://news.example/rss?cat=7&key=***"}


def test_the_allowlist_holds_no_name_that_can_carry_who_asks():
    for name in ("id", "q", "user", "key", "token", "auth", "sig", "signature", "password", "secret", "apikey", "api_key", "session"):
        assert name not in HARMLESS_QUERY_NAMES


def test_query_secrets_are_the_masked_values_at_the_scrub_floor():
    assert query_secrets("https://a.example/x?format=rss&token=abcd%2Fef&id=7") == ("abcd%2Fef", "abcd/ef")
    assert query_secrets("https://a.example/x") == ()
    assert query_secrets(None) == ()  # type: ignore[arg-type]  # never raises


# ---------------------------------------------------------------------------------------------------------------- the writers
def test_failure_url_masks_userinfo_and_query_and_drops_the_fragment():
    assert failure_url("https://alice:pw@news.example/rss?apikey=K3Y&format=rss#x") == "https://***@news.example/rss?apikey=***&format=rss"


def test_failure_url_keeps_the_private_host_withholding():
    assert failure_url("https://archive-api.open-meteo.com/v1/archive?latitude=1&longitude=2") == "https://archive-api.open-meteo.com/v1/archive?…"


def test_reported_url_keeps_none_and_empty():
    assert reported_url(None) is None and reported_url("") == ""
    assert reported_url("https://news.example/rss?token=t") == "https://news.example/rss?token=***"


def test_the_ui_answers_keep_r637s_form():
    """An edit form sends the shown address back (``url_to_store``): a masked query sent back would be stored as typed, so the
    UI's own answers keep the query as stored, R637's form."""
    assert shown_url("https://alice:pw@news.example/rss?token=t") == "https://***@news.example/rss?token=t"


def test_address_secrets_add_the_query_values():
    assert address_secrets("https://alice:hunter2@a.example/x?token=abcdef") == ("alice:hunter2", "alice", "hunter2", "abcdef")


@pytest.mark.parametrize(
    ("stored", "written"),
    [
        ("f:news.example/rss?token=abcdef", "f:news.example/rss?token=***"),
        ("f:alice:hunter2@news.example/rss?cat=7&sig=zz", "f:***@news.example/rss?cat=7&sig=***"),
        ("f:news.example/rss", "f:news.example/rss"),
        ("f:https://news.example/rss?key=v", "f:https://news.example/rss?key=***"),
        (None, None),
        ("", ""),
        ("not-a-key?token=x", "not-a-key?token=x"),  # not a feed key: left what it is, as before
    ],
)
def test_shown_feed_key_masks_the_query(stored, written):
    assert shown_feed_key(stored) == written


def test_the_field_data_source_rows_write_the_address_through_reported_url():
    from src.api.diagnostics.source_samples import _shown_source_columns

    cols = _shown_source_columns()
    assert cols["rss_url"]("https://news.example/rss?token=abcdef") == "https://news.example/rss?token=***"
    assert cols["feed_key"]("f:news.example/rss?token=abcdef") == "f:news.example/rss?token=***"


# ---------------------------------------------------------------------------------------------------------------- the ratchets
def _src_trees():
    for path in sorted((ROOT / "src").rglob("*.py")):
        yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _called_name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")


#: The modules that may write an address in R637's form: the UI's own answers (an edit form sends it back). Every other writer
#: goes through reported_url / failure_url / shown_feed_key.
SHOWN_URL_READERS = frozenset(
    {
        "src/api/main.py",
        "src/api/source_management.py",
        "src/api/source_io.py",
        "src/monitoring/health.py",
    }
)


def test_ratchet_only_the_ui_answers_write_r637s_form():
    found = set()
    for rel, tree in _src_trees():
        if rel == "src/ingest/fetch_verdict.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.ingest.fetch_verdict" and any(a.name == "shown_url" for a in node.names):
                found.add(rel)
    assert found == SHOWN_URL_READERS, "a new writer of an address must use reported_url (R734), not shown_url"


def test_ratchet_no_scrub_takes_the_userinfo_alone():
    """``address_secrets`` is the scrub's one source: a call site taking ``userinfo_secrets`` would leave a query token in an
    exception's own words."""
    offenders = []
    for rel, tree in _src_trees():
        if rel == "src/ingest/fetch_verdict.py":
            continue
        offenders += [f"{rel}:{n.lineno}" for n in ast.walk(tree) if isinstance(n, ast.Call) and _called_name(n) == "userinfo_secrets"]
    assert offenders == []


_FEED_ADDRESS_KEYS = frozenset({"rss_url", "feed_key", "feed_url"})
_WRITERS = frozenset({"reported_url", "failure_url", "shown_feed_key", "shown_url", "_shown_feed"})
#: Report, field data and diagnostics writers: every feed address they put in a row goes through a writer above.
_REPORT_MODULE_PREFIXES = ("src/api/diagnostics/", "src/analytics/", "src/monitoring/", "src/backup/", "src/scheduler/")
#: Pinned: a dict that is a DATABASE write's parameters, not a row of a report (the key is stored, never shown).
_NOT_A_REPORT_ROW = frozenset({"src/analytics/source_topics.py:feed_key=key"})


def test_ratchet_report_rows_never_write_a_feed_address_raw():
    offenders = []
    for rel, tree in _src_trees():
        if not rel.startswith(_REPORT_MODULE_PREFIXES):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                if not (isinstance(key, ast.Constant) and key.value in _FEED_ADDRESS_KEYS) or isinstance(value, ast.Constant):
                    continue
                inner = value.body if isinstance(value, ast.IfExp) else value
                if isinstance(inner, ast.Call) and _called_name(inner) in _WRITERS:
                    continue
                if isinstance(inner, ast.Name) and inner.id in _WRITERS:  # a column -> writer table (source_samples)
                    continue
                if f"{rel}:{key.value}={ast.unparse(value)}" in _NOT_A_REPORT_ROW:
                    continue
                offenders.append(f"{rel}:{value.lineno}: {key.value}={ast.unparse(value)[:60]}")
    assert offenders == [], offenders


_LOG_CALLS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log", "log_failure"})
#: Pinned: names that read as URL-ish but are not addresses (a wiki lane's feed NAME; a test stand-in's own fixture URL).
_NOT_AN_ADDRESS = frozenset({"src/wiki/runner.py:feed", "src/testing/wiki_standin.py:url"})


def test_ratchet_no_log_line_or_raised_sentence_interpolates_an_address_raw():
    offenders = []
    for rel, tree in _src_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if not (name in _LOG_CALLS or name == "FetchFailed" or name.endswith("Error")):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                parts = [v.value for v in ast.walk(arg) if isinstance(v, ast.FormattedValue)] if isinstance(arg, ast.JoinedStr) else [arg]
                for part in parts:
                    label = part.id if isinstance(part, ast.Name) else (part.attr if isinstance(part, ast.Attribute) else "")
                    if "url" not in label.lower() and label not in {"feed", "feed_key", "href", "location"}:
                        continue
                    if f"{rel}:{label}" in _NOT_AN_ADDRESS or (rel.startswith(("src/wiki/", "src/versioned/")) and label == "feed"):
                        continue
                    offenders.append(f"{rel}:{part.lineno}: {ast.unparse(part)}")
    assert offenders == [], offenders
