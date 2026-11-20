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
        ("page", "page"),  # a bare allowlisted name stays
        ("rss", "***"),  # feed, rss and channel left the allowlist (first security read): a private feed's token sits there
        ("feed=0123456789abcdef0123456789abcdef", "feed=***"),
        ("tag=ghp_abcdefghijklmnopqrstuvwxyz0123456789", "tag=***"),  # longer than a kept value's 16 characters
        ("lang=en&lang=SECRETSECRETSECRET", "lang=en&lang=***"),
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
    secrets = query_secrets("https://a.example/x?format=rss&token=abcd%2Fef&id=7")
    assert {"abcd%2Fef", "abcd/ef", "abcd%2fef"} <= set(secrets)
    assert not any(s == "rss" or s == "7" for s in secrets)


@pytest.mark.parametrize(
    "value, quoted",
    [
        ("S\u00c9CRETXYZ", "S%C3%89CRETXYZ"),
        ("ab|cdEFGH", "ab%7CcdEFGH"),
        ("SEC RETXYZ", "SEC%20RETXYZ"),
        ("a%2fBCDEFG", "a%2FBCDEFG"),
        ("SECR\tETXYZ", "SECRETXYZ"),
    ],
)
def test_the_scrub_takes_out_the_spelling_requests_quotes_back(value, quoted):
    """The first security read proved requests re-quotes the address before quoting it in its exception text; each of those
    spellings is among the secrets the scrub takes out."""
    assert quoted in query_secrets(f"https://a.example/rss?token={value}")
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
    secrets = address_secrets("https://alice:hunter2@a.example/x?token=abcdef")
    assert secrets[:4] == ("alice:hunter2", "alice", "hunter2", "abcdef")
    assert {"token=abcdef", "?token=abcdef", "&token=abcdef"} <= set(secrets)  # row 107: the value in its context too


# ---------------------------------------------------------------------------------------------------------------- row 107
def _requests_style(url: str) -> Exception:
    """The words requests writes for a failed request: the path and query, re-quoted, inside its own sentence."""
    from urllib.parse import urlsplit

    from requests.utils import requote_uri

    parts = urlsplit(requote_uri(url))
    return ConnectionError(f"HTTPSConnectionPool(host='{parts.hostname}', port=443): Max retries exceeded with url: "
                           f"{parts.path}?{parts.query} (Caused by NewConnectionError('Failed to establish a new connection'))")


def _recorded(url: str) -> str:
    from src.monitoring.secret_scrub import record_text

    return record_text(_requests_style(url), *address_secrets(url))


@pytest.mark.parametrize(
    "url, secret",
    [
        ("https://news.example/rss?pin=123", "123"),  # red before: "123" is under the floor, so it was never handed to the scrub
        ("https://news.example/rss?format=rss&pin=12", "12"),
        ("https://news.example/rss?pin=1%7C2", "1%7C2"),  # the re-quoted spelling of a short value
        ("https://news.example/rss?pin=1|2", "1%7C2"),  # ... written by requests itself
        ("https://news.example/rss;s=9/x", ";s=9"),  # an R736 path parameter
    ],
)
def test_a_SHORT_masked_value_leaves_the_exception_text_with_its_name(url, secret):
    text = _recorded(url)
    assert "Max retries exceeded" in text, "the sentence is kept: only the value and its name are taken out"
    assert secret not in text, text


def test_the_same_short_value_in_two_items_leaves_both_times():
    text = _recorded("https://news.example/rss?a=12&b=12")
    assert "12" not in text.split("url:", 1)[1].split("(Caused", 1)[0], text
    assert "Max retries exceeded" in text


def test_a_harmless_short_value_stays_and_an_unrelated_number_is_not_cut():
    text = _recorded("https://news.example/rss?page=2&pin=123")
    assert "page=2" in text, "an allowlisted value is not a secret"
    assert "port=443" in text, "a number elsewhere in the sentence is untouched"
    assert "123" not in text


def test_a_query_too_short_for_any_context_withholds_the_text_rather_than_leak_it():
    from src.monitoring.secret_scrub import UNREADABLE_TEXT

    text = _recorded("https://news.example/rss?7")
    assert "?7" not in text
    assert text.endswith(UNREADABLE_TEXT) or UNREADABLE_TEXT in text or "withheld" in text.lower(), text


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


_FEED_ADDRESS_KEYS = frozenset({"rss_url", "feed_key", "feed_url", "source_url", "final_url", "feed_address"})
_WRITERS = frozenset({"reported_url", "failure_url", "shown_feed_key", "shown_url", "_shown_feed"})
#: Report, field data and diagnostics writers: every feed address they put in a row goes through a writer above.
_REPORT_MODULE_PREFIXES = (
    "src/api/diagnostics/", "src/analytics/", "src/monitoring/", "src/backup/", "src/scheduler/",
    "src/catalog/", "src/ingest/",  # row 106: the catalogue's reports and the collector's records write rows too
)
#: Pinned, each with why it is not a row of a report: written as ``path:key=expression``.
_NOT_A_REPORT_ROW = frozenset(
    {
        "src/analytics/source_topics.py:feed_key=key",  # a DATABASE write's parameters: the key is stored, never shown
        "src/catalog/qualification.py:feed_key=key",  # the same: the parameters of an UPDATE of the sources table
        "src/ingest/seed_sources.py:rss_url=row.rss_url",  # a lookup table read beside the catalogue's value, never written out
    }
)


def _report_row_writes(tree: ast.AST):
    """Every ``(key, value)`` a module puts in a row: a dict literal's entries, ``dict(key=value)`` and ``row["key"] = value``
    (row 106: the last two were not read, so a row built by assignment passed unread)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield key.value, value
        elif isinstance(node, ast.Call) and _called_name(node) == "dict":
            for kw in node.keywords:
                if kw.arg is not None:
                    yield kw.arg, kw.value
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                    and node.value is not None
                ):
                    yield target.slice.value, node.value


def test_ratchet_report_rows_never_write_a_feed_address_raw():
    offenders = []
    for rel, tree in _src_trees():
        if not rel.startswith(_REPORT_MODULE_PREFIXES):
            continue
        for key, value in _report_row_writes(tree):
            if key not in _FEED_ADDRESS_KEYS or isinstance(value, ast.Constant):
                continue
            branches = [value.body, value.orelse] if isinstance(value, ast.IfExp) else [value]  # both arms of a conditional
            if all(
                isinstance(b, ast.Constant)
                or (isinstance(b, ast.Call) and _called_name(b) in _WRITERS)
                or (isinstance(b, ast.Name) and b.id in _WRITERS)  # a column -> writer table (source_samples)
                for b in branches
            ):
                continue
            if f"{rel}:{key}={ast.unparse(value)}" in _NOT_A_REPORT_ROW:
                continue
            offenders.append(f"{rel}:{value.lineno}: {key}={ast.unparse(value)[:60]}")
    assert offenders == [], offenders


def test_the_report_row_ratchet_reads_assignments_and_dict_calls():
    """Row 106: the three ways a row is built are all read (a planted offender of each kind is found)."""
    planted = ast.parse(
        "row = {'rss_url': src.rss_url}\nrow2 = dict(feed_url=s.url)\nrow3 = {}\nrow3['final_url'] = r.url\nrow3['rss_url'] = reported_url(u)\n"
    )
    seen = [(k, ast.unparse(v)) for k, v in _report_row_writes(planted) if k in _FEED_ADDRESS_KEYS]
    assert ("rss_url", "src.rss_url") in seen and ("feed_url", "s.url") in seen and ("final_url", "r.url") in seen
    assert ("rss_url", "reported_url(u)") in seen  # read too, and passed by the writer check


def test_every_pinned_report_row_still_exists():
    """A pin whose expression is gone is a pin that would excuse the next one written the same way."""
    live = {f"{rel}:{k}={ast.unparse(v)}" for rel, tree in _src_trees() for k, v in _report_row_writes(tree)}
    assert live >= _NOT_A_REPORT_ROW, sorted(_NOT_A_REPORT_ROW - live)


_LOG_CALLS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "log_failure", "print"})
#: Calls whose result is safe to log: the writers, the scrub, and what reads an address without writing it (its host, its length).
_SAFE_CALLS = frozenset(
    {"reported_url", "failure_url", "shown_feed_key", "_shown_feed", "record_text", "masked_address", "address_secrets", "_logged",
     "_url_without_query", "len", "bool", "isinstance"}
)
#: The UI answer form, or a wrapper of it: never in a log line or a raised sentence (the second security read on R734 found a
#: request body logged through such a wrapper).
_ANSWER_FORM_CALLS = frozenset({"shown_url", "_shown", "_shown_found"})
#: Pinned, each with why it is not a feed address leaving the app: written as ``path:expression``.
_NOT_AN_ADDRESS = frozenset(
    {
        "src/api/markets.py:feed",  # a market feed's catalogue entry; only feed.key is written
        "src/markets/pipeline.py:feed",  # the same
        "src/backup/sqlite_backup.py:engine.url",  # only get_backend_name() is written
        "src/database/session.py:DATABASE_URL",  # only the scheme is written
        "src/law/declared.py:row.get('url')",  # a bundled law catalogue address, never a user's feed
        "src/services/duckduckgo.py:result.get('url', 'No URL')",  # the module's __main__ demo prints a public search result
        "src/testing/wiki_standin.py:url",  # a test stand-in's own fixture URL
        "src/tui/panel.py:url",  # the app's own loopback address
        "src/versioned/feed.py:batch.feed",  # a versioned feed's NAME
    }
)
_NAME_ONLY_FEED_TREES = ("src/wiki/", "src/versioned/")  # there ``feed`` is a lane's name


def _urlish(label: str) -> bool:
    return "url" in label.lower() or label in {"feed", "feed_key", "href", "location"}


def _raw_addresses(node: ast.AST, out: list[ast.AST]) -> None:
    """Every part of a log or raise argument that writes an address unmasked: a URL-ish name or attribute, a URL-ish key read by
    subscript or ``.get``, or the UI answer form, at any depth (an f-string, ``%``, ``.format``, ``+``), except inside a safe call."""
    if isinstance(node, ast.Call):
        name = _called_name(node)
        if name in _SAFE_CALLS:
            return
        if name in _ANSWER_FORM_CALLS:
            out.append(node)
            return
        first = node.args[0] if node.args else None
        if name == "get" and isinstance(first, ast.Constant) and isinstance(first.value, str) and _urlish(first.value):
            out.append(node)
            return
    key = node.slice.value if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) else None
    if isinstance(key, str) and _urlish(key):
        out.append(node)
        return
    if isinstance(node, ast.Name | ast.Attribute) and _urlish(node.id if isinstance(node, ast.Name) else node.attr):
        out.append(node)
        return
    if isinstance(node, ast.Lambda):
        return
    for child in ast.iter_child_nodes(node):
        _raw_addresses(child, out)


def test_ratchet_no_log_line_or_raised_sentence_interpolates_an_address_raw():
    offenders = []
    for rel, tree in _src_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if not (name in _LOG_CALLS or name == "FetchFailed" or name.endswith(("Error", "Exception", "Refused", "Failed"))):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                found: list[ast.AST] = []
                _raw_addresses(arg, found)
                for part in found:
                    text = ast.unparse(part)
                    if f"{rel}:{text}" in _NOT_AN_ADDRESS or (rel.startswith(_NAME_ONLY_FEED_TREES) and text == "feed"):
                        continue
                    offenders.append(f"{rel}:{part.lineno}: {text}")
    assert offenders == [], offenders


def test_the_log_ratchet_sees_the_spellings_the_second_read_named():
    """The escapes the second security read listed, each caught: a call, a subscript, ``%``, ``.format``, ``+``, a wrapper of
    the answer form, ``print``, an ``Exception``."""
    src = """
log.info("x %s" % url)
log.info("x {}".format(row["rss_url"]))
log.info("x " + str(feed_url))
log.warning(f"{row.get('url')}")
log.info(f"{_shown(u)}")
print(final_url)
raise HTTPException(detail=f"bad {source.rss_url}")
"""
    found: list[ast.AST] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and (_called_name(node) in _LOG_CALLS or _called_name(node).endswith("Exception")):
            for arg in list(node.args) + [k.value for k in node.keywords]:
                _raw_addresses(arg, found)
    assert len(found) == 7, [ast.unparse(f) for f in found]


def test_a_logged_request_body_and_a_health_row_write_the_reported_form():
    """The second security read: the create/update log line wrote the body through the UI answer form, and the health row's
    ``url`` kept the query its ``detail`` masked. Both write :func:`reported_url` now."""
    from datetime import UTC, datetime

    from src.api.source_management import _reported_data
    from src.monitoring.health import HealthStatus, SourceHealth

    sent = "https://u:p@news.example/rss?token=abcdef1234#frag"
    assert _reported_data({"rss_url": sent, "name": "n"}) == {"rss_url": "https://***@news.example/rss?token=***", "name": "n"}
    row = SourceHealth(1, "n", sent, HealthStatus.UP, 1.0, datetime.now(UTC)).to_dict()
    assert row["url"] == "https://***@news.example/rss?token=***"
