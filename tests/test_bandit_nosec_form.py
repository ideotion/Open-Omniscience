"""A bandit nosec marker in src/ keeps its reason behind a second ``#`` (OPEN_QUEUE 24).

Bandit 1.9.4 reads everything after ``# nosec`` up to the next ``#`` as a list of test ids, so
``# nosec B608 - column names are constants`` printed one "Test in comment" warning per word
into every green CI log (about 3,100 lines). ``# nosec B608 # column names are constants`` ends
the list at the second ``#`` and suppresses exactly the same findings. This guard keeps the old
form from coming back one line at a time.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
# Bandit 1.9.4's own parse (bandit/core/utils.py): the test list is everything after "nosec" up to the
# next "#", and each comma- or space-separated word in it is taken for a test id or name.
_NOSEC = re.compile(r"#\s*nosec:?(?P<tests>[^#]+)?#?", re.IGNORECASE)
_WORD = re.compile(r"[^\s,]+")
_TEST_ID = re.compile(r"B\d{3}")


def _problem(line: str) -> str | None:
    """Why bandit would misread this line's marker, or None when every word in its list is a test id."""
    m = _NOSEC.search(line)
    if m is None:
        return None
    words = _WORD.findall(m.group("tests") or "")
    if not words:
        return "a bare nosec silences every test on the line; name the ids"
    stray = [w for w in words if not _TEST_ID.fullmatch(w)]
    if stray:
        return f"bandit reads {stray[:3]} as test ids"
    return None


def test_no_nosec_reason_is_read_as_a_test_id() -> None:
    offenders = []
    for path in sorted(_SRC.rglob("*.py")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            why = _problem(line)
            if why:
                offenders.append(f"{path.relative_to(_SRC.parent)}:{no}: {why}: {line.strip()}")
    assert not offenders, (
        "write the reason after a second '#', as in '# nosec B608 # why', so bandit does not read "
        "it as test ids:\n" + "\n".join(offenders)
    )


def test_the_check_tells_the_forms_apart() -> None:
    misread = [
        'x = f"..."  # nosec B608 - names are constants',
        'x = f"..."  # nosec B608, B611 because',
        'x = f"..."  # nosec B608 Because the names are constants',
        'x = f"..."  # nosec B608 - see #123',
        'x = f"..."  # nosec b608 - x',
        'x = f"..."  # nosec - reason',
        'x = f"..."  # nosec',
        'x = f"..."  # nosec B6081',
    ]
    for line in misread:
        assert _problem(line), line
    fine = [
        'x = f"..."  # nosec B608 # names are constants',
        'x = f"..."  # nosec B608, B611',
        'x = f"..."  # nosec: B608 # why',
        'x = f"..."  # nosec B608',
        'x = f"..."  # noqa: S608  table is a constant',
    ]
    for line in fine:
        assert _problem(line) is None, line
