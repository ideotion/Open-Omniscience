"""Release pipeline guard (RC gate: "release action emits all artifacts; SHA256SUMS").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the release workflow's contract so the V0.1 release-engineering row cannot silently
regress: tagging vX.Y.Z builds the sdist + wheel, computes SHA256SUMS, verifies the tag
matches the single-sourced pyproject version, and publishes a GitHub Release. Debian is
the V0.1 install target; no signing key yet (checksums-only, a tracked future item).
Third-party actions stay SHA-pinned (CI hygiene), so no fabricated/unpinned action refs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WF = _ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_exists_and_parses():
    assert _WF.exists(), "the release workflow (.github/workflows/release.yml) must exist"
    data = yaml.safe_load(_WF.read_text(encoding="utf-8"))
    # 'on:' parses to the YAML boolean True (the same quirk ci.yml relies on).
    triggers = data[True]
    assert "push" in triggers and "tags" in triggers["push"], "must trigger on tag push"
    assert any(t.startswith("v") for t in triggers["push"]["tags"]), "tags filter must be v*"


def test_release_builds_artifacts_and_checksums():
    text = _WF.read_text(encoding="utf-8")
    assert "python -m build" in text, "the workflow must build the sdist + wheel"
    assert "sha256sum" in text and "SHA256SUMS" in text, "it must compute SHA256SUMS"
    assert "gh release create" in text, "it must publish a GitHub Release"
    # The artifacts + the checksums are uploaded to the release.
    assert ".whl" in text and ".tar.gz" in text and "SHA256SUMS" in text


def test_release_verifies_tag_matches_pyproject_version():
    text = _WF.read_text(encoding="utf-8")
    # A tag that disagrees with the single-sourced version must fail the release loudly.
    assert 'tag="${GITHUB_REF_NAME#v}"' in text
    assert "pyproject.toml" in text and "exit 1" in text, (
        "the workflow must fail when the tag != pyproject version (no mislabelled release)"
    )


def test_release_actions_are_sha_pinned():
    """No unpinned/fabricated third-party action refs (CI hygiene). Every `uses:` must be a
    40-hex SHA with a version comment, matching the ci.yml convention."""
    text = _WF.read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses, "the workflow should use the pinned checkout/setup-python actions"
    for u in uses:
        assert re.search(r"@[0-9a-f]{40}$", u), f"action ref not SHA-pinned: {u}"


def test_release_least_privilege():
    data = yaml.safe_load(_WF.read_text(encoding="utf-8"))
    assert data["permissions"] == {"contents": "read"}, "top-level perms must be read-only"
    # Only the publish job elevates, and only to contents: write.
    job = data["jobs"]["release"]
    assert job["permissions"] == {"contents": "write"}, "the release job needs contents: write"


# --- An existing release still gets the no-telemetry re-check (OPEN_QUEUE, the v0.4.0 notes gap) ---
# A release made on GitHub's Releases page together with its tag already exists when this workflow
# runs. That branch used to append only the checksums, so the generated no-telemetry re-check (the
# per-release ritual, RELEASE_0.4_GATE row V) never reached the notes and nothing said so. The step's
# own shell is run here against a fake ``gh`` and a fake generator, so the test reads what it does.

_GENERATED = """### What shipped since `v0.4.0`

- a row

### No-telemetry re-check

- Socket-importer ratchet: exit **0** (PASSED).

### Verification bar

- bar
"""


def _publish_script() -> str:
    data = yaml.safe_load(_WF.read_text(encoding="utf-8"))
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name", "").startswith("Publish GitHub Release"):
                return step["run"]
    raise AssertionError("no 'Publish GitHub Release' step in release.yml")


def _run_existing(tmp_path: Path, existing_body: str) -> tuple[int, str, str, list[str]]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "SHA256SUMS").write_text("abc  oo.whl\n", encoding="utf-8")
    (tmp_path / "existing_body.md").write_text(existing_body, encoding="utf-8")
    (tmp_path / "gen.md").write_text(_GENERATED, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$OO_GH_LOG"\n'
        'if [ "$1 $2" = "release view" ] && [ "${4:-}" = "--json" ]; then cat existing_body.md; fi\n'
        'if [ "$1 $2" = "release edit" ]; then cp "$5" edited_notes.md; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    script = _publish_script().replace(
        'python scripts/release_notes.py --tag "${TAG}" -o generated_notes.md',
        "cp gen.md generated_notes.md",
    )
    assert "cp gen.md generated_notes.md" in script, "the generator line moved; update this test"
    log = tmp_path / "gh.log"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        TAG="v0.4.0",
        GH_TOKEN="unused",
        OO_GH_LOG=str(log),
    )
    proc = subprocess.run(
        [bash, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )
    edited = tmp_path / "edited_notes.md"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return (
        proc.returncode,
        proc.stdout + proc.stderr,
        edited.read_text(encoding="utf-8") if edited.exists() else "",
        calls,
    )


def test_an_existing_release_without_the_recheck_gets_it_appended(tmp_path):
    rc, out, edited, calls = _run_existing(tmp_path, "The maintainer's own words.\n")
    assert rc == 0, out
    assert edited.startswith("The maintainer's own words."), "the existing text must be kept first"
    assert "### No-telemetry re-check" in edited and "PASSED" in edited
    assert "### Verification bar" not in edited, "only the re-check section is appended"
    assert "Verify your download (SHA-256)" in edited and "abc  oo.whl" in edited
    assert "already existed" in out, "the append must be said in the log"
    assert not any(c.startswith("release create") for c in calls)


def test_an_existing_release_that_has_both_is_left_alone(tmp_path):
    body = (
        "Words.\n\n### No-telemetry re-check\n\n- done by hand\n\n"
        "### Verify your download (SHA-256)\n\nabc\n"
    )
    rc, out, edited, calls = _run_existing(tmp_path, body)
    assert rc == 0, out
    assert edited == "", "nothing to add, so the notes must not be edited"
    assert not any(c.startswith("release edit") for c in calls)
    assert any(c.startswith("release upload") for c in calls)
