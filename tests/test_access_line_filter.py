"""The server's access line names the route template and a standard method, with no query (2026-10-07).

A passphrase typed into the address bar is a path, and the access line is a log the app cannot keep out of journald, ``docker
logs`` or a launcher's redirect. ``AccessLineFilter`` is attached to the ``uvicorn.access`` logger by the app itself, so it holds
however the server is started.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import logging

import pytest

from src.utils import access_log

MARK = "zq-typed-in-the-bar-77"


@pytest.fixture
def written():
    """What a console handler on the real ``uvicorn.access`` logger writes, formatted by the app's own access formatter."""
    from src.api import main  # noqa: F401 - importing the app is what installs the filter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(access_log.AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    log = logging.getLogger("uvicorn.access")
    old_level, old_prop = log.level, log.propagate
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(handler)
    try:
        yield stream
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
        log.propagate = old_prop


def _serve_line(method, full_path, status=404):
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", method, full_path, "1.1", status)


def test_the_app_attaches_the_filter_to_the_access_logger_itself():
    """MUTATION TARGET: the install taken out of ``src/api/main.py`` (a server started by the uvicorn command line never goes
    through ``_serve`` or ``uvicorn_log_config``, and imports the app)."""
    from src.api import main  # noqa: F401

    filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, access_log.AccessLineFilter)]
    assert len(filters) == 1
    before = len(logging.getLogger("uvicorn.access").filters)
    assert access_log.install_access_line_filter() is filters[0], "a second call returns the one filter"
    assert len(logging.getLogger("uvicorn.access").filters) == before, "and adds none"


def test_an_unmatched_path_and_its_query_never_reach_the_line(written):
    """MUTATION TARGET: the filter taken off, or the path or the query passed through again."""
    _serve_line("GET", f"/api/{MARK}?token={MARK}&x=1")
    line = written.getvalue()
    assert MARK not in line and "token" not in line and "?" not in line, line
    assert 'GET (no route matched) HTTP/1.1" 404' in line and "127.0.0.1:5000" in line


def test_a_matched_route_is_written_as_its_template_and_the_value_in_it_is_not(written):
    _serve_line("GET", f"/api/articles/{MARK}/view?lang=fr", status=200)
    line = written.getvalue()
    assert MARK not in line and "lang" not in line, line
    assert "GET /api/articles/{" in line, line


def test_a_method_the_client_made_up_is_written_as_a_fixed_word(written):
    _serve_line(MARK.upper(), "/api/health")
    line = written.getvalue()
    assert MARK.upper() not in line and "(other method)" in line, line


def test_a_record_that_is_not_the_servers_five_part_line_is_replaced_by_a_fixed_text(written):
    """Fails closed: a record of another shape on this logger is never written as it came."""
    logging.getLogger("uvicorn.access").info("GET /api/%s?q=%s", MARK, MARK)
    line = written.getvalue()
    assert MARK not in line and access_log.ACCESS_LINE_WITHHELD in line, line
