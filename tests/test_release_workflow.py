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

import re
from pathlib import Path

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
    assert "pyproject.toml" in text and 'exit 1' in text, (
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
