"""The [pqc] version ceiling defends itself (2026-09-07).

WHY THIS FILE EXISTS. ``pqcrypto>=0.3.4`` carried no upper bound until 2026-09-03, so when
1.0.0 published the resolver simply took it and the whole repository went red on commits that
touched none of it. The bound was added with its reasoning in a pyproject comment — and
dependabot #996 widened it straight back to ``<2.0`` days later, and that merged. The recorded
lesson is that prose addresses humans and the next reader was a bot: *only a CI-visible
mechanism addresses a bot, and this bound had no test.* This file is that mechanism. It fails
on the PR that widens the ceiling, naming the breakage, instead of the repository going red
later behind a confusing AttributeError on somebody else's unrelated change.

WHAT 1.0.0 ACTUALLY BREAKS, measured against both real wheels installed side by side on
2026-09-07 rather than read off a changelog:

    call site (src/custody/signing.py)   0.4.0    1.0.0
    generate_keypair()                   present  ABSENT — renamed keygen
    verify(pk, data, GOOD_sig)           True     None          <-- bool() is False
    verify(pk, data, BAD_sig)            False    raises InvalidSignatureError
    PUBLIC_KEY_SIZE / key type           1952 / bytes   1952 / bytes  (identical)

The second row is the dangerous one, and it is why this ceiling is a data-safety guard rather
than a housekeeping one. ``signing.py`` verifies with ``bool(_mldsa.verify(...))``, so under
1.0.0 every GENUINE ML-DSA signature verifies as a forgery — silently, in the tamper-evidence
path, on any install whose keys already exist. That path never reaches ``generate_keypair``,
so the loud AttributeError never fires, the module still imports, ``PQC_AVAILABLE`` stays True
and the honest-degrade path never runs either. An inverted predicate, no error, no degrade.

The key FORMAT is unchanged in both versions (plain ``bytes``, 1952), so migrating is a
call-site and return-contract change rather than a key rewrite — but it still touches
PERSISTED key material in the custody chain, so it goes through
``docs/maintenance/EXTERNAL_DEPENDENCIES.md`` and not a bound widening.

SCOPE. ``pqcrypto`` is currently the only upper-bounded requirement anywhere in pyproject
(measured, 2026-09-07); ``mypy==2.3.1`` and the workflows' ``bandit==1.9.4`` are exact pins,
where a bump is a one-line version change a reviewer reads. So this is deliberately one
guarded ceiling rather than a table with one row in it. Whether the ceiling also owes an entry
in ``configs/external_artifacts.yml`` is recorded in CLAUDE.md as an OPEN scope decision and is
deliberately not settled here.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

_ROOT = Path(__file__).resolve().parents[1]

#: The release that inverts verify() and renames generate_keypair. See the module docstring.
_BREAKING = "1.0.0"
#: The newest release the ceiling admits — what a real ``pip install '.[pqc]'`` resolves to.
_SHIPPED = "0.4.0"

_WHY = (
    f"pqcrypto {_BREAKING} renamed generate_keypair -> keygen AND inverted verify(), which "
    "returns None for a VALID signature — so signing.py's bool(_mldsa.verify(...)) reports "
    "every genuine ML-DSA signature as a forgery, silently, in the tamper-evidence path. "
    "Widening this ceiling is a migration, not a version bump: see the module docstring and "
    "docs/maintenance/EXTERNAL_DEPENDENCIES.md."
)


def _pqcrypto_specifier() -> SpecifierSet:
    """The [pqc] extra's pqcrypto constraint, or a loud failure if it is not there.

    ANTI-VACUITY. Every assertion below asks whether a specifier admits some version, and an
    absent requirement yields an empty SpecifierSet that admits everything — so a guard that
    silently tolerated a renamed or deleted requirement would pass hardest at exactly the
    moment the ceiling stopped existing.
    """
    extra = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["pqc"]
    matches = [r for r in (Requirement(spec) for spec in extra) if r.name == "pqcrypto"]
    assert len(matches) == 1, (
        f"expected exactly one pqcrypto requirement in the [pqc] extra, found {len(matches)} "
        f"in {extra}. The ceiling guards in this file have nothing to check without it."
    )
    return matches[0].specifier


def test_the_pqc_ceiling_refuses_the_release_that_inverts_verify() -> None:
    """The load-bearing guard: whatever the constraint is spelled as, it must exclude 1.0.0."""
    spec = _pqcrypto_specifier()
    assert not spec.contains(_BREAKING), (
        f"the [pqc] extra now admits pqcrypto {_BREAKING} (constraint: 'pqcrypto{spec}'). {_WHY}"
    )


def test_the_pqc_ceiling_still_admits_the_version_it_ships() -> None:
    """NEGATIVE-SPACE TWIN, and it is not decoration.

    Over-narrowing satisfies the guard above while breaking the extra just as thoroughly:
    ``==0.3.4`` or ``<0.4`` both exclude 1.0.0 and both quietly drop the release a real
    install resolves to. A ceiling that admits nothing is not a fix, and without this test
    the cheapest way to make the ceiling guard green would be to make the extra useless.
    """
    spec = _pqcrypto_specifier()
    assert spec.contains(_SHIPPED), (
        f"the [pqc] extra no longer admits pqcrypto {_SHIPPED} (constraint: 'pqcrypto{spec}') "
        f"— the newest release below the ceiling, and the one a real install resolves to."
    )


def test_the_installed_pqcrypto_satisfies_the_declared_ceiling() -> None:
    """The declaration is only half the guarantee — check what is actually importable.

    Mirrors ``test_duckdb_version_coupling_holds_when_installed``: a lockfile, a stale
    environment or a manual install can drift from pyproject, and on the PQC lane this is the
    only guard that names the drift as drift. Without it the first symptom is a custody test
    dying on an AttributeError, which reads as a broken test rather than a wrong version.
    """
    try:
        installed = importlib_metadata.version("pqcrypto")
    except importlib_metadata.PackageNotFoundError:
        pytest.skip("pqcrypto is an optional [pqc] extra and is not installed in this lane")
    spec = _pqcrypto_specifier()
    assert spec.contains(installed), (
        f"installed pqcrypto {installed} violates the declared ceiling 'pqcrypto{spec}'. {_WHY}"
    )
