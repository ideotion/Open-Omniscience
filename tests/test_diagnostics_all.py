"""The all-diagnostics bundle's member encoder (field report 2026-06-22: "download all
diagnostics logs at once"). Tests the one piece of novel logic — turning any endpoint
return (a plain dict, a JSONResponse, or a StreamingResponse) into ZIP-member bytes —
without standing up the full app (the heavy logs are covered by their own tests).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from fastapi.responses import JSONResponse, StreamingResponse

from src.api.diagnostics import _member_bytes


def test_member_bytes_encodes_a_plain_dict():
    out = _member_bytes({"a": 1, "b": ["x", "y"]})
    assert json.loads(out) == {"a": 1, "b": ["x", "y"]}


def test_member_bytes_reads_a_jsonresponse_body():
    out = _member_bytes(JSONResponse({"hello": "world"}))
    assert json.loads(out) == {"hello": "world"}


def test_member_bytes_drains_a_streamingresponse():
    def _gen():
        yield '{"part":'
        yield "1}"

    out = _member_bytes(StreamingResponse(_gen(), media_type="application/json"))
    assert json.loads(out) == {"part": 1}
