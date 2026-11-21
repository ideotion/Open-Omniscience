"""Row 236 (R734): a local-AI address is shown with its sign-in details and query values masked.

``vllm_lifecycle.status()["base_url"]`` and the Ollama status's ``base_url`` returned ``OO_VLLM_URL`` / ``OO_OLLAMA_URL``
verbatim, so a password in the address (``http://user:pw@127.0.0.1:8000``) reached the Settings page, and every error sentence
the two clients raise ("vLLM not reachable at <address>") carried it into toasts, logs and diagnostics. They now show the
address the way every report and log line already does (``fetch_verdict.reported_url``): userinfo ``***@``, query values
``***``, the fragment dropped. The request itself still uses the address as written.
"""

from __future__ import annotations

import httpx
import pytest

from src.llm import vllm_lifecycle as V
from src.llm.ollama import LLMUnavailable, OllamaClient, shown_address
from src.llm.vllm_client import VllmClient

SECRET_URL = "http://alice:s3cretpw@127.0.0.1:8000/v1?api_key=tok3nvalue#frag"
SECRETS = ("alice", "s3cretpw", "tok3nvalue", "frag")


def _clean(text: str) -> None:
    for s in SECRETS:
        assert s not in text, (s, text)


def test_the_shown_form_masks_sign_in_details_and_query_values():
    shown = shown_address(SECRET_URL)
    _clean(shown)
    assert shown.startswith("http://***@127.0.0.1:8000")
    assert shown_address("http://127.0.0.1:11434") == "http://127.0.0.1:11434"  # nothing to mask: unchanged


def test_the_vllm_status_shows_the_masked_address(monkeypatch):
    monkeypatch.setenv("OO_VLLM_URL", SECRET_URL)
    monkeypatch.setattr(V, "is_running", lambda **kw: False)
    monkeypatch.setattr(V, "port_occupant", lambda **kw: {"state": "free", "port": 8000, "detail": ""})
    st = V.status()
    assert st["base_url"].startswith("http://***@127.0.0.1:8000")
    _clean(st["base_url"])


@pytest.mark.parametrize("make", [OllamaClient, VllmClient])
def test_the_clients_error_sentences_show_the_masked_address(make):
    def _down(request):
        raise httpx.ConnectError("refused", request=request)

    url = SECRET_URL.split("/v1")[0] + "?api_key=tok3nvalue"
    client = make(base_url=url, client=httpx.Client(base_url=url, transport=httpx.MockTransport(_down)))
    assert client.base_url == url  # the request still uses the address as written
    with pytest.raises(LLMUnavailable) as exc:
        client.list_installed()
    assert "***@127.0.0.1:8000" in str(exc.value)
    _clean(str(exc.value))


@pytest.mark.parametrize("reachable", [True, False])
def test_the_health_answer_shows_the_masked_address(reachable, monkeypatch):
    """``GET /api/llm/health`` (the AI pill) answers with the active client's address, in both of its branches."""
    import src.api.llm as api
    import src.llm.backend as backend_mod

    url = "http://bob:hunter2pw@127.0.0.1:11434"

    def _answer(request):
        if not reachable:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"models": [{"name": "m:1"}]})

    fake = OllamaClient(base_url=url, client=httpx.Client(base_url=url, transport=httpx.MockTransport(_answer)))
    monkeypatch.setattr(backend_mod, "resolve_backend", lambda **kw: {"backend": "ollama"})
    out = api.llm_health(client=fake)
    assert out["available"] is reachable
    assert out["base_url"] == "http://***@127.0.0.1:11434"
    assert "hunter2pw" not in str(out) and "bob" not in str(out)


@pytest.mark.parametrize("make", [OllamaClient, VllmClient])
@pytest.mark.parametrize("call", ["list_installed", "generate"])
def test_a_refused_sign_in_does_not_quote_the_address_either(make, call):
    """httpx's own status text quotes the request's full address ("Client error '401 Unauthorized' for url
    'http://alice:pw@...'"): a wrong password, or a vLLM started with --api-key. That text is masked too."""
    url = "http://alice:s3cretpw@127.0.0.1:8000?api_key=tok3nvalue"
    client = make(
        base_url=url,
        client=httpx.Client(base_url=url, transport=httpx.MockTransport(lambda r: httpx.Response(401, text="nope"))),
    )
    with pytest.raises(Exception) as exc:
        client.list_installed() if call == "list_installed" else client.generate("hi", model="m")
    text = str(exc.value)
    assert "401" in text  # the failure is still said
    _clean(text)


def test_the_bounded_error_a_job_stores_is_masked_too():
    from src.llm.ollama import bounded_error

    url = "http://alice:s3cretpw@127.0.0.1:8000/api/tags?api_key=tok3nvalue"
    req = httpx.Request("GET", url)
    exc = httpx.HTTPStatusError("Client error '401 Unauthorized' for url '" + url + "'", request=req,
                                response=httpx.Response(401, request=req))
    _clean(bounded_error(exc))


@pytest.mark.parametrize("make", [OllamaClient, VllmClient])
def test_a_logged_failure_does_not_quote_the_address_through_its_cause(make, caplog):
    """Security read of row 236: the clients raise their own sentence FROM httpx's error, and ``log_failure`` prints the whole
    chain, so httpx's raw "for url 'http://alice:pw@...'" reached the log under a masked outer sentence."""
    import logging

    from src.monitoring.secret_scrub import TRACEBACK_ATTRIBUTE, log_failure

    url = "http://alice:s3cretpw@127.0.0.1:8000?api_key=tok3nvalue"
    client = make(
        base_url=url,
        client=httpx.Client(base_url=url, transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))),
    )
    log = logging.getLogger("test.row236")
    with pytest.raises(Exception) as exc:
        client.list_installed()
    with caplog.at_level(logging.ERROR, logger="test.row236"):
        log_failure(log, "probe", exc.value)
    assert caplog.records, "nothing was logged"
    for rec in caplog.records:
        _clean(rec.getMessage())
        _clean(str(getattr(rec, TRACEBACK_ATTRIBUTE, "")))
    assert "500" in caplog.records[0].getMessage()


@pytest.mark.parametrize("make", [OllamaClient, VllmClient])
def test_a_redirect_location_is_masked_too(make):
    """httpx's status text adds "Redirect location: '<Location>'" for a 3xx, an address the server chose."""
    url = "http://alice:s3cretpw@127.0.0.1:8000"
    loc = "http://alice:s3cretpw@127.0.0.1:8000/x?api_key=tok3nvalue"

    def _redirect(request):
        return httpx.Response(302, headers={"Location": loc})

    client = make(base_url=url, client=httpx.Client(base_url=url, transport=httpx.MockTransport(_redirect)))
    with pytest.raises(Exception) as exc:
        client.list_installed()
    _clean(str(exc.value))
    _clean(repr(exc.value.__cause__))


def test_an_error_with_no_request_is_masked_too():
    from src.llm.ollama import bounded_error, error_text

    e = httpx.ConnectError("could not reach http://alice:s3cretpw@127.0.0.1:11434/?api_key=tok3nvalue")
    _clean(error_text(e))
    _clean(bounded_error(e))


@pytest.mark.parametrize(
    "url",
    [
        "http://alice:s3cret/pw@127.0.0.1:11434",  # "/" ends the authority early: the parse sees no userinfo
        "http://alice:s3cret#pw@127.0.0.1:11434",
        "http://alice:s3cret?pw@127.0.0.1:11434",
    ],
)
def test_a_password_that_ends_the_authority_early_is_not_shown(url):
    shown = shown_address(url)
    assert "s3cret" not in shown and "alice" not in shown and "pw" not in shown, shown


def test_the_vllm_status_never_shows_such_a_password(monkeypatch):
    monkeypatch.setenv("OO_VLLM_URL", "http://alice:s3cret/pw@127.0.0.1:8000")
    monkeypatch.setattr(V, "is_running", lambda **kw: False)
    monkeypatch.setattr(V, "port_occupant", lambda **kw: {"state": "free", "port": 8000, "detail": ""})
    assert "s3cret" not in V.status()["base_url"]
