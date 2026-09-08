"""``_safe_extract``'s containment guard must be ``is_relative_to``, never a string
prefix (audit finding P3-11) -- the same anti-pattern this codebase already documents
by name in ``folder_backup.py``'s ``place_artifact_file_members`` docstring.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from src.backup.artifact import ArtifactError, _safe_extract


def _zip_with_member(name: str, data: bytes = b"PLANTED") -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, data)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def test_traversal_and_absolute_names_are_still_refused_before_containment(tmp_path):
    """The earlier, narrower guards stay in place -- ``..`` in the member name and an
    absolute member name are both refused without ever reaching the containment check."""
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(ArtifactError, match="unsafe member path"):
        _safe_extract(_zip_with_member("../escape.txt"), staging)

    with pytest.raises(ArtifactError, match="unsafe member path"):
        _safe_extract(_zip_with_member("/etc/escape.txt"), staging)


def test_a_symlinked_sibling_sharing_a_string_prefix_is_still_refused(tmp_path):
    """The containment BELT, on the only member shape that actually reaches it: a name
    with no ``..`` and no leading ``/`` (so the earlier guards let it through), whose
    resolved target escapes ``staging`` via a SYMLINK -- to a sibling staging directory
    (``.restore-12``) whose name happens to share ``.restore-1``'s STRING PREFIX.

    Per the docs/ledger/LESSONS.md entry on this exact area (2026-09-07): once the
    ``..``/leading-``/`` guard runs first, a fixture built with ``..`` in it never
    reaches the containment line at all -- a symlinked root/subdirectory is the only
    shape left that does. This fixture is also not incidental: it reproduces the precise
    failure the audit named (``str(target).startswith(str(root))`` treats
    ``.restore-12`` as "starting with" ``.restore-1`` even though it is a SIBLING, not a
    descendant) -- confirmed red under the pre-fix string-prefix check and green only
    under ``is_relative_to`` (verified by hand before this test was added, per the same
    LESSONS.md entry's warning not to trust a green test without checking what it
    actually exercised)."""
    root_dir = tmp_path
    staging = root_dir / ".restore-1"
    sibling = root_dir / ".restore-12"  # shares staging's string prefix, is NOT inside it
    staging.mkdir()
    sibling.mkdir()
    (staging / "sub").symlink_to(sibling, target_is_directory=True)

    with pytest.raises(ArtifactError, match="unsafe member path"):
        _safe_extract(_zip_with_member("sub/evil.txt"), staging)

    assert not (sibling / "evil.txt").exists(), (
        "nothing may be written outside staging, even into a same-string-prefix sibling"
    )


def test_a_member_that_genuinely_stays_inside_staging_still_extracts(tmp_path):
    """The fix must not turn into a false refusal for ordinary, safe members."""
    staging = tmp_path / "staging"
    staging.mkdir()

    _safe_extract(_zip_with_member("sub/ok.txt", b"fine"), staging)

    assert (staging / "sub" / "ok.txt").read_bytes() == b"fine"
