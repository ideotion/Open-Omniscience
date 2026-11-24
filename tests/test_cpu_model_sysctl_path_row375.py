"""Row 375 (Audit 17 SEC-2): the macOS CPU line calls sysctl by its full path.

A bare "sysctl" is looked up on PATH, so a directory ahead of /usr/sbin could answer the
diagnostics bundle's CPU line. The call names /usr/sbin/sysctl, and nothing in the
diagnostics package runs a bare program name through subprocess.
"""

from __future__ import annotations

import subprocess
import sys
import types

import src.api.diagnostics.bundle as bundle


def test_darwin_cpu_model_runs_usr_sbin_sysctl(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return types.SimpleNamespace(returncode=0, stdout="Fake CPU\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "platform", "darwin")  # the function imports sys locally
    assert bundle._cpu_model_safe() == "Fake CPU"
    assert calls and calls[0][0] == "/usr/sbin/sysctl"


def test_no_bare_sysctl_in_the_bundle_source():
    import inspect

    src = inspect.getsource(bundle)
    assert '["sysctl"' not in src
    assert "'sysctl'" not in src.replace("'/usr/sbin/sysctl'", "")
