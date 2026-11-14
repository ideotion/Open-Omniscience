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
# "# nosec" then ids, then a word that is not an id and no "#" before it: bandit takes the word
# for a test name.
_WORDS_IN_THE_ID_LIST = re.compile(r"#\s*nosec:?\s*((?:B\d{3}[\s,]*)+)[^#\sB,][^#]*$")


def test_no_nosec_reason_is_read_as_a_test_id() -> None:
    offenders = []
    for path in sorted(_SRC.rglob("*.py")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _WORDS_IN_THE_ID_LIST.search(line):
                offenders.append(f"{path.relative_to(_SRC.parent)}:{no}: {line.strip()}")
    assert not offenders, (
        "write the reason after a second '#', as in '# nosec B608 # why', so bandit does not read "
        "it as test ids:\n" + "\n".join(offenders)
    )


def test_the_pattern_tells_the_two_forms_apart() -> None:
    assert _WORDS_IN_THE_ID_LIST.search('x = f"..."  # nosec B608 - names are constants')
    assert _WORDS_IN_THE_ID_LIST.search('x = f"..."  # nosec B608, B611 because')
    assert not _WORDS_IN_THE_ID_LIST.search('x = f"..."  # nosec B608 # names are constants')
    assert not _WORDS_IN_THE_ID_LIST.search('x = f"..."  # nosec B608, B611')
    assert not _WORDS_IN_THE_ID_LIST.search('x = f"..."  # nosec B608')
