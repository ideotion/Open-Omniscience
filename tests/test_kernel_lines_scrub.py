"""OS-written journal and kernel lines leave their readers with the held passphrase taken out (audit row: the standalone route and
the text download had no net; an audit EXECVE record carries a process's argv)."""

from __future__ import annotations

import pytest

from src.database import connect
from src.monitoring import exit_evidence as ee
from src.monitoring import kernel_log as kl
from src.monitoring import secret_scrub as ss

_KEY = "hunter2-correct-horse-9f3a"
_PID = 4321


@pytest.fixture(autouse=True)
def _held(monkeypatch):
    monkeypatch.delenv("OO_NO_KERNEL_LOG", raising=False)
    monkeypatch.setattr(connect, "_passphrase", _KEY)
    ss.forget_held()
    yield
    ss.forget_held()


def test_kernel_evidence_lines_are_scrubbed_and_the_verdict_still_reads_the_raw_line(monkeypatch):
    oom = f"2026-10-14T23:05:53+0000 host kernel: Out of memory: Killed process {_PID} (open-omniscien) argv=open-omniscience --key {_KEY}"
    quiet = "2026-10-14T23:05:50+0000 host kernel: unrelated"
    monkeypatch.setattr(kl.shutil, "which", lambda name: "/usr/bin/journalctl")
    monkeypatch.setattr(kl, "_run", lambda cmd: (0, f"{quiet}\n{oom}\n"))
    out = kl.read_kernel_evidence(_PID)
    assert out["lines"] and not any(_KEY in ln for ln in out["lines"])
    assert any("Killed process" in ln for ln in out["lines"]), "the line is kept; only the key is out"
    assert out["verdict"] != "no-kernel-evidence", "the verdict was read from the line as written"


def test_kern_log_fallback_lines_are_scrubbed(monkeypatch):
    import io

    line = f"Oct 14 host kernel: process {_PID} argv {_KEY}\n"
    monkeypatch.setattr(kl.shutil, "which", lambda name: None)
    monkeypatch.setattr(kl, "open", lambda *a, **k: io.BytesIO(line.encode()), raising=False)
    out = kl.read_kernel_evidence(_PID)
    assert out["lines"] and _KEY not in "".join(out["lines"]) and "argv" in out["lines"][0]


def test_userspace_killer_lines_are_scrubbed(monkeypatch):
    line = f"2026-10-14T23:05:53+0000 host systemd-oomd[1]: Killed process {_PID} (open-omniscien) cmdline {_KEY}"
    monkeypatch.setattr(ee.shutil, "which", lambda name: "/usr/bin/journalctl")
    monkeypatch.setattr(ee, "_run", lambda cmd: (0, line + "\n"))
    out = ee.read_userspace_killers(_PID)
    assert out["lines"] and _KEY not in "".join(out["lines"]) and "Killed process" in out["lines"][0]


def test_published_lines_picks_whole_lines_and_takes_the_key_out_of_each():
    got = kl.published_lines(["a", "b", f"c {_KEY} d"], 2)
    assert len(got) == 2 and got[0] == "b" and _KEY not in got[1] and got[1].startswith("c ") and got[1].endswith(" d")
