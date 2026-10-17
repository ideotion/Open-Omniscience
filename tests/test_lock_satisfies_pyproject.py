"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``requirements.lock`` is the hash-verified clean-room install (``lockfile-install`` installs it, then the project with ``--no-deps``), so a pin
OUTSIDE a range ``pyproject.toml`` declares gives an install that violates the manifest and that nothing else catches. Three places already
guard one package each by hand (urllib3, trafilatura, starlette in ``tests/test_external_freshness.py``): each was written after that package's
pin and floor had drifted. This is the same check for EVERY requirement, so the next drift is a red test and not a fourth hand-written guard.

What it checks, and what it deliberately does not (a ratchet, not a policy):
  * every requirement of ``[project].dependencies`` and of every ``[project.optional-dependencies]`` extra whose package the lock pins is
    satisfied by that pin (pre-releases allowed: a pin is what the lock resolved, whatever its tag);
  * every CORE requirement IS pinned, because the first check passes vacuously for a package the lock lacks (the lock is generated with
    ``--extra=analysis`` only, so requirements of the other extras are legitimately absent and are not asserted);
  * the lock pins each package once, because two pins are two installs.
It never asks for a pin to be NEWER, never reads the registry and never edits a range. 39 of today's 60 requirements are pinned (all satisfied);
the other 21 are in extras the lock is not generated for.

The parser reads ``lxml[html-clean]==6.1.1`` and ``uvicorn[standard]==0.49.0`` (pip-compile writes the extras into the pin line). A parser that
stops at the name misses exactly those two core pins: ``test_a_pin_line_with_extras_is_a_pin`` fails without the extras group.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

_ROOT = Path(__file__).resolve().parents[1]

# pip-compile writes `name==1.2.3 \` and, for a requirement with extras, `name[extra]==1.2.3 \`; an environment marker follows a `;`.
_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s\\;]+)", re.M)


def lock_pins(text: str) -> dict[str, list[str]]:
    """Canonical package name -> every version the lock pins for it (more than one is a defect)."""
    pins: dict[str, list[str]] = {}
    for m in _PIN.finditer(text):
        pins.setdefault(canonicalize_name(m.group(1)), []).append(m.group(2))
    return pins


def requirements_by_group(pyproject_text: str) -> dict[str, list[Requirement]]:
    data = tomllib.loads(pyproject_text)["project"]
    groups: dict[str, list[Requirement]] = {"core": [Requirement(s) for s in data.get("dependencies", [])]}
    for extra, reqs in data.get("optional-dependencies", {}).items():
        groups[f"extra:{extra}"] = [Requirement(s) for s in reqs]
    return groups


def violations(groups: dict[str, list[Requirement]], pins: dict[str, list[str]]) -> tuple[list[str], int]:
    """(problems, number of requirements compared). A problem is a sentence naming the package, the range, the pin and the group."""
    problems: list[str] = []
    compared = 0
    for group, reqs in groups.items():
        for req in reqs:
            name = canonicalize_name(req.name)
            found = pins.get(name)
            if not found:
                if group == "core":
                    problems.append(f"core requirement {req} is not pinned in requirements.lock")
                continue
            if len(found) > 1:
                problems.append(f"requirements.lock pins {name} {len(found)} times ({', '.join(found)})")
                continue
            compared += 1
            if not req.specifier.contains(Version(found[0]), prereleases=True):
                problems.append(f"requirements.lock pins {name}=={found[0]}, outside pyproject's {req} ({group})")
    return problems, compared


def test_every_lock_pin_satisfies_every_pyproject_range():
    groups = requirements_by_group((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pins = lock_pins((_ROOT / "requirements.lock").read_text(encoding="utf-8"))
    problems, compared = violations(groups, pins)
    assert not problems, "the lock and the manifest disagree: " + "; ".join(problems)
    core = len(groups["core"])
    assert compared >= core, f"only {compared} requirements were compared and the core alone has {core}: the parser stopped finding pins"


# --- the checker itself, on planted inputs (red without the code it exercises) -------------------------------------------------------

_LOCK = (
    "alpha==1.4.0 \\\n    --hash=sha256:aa\n    # via open-omniscience\n"
    "lxml[html-clean]==6.1.1 \\\n    --hash=sha256:bb\n"
    "uvicorn[standard]==0.49.0 \\\n    --hash=sha256:cc\n"
    "Some_Pkg==2.0.0rc1 ; python_version >= '3.9' \\\n    --hash=sha256:dd\n"
)


def _groups(*lines: str, extra: tuple[str, ...] = ()) -> dict[str, list[Requirement]]:
    return {"core": [Requirement(s) for s in lines], "extra:x": [Requirement(s) for s in extra]}


def test_a_pin_line_with_extras_is_a_pin():
    pins = lock_pins(_LOCK)
    assert pins["lxml"] == ["6.1.1"] and pins["uvicorn"] == ["0.49.0"]
    assert pins["some-pkg"] == ["2.0.0rc1"], "names are canonical (case, underscore) and a marker after the version is not part of it"
    assert "alpha" in pins and "hash" not in pins


def test_a_pin_below_the_floor_is_a_violation():
    problems, compared = violations(_groups("alpha>=1.5"), lock_pins(_LOCK))
    assert compared == 1 and len(problems) == 1 and "alpha==1.4.0" in problems[0] and "alpha>=1.5" in problems[0]


def test_a_pin_above_the_ceiling_is_a_violation():
    problems, _ = violations(_groups("alpha>=1.0,<1.4"), lock_pins(_LOCK))
    assert len(problems) == 1 and "alpha==1.4.0" in problems[0] and str(Requirement("alpha>=1.0,<1.4")) in problems[0]


def test_a_satisfied_range_and_a_prerelease_pin_pass():
    problems, compared = violations(_groups("alpha>=1.4", "uvicorn[standard]>=0.27", "lxml>=5.2", "some_pkg>=1.0"), lock_pins(_LOCK))
    assert not problems and compared == 4


def test_a_core_requirement_the_lock_lacks_is_a_violation_but_an_extra_one_is_not():
    problems, compared = violations(_groups("alpha>=1.0", "beta>=1", extra=("gamma>=1",)), lock_pins(_LOCK))
    assert compared == 1
    assert problems == ["core requirement beta>=1 is not pinned in requirements.lock"]


def test_two_pins_for_one_package_are_a_violation():
    lock = _LOCK + "alpha==1.9.0 \\\n    --hash=sha256:ee\n"
    problems, _ = violations(_groups("alpha>=1.0"), lock_pins(lock))
    assert len(problems) == 1 and "2 times" in problems[0]


def test_the_checker_reads_the_real_files_to_a_known_shape():
    """The two core pins whose lines carry extras are found in the real lock (the parser's own tell)."""
    pins = lock_pins((_ROOT / "requirements.lock").read_text(encoding="utf-8"))
    assert "lxml" in pins and "uvicorn" in pins
