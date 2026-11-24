"""Every network-starting action's consent gate fails CLOSED (R822, row 401).

``ensureOnline`` and ``ensureAiEgress`` (app-core.js) are the gates every action that starts network activity awaits;
each wraps its consent step (``_ensureOnlineAsk`` / ``_ensureAiEgressAsk``) so that only an explicit yes starts the
action, and a step that is missing, throws, or answers anything else starts nothing and says why. Eighteen callers used
to test the gate optionally (``typeof ensureOnline === "function" && !await ensureOnline(...)``), so a missing gate
STARTED the action; each now fails closed.

The behaviour is driven as real code in ``consent_gate_node_test.js``. This file runs it, and holds the source so the
optional shapes cannot come back: no ``typeof <gate> === "function" &&``, no optional call ``<gate>?.(``, no
``window.<gate> &&``, no ``.catch`` on a gate's answer, no direct call of a consent step outside its gate, and every
remaining ``typeof <gate>`` test is a fail-closed form (``!== "function" ||``, or ``!== "function") return false``).
"""

from __future__ import annotations

import pathlib
import re
import subprocess

from tests.js_source_helper import function_body

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
_GATES = ("ensureOnline", "ensureAiEgress")
_STEPS = {"_ensureOnlineAsk": "ensureOnline", "_ensureAiEgressAsk": "ensureAiEgress"}


def _sources() -> dict[str, str]:
    out = {}
    for path in sorted(_STATIC.rglob("*.js")):
        rel = path.relative_to(_STATIC).as_posix()
        if "/vendor/" in "/" + rel:
            continue
        out[rel] = path.read_text(encoding="utf-8")
    return out


def _code(src: str) -> str:
    """The source with // and /* */ comments blanked (a comment that NAMES a pattern is not one)."""
    src = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'\\])//[^\n]*", lambda m: m.group(1), src)


def test_the_gates_fail_closed_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "consent_gate_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "consent_gate_node_test.js: OK" in proc.stdout


def test_no_optional_gate_shape_is_left_in_the_ui():
    hits = []
    for rel, src in _sources().items():
        code = _code(src)
        for gate in _GATES:
            for pattern in (
                rf'typeof\s+(?:window\.)?{gate}\s*===?\s*["\']function["\']',
                rf"\b{gate}\s*\?\.",
                rf"window\.{gate}\s*&&",
                rf"\b{gate}\s*&&",
                rf"\b{gate}\([^;]*?\)\s*\.catch\(",
            ):
                hits += [f"{rel}: {m.group(0)}" for m in re.finditer(pattern, code)]
            for m in re.finditer(rf"typeof\s+(?:window\.)?{gate}\b[^\n]*", code):
                if not re.match(
                    rf'typeof\s+{gate}\s*!==\s*"function"\s*(\|\||\)\s*return\s+false\b|$)',
                    m.group(0),
                ):
                    hits.append(f"{rel}: {m.group(0)[:80]}")
    assert not hits, (
        "an optional consent gate starts the action when the gate is missing:\n" + "\n".join(hits)
    )


def test_a_consent_step_is_called_only_by_its_own_gate():
    core = _code((_STATIC / "app-core.js").read_text(encoding="utf-8"))
    for step, gate in _STEPS.items():
        assert f"async function {step}(" in core, step + " is gone: the gate has nothing to wrap"
        calls = [
            m.start()
            for m in re.finditer(rf"\b{step}\(", core)
            if not core[: m.start()].endswith("function ")
        ]
        assert len(calls) == 1, f"{step} is called {len(calls)} times; only {gate} may call it"
        assert re.search(rf"\b{step}\(", function_body(core, gate)), (
            f"the one call of {step} is inside {gate}"
        )
    for rel, src in _sources().items():
        if rel == "app-core.js":
            continue
        for step in _STEPS:
            assert step not in _code(src), f"{rel} calls the consent step {step} past its gate"


def test_only_an_explicit_yes_passes_each_gate():
    core = _code((_STATIC / "app-core.js").read_text(encoding="utf-8"))
    for _step, gate in _STEPS.items():
        body = function_body(core, gate)
        assert "answer === true" in body and "catch" in body, (
            gate + " must pass only true and swallow a throw as a no"
        )
        assert (
            'toast(t("The network consent step did not complete, so nothing was started."), "err")'
            in body
        )
