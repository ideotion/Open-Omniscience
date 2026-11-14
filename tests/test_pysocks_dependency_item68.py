"""PySocks is a core dependency, and requests and the airplane guard use it (queue item 68(d), R656).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Protected mode over Tor names a ``socks5h://`` proxy. requests reaches it through urllib3's ``contrib.socks``, which needs PySocks. Without
it, requests swaps in a stand-in ``SOCKSProxyManager`` that raises ``InvalidSchema("Missing dependencies for SOCKS support.")`` at the first
request, and the airplane guard has no PySocks ``connect`` or ``sendto`` to wrap. Until R656 the operator installed it by hand
(docs/SECURITY.md said "no packaged extra"). The first four tests fail wherever an install leaves it out; the last two read the manifest,
the lock and the source. None opens a socket.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent


def test_pysocks_imports():
    import socks

    assert Version(socks.__version__) >= Version("1.7.1")


def test_requests_uses_the_real_socks_manager_not_its_stand_in():
    import requests.adapters
    from urllib3.contrib.socks import SOCKSProxyManager

    assert requests.adapters.SOCKSProxyManager is SOCKSProxyManager


def test_an_adapter_builds_a_socks_manager_for_a_tor_proxy_without_connecting():
    """What a protected-mode session asks for at its first request; building the manager connects nothing."""
    import requests.adapters
    from urllib3.contrib.socks import SOCKSProxyManager

    adapter = requests.adapters.HTTPAdapter()
    try:
        manager = adapter.proxy_manager_for("socks5h://oo.0123456789abcdef0123456789abcdef:oo.0123456789abcdef0123456789abcdef@127.0.0.1:9050")
        assert isinstance(manager, SOCKSProxyManager)
    finally:
        adapter.close()


def test_the_airplane_guard_has_pysocks_to_wrap():
    """The guard's two SOCKS patches are installed only when PySocks imports (src/ingest/airplane.py)."""
    import socks

    from src.ingest import airplane

    assert airplane._pysocks is socks
    assert airplane._orig_socks_connect is not None
    assert airplane._orig_socks_sendto is not None


def test_core_declares_pysocks_and_the_lock_pins_it_with_hashes():
    """In ``[project] dependencies`` (not an extra), and pinned by the hash-verified lock the clean-room install uses."""
    core = [Requirement(d) for d in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]]
    pysocks = [r for r in core if canonicalize_name(r.name) == "pysocks"]
    assert len(pysocks) == 1, [str(r) for r in core]
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pin = re.search(r"^pysocks==(\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", lock, re.M)
    assert pin, "requirements.lock has no hashed pysocks pin"
    assert pysocks[0].specifier.contains(pin.group(1)), (str(pysocks[0]), pin.group(1))


def test_no_module_claims_that_separate_circuits_make_lookups_unlinkable():
    """Queue item 68(b): the Wikidata getters said distinct lookups were "unlinkable over Tor". A circuit is one hop of linkability: each
    lookup still sends a bot User-Agent, protected mode included, and they run close together. The docstrings now say "separate circuits".
    The fetcher's ``_isolated_proxies`` said a host's circuit was "unlinkable to other hosts' circuits" (R656, found 2026-11-14)."""
    said = [
        f"{p.relative_to(ROOT).as_posix()}:{n}"
        for p in sorted((ROOT / "src").rglob("*.py"))
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"unlinkable over Tor|distinct ones are unlinkable|unlinkable to other", line)
    ]
    assert said == []
