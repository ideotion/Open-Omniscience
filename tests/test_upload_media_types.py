"""The two corpus uploads and the qualification merge refuse a body in an encoding they do not read (R663; OPEN_QUEUE 2026-10-27 item 14).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on 2026-10-27 (``audit-0.5.0/proposal-raw-body-content-type-2026-10-27.md``): ``POST /api/newsletters/import`` and
``POST /api/documents/pdf/upload`` answered 200 to NO body and to every Content-Type, and the newsletter import get-or-created its source
row on an empty POST; ``POST /api/diagnostics/source-qualification-merge`` ran the whole merge for an empty or ``text/plain`` POST. Each now
answers 415 before it reads the form, writes a row or computes anything. The Origin layer already stops a cross-site POST; this is depth.

Each refusal below is proved by a spy that must stay UNCALLED (no row created, no merge run), not by the status alone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import ingestion
from src.api.main import app

_UPLOADS = ("/api/newsletters/import", "/api/documents/pdf/upload")
_MERGE = "/api/diagnostics/source-qualification-merge"

# (headers, body) for every shape a route that reads a form was never written for. text/plain and urlencoded are browser "simple
# request" types; "none" is a body-less POST, the one that created the newsletter row.
_NOT_MULTIPART = {
    "none": ({}, None),
    "text/plain": ({"content-type": "text/plain"}, b"files=x"),
    "json": ({"content-type": "application/json"}, b"{}"),
    "octet-stream": ({"content-type": "application/octet-stream"}, b"x"),
    "urlencoded": ({"content-type": "application/x-www-form-urlencoded"}, b"files=x"),
}


class _Reached(RuntimeError):
    """Raised by a spy that must not be reached; a plain exception, so it surfaces as a 500 the status assertion catches."""


def _spy(seen: list[str], what: str):
    def f(*_a, **_k):
        seen.append(what)
        raise _Reached(what)

    return f


def _post(c: TestClient, path: str, headers: dict, body: bytes | None):
    return c.post(path, headers=headers, content=body) if body is not None else c.post(path, headers=headers)


@pytest.mark.parametrize("path", _UPLOADS)
@pytest.mark.parametrize("shape", sorted(_NOT_MULTIPART))
def test_an_upload_not_sent_as_multipart_is_a_415_and_writes_nothing(path, shape, monkeypatch):
    touched: list[str] = []
    monkeypatch.setattr(ingestion, "_get_newsletter_source", _spy(touched, "source row"))
    monkeypatch.setattr(ingestion.Request, "form", _spy(touched, "form read"))
    headers, body = _NOT_MULTIPART[shape]
    with TestClient(app, raise_server_exceptions=False) as c:
        r = _post(c, path, headers, body)
    assert r.status_code == 415, (shape, r.status_code, r.text)
    assert "multipart/form-data" in r.json()["detail"]
    assert touched == []


@pytest.mark.parametrize("path", _UPLOADS)
def test_a_multipart_upload_still_imports(path):
    files = [("files", ("notes.txt", b"not an email or a pdf", "text/plain"))]
    with TestClient(app) as c:
        r = c.post(path, files=files)
    assert r.status_code == 200, r.text


def test_a_multipart_content_type_with_its_boundary_and_odd_case_is_accepted():
    from src.api.body_media import media_type

    class _R:
        headers = {"content-type": 'Multipart/Form-Data; boundary="----x"'}

    assert media_type(_R()) == "multipart/form-data"  # type: ignore[arg-type]


@pytest.mark.parametrize("shape", ["none", "text/plain", "json", "octet-stream"])
def test_the_merge_not_sent_as_a_form_is_a_415_and_computes_nothing(shape, monkeypatch):
    import src.catalog.qualification_export as export

    ran: list[str] = []
    monkeypatch.setattr(export, "build_overlay_export", _spy(ran, "merge"))
    headers, body = _NOT_MULTIPART[shape]
    with TestClient(app, raise_server_exceptions=False) as c:
        r = _post(c, _MERGE, headers, body)
    assert r.status_code == 415, (shape, r.status_code, r.text)
    assert ran == []


def test_the_merge_still_takes_both_form_encodings(monkeypatch):
    """The UI sends FormData (multipart); the command-line style and the tests send a url-encoded form. Both are the declared params."""
    import src.catalog.qualification_export as export

    ran: list[str] = []
    monkeypatch.setattr(export, "build_overlay_export", _spy(ran, "merge"))
    with TestClient(app, raise_server_exceptions=False) as c:
        a = c.post(_MERGE, data={"include_this_instance": "true"})
        b = c.post(_MERGE, files=[("files", ("x.json", b"{}", "application/json"))], data={"include_this_instance": "true"})
    assert a.status_code != 415 and b.status_code != 415, (a.text, b.text)
    assert ran[:1] == ["merge"], "the url-encoded form reached the merge"
    # the multipart one reaches the handler and is refused there for its malformed upload, or reaches the merge: either way not a 415
