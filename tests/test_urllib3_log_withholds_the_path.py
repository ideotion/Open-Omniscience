"""R142: the HTTP library's own log lines do not carry a request's path or query.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urllib3`` logs a request's target on its own loggers: at WARNING, with the default log level, when a response has a malformed header line
("Failed to parse headers (url=...)", on a fetch that SUCCEEDS as well as on one that fails) and when a session retries; at DEBUG, the request
line and each redirect hop. The installer's download is a signed storage address, so its signature rode those lines into the error journal
that a debug bundle carries. ``src/ingest/urllib3_log.py`` rewrites the target arguments of those records before any handler sees them.

The checks that matter drive the REAL library against a loopback socket: a scripted adapter stands in for urllib3 entirely and could never
show a line the library writes itself. Each real-stack case also asserts that the library DID log the line (so the case cannot pass because
the library stayed quiet) and that the host is still there (so the filter did not just blank the record).
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

import src.ingest  # noqa: F401  (importing the package is what installs the filter, which these tests rely on)
from src.ingest import urllib3_log
from src.safety import fetcher as fetcher_mod
from src.safety.settings import SafetySettings

ROOT = Path(__file__).resolve().parents[1]

SIG = "PLANTEDSIG"

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
#: A header line with no colon: urllib3 parses the response, finds a defect, logs it, and the request still succeeds.
_MALFORMED_HEADER = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nbadheaderwithoutcolon\r\nConnection: close\r\n\r\nok"


def _serve(*replies: bytes | None) -> int:
    """A loopback listener that answers its Nth connection with ``replies[N]`` (``None``: read the request and close without a word)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(15)

    def run() -> None:
        try:
            for reply in replies:
                conn, _addr = srv.accept()
                with conn:
                    conn.recv(65536)
                    if reply is not None:
                        conn.sendall(reply)
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


# --------------------------------------------------------------------------- the rewrite itself


@pytest.mark.parametrize(
    ("arg", "expected"),
    [
        (f"/install.sh?sig={SIG}", urllib3_log.WITHHELD),
        ("/", urllib3_log.WITHHELD),
        (f"https://objects.githubusercontent.com:443/a/b?sig={SIG}", f"https://objects.githubusercontent.com:443/{urllib3_log.WITHHELD}"),
        (f"https://host.example/a#{SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),
        (f"http://user:{SIG}@host.example/p", f"http://host.example/{urllib3_log.WITHHELD}"),
        (f"http://user:{SIG}@host.example", "http://host.example"),
        (f"https://host.example/?sig={SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),
        (f"https://host.example?sig={SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),
        (f"https://[::1]:8443/x?y={SIG}", f"https://[::1]:8443/{urllib3_log.WITHHELD}"),
        (f"https://host.example:notaport/x?{SIG}", urllib3_log.WITHHELD),
        ("https://host.example", "https://host.example"),
        ("https://host.example/", "https://host.example/"),
        ("host.example:443", "host.example:443"),
        ("HTTP/1.1", "HTTP/1.1"),
        ("GET", "GET"),
        (200, 200),
        (None, None),
    ],
)
def test_withhold_keeps_the_scheme_host_and_port_and_loses_the_rest(arg, expected):
    assert urllib3_log.withhold(arg) == expected


def test_withhold_leaves_an_object_that_is_not_text_alone():
    exc = ConnectionError("Max retries exceeded")
    assert urllib3_log.withhold(exc) is exc


#: The shapes urllib3 2.8.0 logs a target in, copied from its source (logger, level, format string, arguments), so a shape that stops being
#: covered fails here by name; the real-stack cases below are what show that urllib3 still logs them this way.
_SHAPES = [
    ("urllib3.connection", logging.WARNING, "Failed to parse headers (url=%s): %s", (f"http://h.example:80/p?sig={SIG}", "MissingHeaderBodySeparatorDefect")),
    ("urllib3.connectionpool", logging.WARNING, "Retrying (%r) after connection broken by '%r': %s", ("Retry(total=0)", "ProtocolError", f"/p?sig={SIG}")),
    ("urllib3.connectionpool", logging.DEBUG, '%s://%s:%s "%s %s %s" %s %s', ("https", "h.example", 443, "GET", f"/p?sig={SIG}", "HTTP/1.1", 200, 2)),
    ("urllib3.connectionpool", logging.DEBUG, "Redirecting %s -> %s", (f"/a?sig={SIG}", f"https://h.example/b?sig={SIG}")),
    ("urllib3.connectionpool", logging.DEBUG, "Retry: %s", (f"/p?sig={SIG}",)),
    ("urllib3.util.retry", logging.DEBUG, "Incremented Retry for (url='%s'): %r", (f"/p?sig={SIG}", "Retry(total=0)")),
    ("urllib3.poolmanager", logging.INFO, "Redirecting %s -> %s", (f"/a?sig={SIG}", f"https://h.example/b?sig={SIG}")),
]


@pytest.mark.parametrize(("logger", "level", "fmt", "args"), _SHAPES, ids=[f"{s[0]}:{s[2][:24]}" for s in _SHAPES])
def test_each_shape_urllib3_logs_a_target_in_loses_it(caplog, logger, level, fmt, args):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger(logger).log(level, fmt, *args)
    assert caplog.records, "the record must still be emitted: the filter rewrites, it never drops"
    assert SIG not in caplog.text
    assert urllib3_log.WITHHELD in caplog.text


def test_a_record_with_no_target_is_left_as_it_was(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger("urllib3.connectionpool").warning("Connection pool is full, discarding connection: %s. Connection pool size: %s", "h.example", 10)
    assert "Connection pool is full, discarding connection: h.example. Connection pool size: 10" in caplog.text


@pytest.mark.parametrize("name", urllib3_log.LOGGERS)
def test_the_filter_is_on_each_logger_exactly_once(name):
    urllib3_log.install()
    urllib3_log.install()
    assert sum(isinstance(f, urllib3_log._WithholdRequestPath) for f in logging.getLogger(name).filters) == 1


def test_importing_the_fetcher_alone_installs_the_filter():
    """A process that only builds a guarded session (the installer's) gets the filter: ``src.ingest`` is imported by the fetcher and imports
    the module that installs it. Run in a fresh interpreter, because this process already has the filter, and ask the loggers by their names
    and the filter's class name, so that the check itself imports nothing from ``urllib3_log``."""
    code = (
        "import logging\n"
        "import src.safety.fetcher\n"
        "names = ('urllib3.connection', 'urllib3.connectionpool', 'urllib3.poolmanager', 'urllib3.util.retry')\n"
        "missing = [n for n in names if not any(type(f).__name__ == '_WithholdRequestPath' for f in logging.getLogger(n).filters)]\n"
        "print('MISSING', missing)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert "MISSING []" in out.stdout
    assert set(urllib3_log.LOGGERS) == {"urllib3.connection", "urllib3.connectionpool", "urllib3.poolmanager", "urllib3.util.retry"}


# --------------------------------------------------------------------------- the real library, a real socket


def test_a_response_with_a_malformed_header_logs_without_the_path_and_the_fetch_still_succeeds(caplog):
    """The reproduction of the read's finding B1, at the default level, on a SUCCESSFUL fetch."""
    caplog.set_level(logging.WARNING)
    port = _serve(_MALFORMED_HEADER)
    resp = requests.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200 and resp.content == b"ok"
    assert "Failed to parse headers" in caplog.text, "urllib3 must have logged the line, or this case proves nothing"
    assert f"127.0.0.1:{port}" in caplog.text
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text


def test_a_retry_logs_without_the_path(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    port = _serve(None, _OK)
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=0)))
    resp = session.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200
    assert "Retrying" in caplog.text, "urllib3 must have logged the retry, or this case proves nothing"
    assert "Incremented Retry" in caplog.text, "and the retry object's own debug line"
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text


def test_the_debug_request_line_and_the_redirect_hop_log_without_the_path(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    redirect = b"HTTP/1.1 302 Found\r\nLocation: /next.sh?sig=" + SIG.encode() + b"2\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    port = _serve(redirect, _OK)
    resp = requests.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200
    assert 'HTTP/1.1" 302' in caplog.text and 'HTTP/1.1" 200' in caplog.text, "urllib3 must have logged both request lines"
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text and "next.sh" not in caplog.text


def test_the_installers_own_download_logs_nothing_of_the_signed_address_even_when_the_library_does(caplog, monkeypatch):
    """The installer's real path (``_default_get_bytes`` through ``_get_within`` and a ``GuardedSession``) against a loopback server whose
    answer has a malformed header: the download succeeds and the signature is in no log record. Only the host-list check is patched, because
    the listed hosts are https on port 443 and this is a loopback socket."""
    from src.llm import installer

    monkeypatch.setattr(fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="transparent"))
    monkeypatch.setattr(fetcher_mod, "refuse_unlisted_host", lambda url, allowed: None)
    caplog.set_level(logging.DEBUG, logger="urllib3")
    caplog.set_level(logging.DEBUG)
    port = _serve(_MALFORMED_HEADER)
    body = installer._default_get_bytes(f"http://127.0.0.1:{port}/ollama/ollama/releases/download/v1/install.sh?X-Amz-Signature={SIG}")
    assert body == b"ok"
    assert "Failed to parse headers" in caplog.text, "urllib3 must have logged the line, or this case proves nothing"
    assert SIG not in caplog.text
    assert "X-Amz-Signature" not in caplog.text and "releases/download" not in caplog.text
