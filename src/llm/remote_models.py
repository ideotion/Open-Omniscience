"""Refuse every Ollama model that runs somewhere other than this computer (R671).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Generation talks to the LOCAL Ollama daemon on loopback, and airplane mode deliberately lets that through (OPEN_QUEUE 2026-07-20:
"a missing model errors, it never auto-pulls" -- local inference does no network I/O). Ollama's cloud models break that premise: the
local daemon itself forwards the request, prompt included, to ollama.com, from its own process, where this app's socket guard and kill
switch cannot see it. A prompt here is corpus text, so one model name was enough to send it off the machine with airplane mode on.

HOW THE DAEMON DECIDES (read in Ollama's source, github.com/ollama/ollama at 5632619, 2026-11-12):

* ``internal/modelref/modelref.go`` ``parseSourceSuffix``: the part after the LAST ``:`` is a source suffix when it is ``cloud``
  (``gpt-oss:20b:cloud``, ``glm-4.6:cloud``) or ends in ``-cloud`` with no ``/`` in it (``gpt-oss:120b-cloud``), compared after
  trimming and lower-casing. ``server/routes.go`` (GenerateHandler) sends such a request to ``proxyCloudJSONRequest`` BEFORE looking for
  any local model, so it needs no pull and no install: the name alone forwards it.
* A local model whose config carries ``RemoteHost`` and ``RemoteModel`` (a cloud stub, or a model ``ollama create``-d FROM a cloud
  model under any name) is forwarded to that host (``server/routes.go``, the ``m.Config.RemoteHost != ""`` branch). ``/api/tags`` lists
  such a model with ``remote_host`` / ``remote_model`` (``api/types.go`` ``ListModelResponse``), which is how a local name is told apart.
* ``OLLAMA_NO_CLOUD=1`` (or ``disable_ollama_cloud`` in ``~/.ollama/server.json``) makes the daemon refuse both (``internal/cloud``).
  The app sets it on a daemon IT starts (``ollama_lifecycle.start``); a daemon the operator runs keeps its own environment, which is why
  the check below does not rely on it.

THE RULE, FAIL CLOSED: before any request that names a model, the name must not carry a cloud suffix, and it must be listed by the
daemon's own ``/api/tags`` WITHOUT a remote field. A name the list does not show is refused as not installed; a list that cannot be read
is refused as unreachable. Nothing is guessed in the model's favour: a remote field that is present at all (any value but null or
an empty string) marks the entry remote, a field of an odd type is read as text, and when two listed entries answer to one name, one
remote entry is enough to refuse it.

WHAT IT CANNOT SEE. Any local process can talk to the daemon (it has no authentication), so between this check's ``/api/tags`` read
and the request that follows, a local ``ollama create`` could re-point the name; ``OLLAMA_NO_CLOUD=1`` closes that only for a daemon
the app starts. And telling a local alias of a cloud model apart relies on ``/api/tags`` carrying ``remote_host``/``remote_model``
(both ``omitempty`` there); a daemon that one day marks remote models some other way would read here as local.
"""

from __future__ import annotations

#: The one sentence the person reads, keyed in every locale (the UI translates it by this exact text). It names no model, so the key
#: is fixed; the API adds the name beside it.
REFUSAL = (
    "That model runs on Ollama's cloud, not on this computer, so it is refused: the text you give it would leave the machine. "
    "Choose a local model."
)

_REMOTE_FIELDS = ("remote_host", "remote_model")


def is_cloud_name(name: str | None) -> bool:
    """True when Ollama would route ``name`` to its cloud by the name alone (``:cloud`` or a ``-cloud`` tag), as ``parseSourceSuffix``."""
    raw = str(name or "").strip()
    idx = raw.rfind(":")
    if idx < 0:
        return False
    suffix_raw = raw[idx + 1 :].strip()
    suffix = suffix_raw.lower()
    if suffix == "cloud":
        return True
    if suffix == "local":
        # an explicit local suffix: the daemon strips it and reads the base, so judge the base (a nested suffix is an error there)
        return is_cloud_name(raw[:idx])
    return "/" not in suffix_raw and suffix.endswith("-cloud")


def _key(name: str) -> str:
    """The name as ``/api/tags`` spells it: the default registry and namespace dropped, ``:latest`` when no tag, lower-cased."""
    n = str(name or "").strip()
    if n.lower().endswith(":local"):
        n = n[: -len(":local")]
    for prefix in ("registry.ollama.ai/library/", "registry.ollama.ai/", "library/"):
        if n.lower().startswith(prefix):
            n = n[len(prefix) :]
            break
    last_slash, last_colon = n.rfind("/"), n.rfind(":")
    if last_colon <= last_slash:
        n += ":latest"
    return n.lower()


def is_remote_entry(entry: dict) -> bool:
    """True when an ``/api/tags`` entry is a model the daemon forwards elsewhere (a remote field set, or a cloud-suffixed name)."""
    if any(entry.get(f) not in (None, "") for f in _REMOTE_FIELDS):
        return True
    return is_cloud_name(entry.get("name")) or is_cloud_name(entry.get("model"))


def local_entry(name: str, models: list[dict]) -> tuple[str, dict | None]:
    """Judge ``name`` against the daemon's ``/api/tags`` ``models`` list.

    Returns ``("cloud", entry)`` for a name the daemon would send elsewhere, ``("missing", None)`` for a name the list does not show,
    and ``("local", entry)`` only for a listed model with no remote field.
    """
    if is_cloud_name(name):
        return "cloud", None
    want = _key(name)
    found: dict | None = None
    for entry in models:
        if not isinstance(entry, dict):
            continue
        names = {_key(str(entry[k])) for k in ("name", "model") if entry.get(k)}
        if want in names:
            if is_remote_entry(entry):
                return "cloud", entry
            found = found or entry
    return ("local", found) if found is not None else ("missing", None)
