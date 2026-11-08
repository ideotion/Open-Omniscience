"""ci.yml's concurrency block (R612): every merge commit on the default branch gets its own full run, and a PR's new push cancels its old one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A concurrency group holds one running and ONE pending run. With one group per ref, each merge to main replaced the queued run of the merge
before it, so on a busy day most merge commits were never tested on main (GitHub shows them as "cancelled"). The workflow now keys the
default branch's group by the commit sha. These tests evaluate the two expressions for real events rather than matching their text, so an
equivalent rewrite passes and a change in behaviour fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_CI = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
_CONTEXT_NAMES = ("github.event.repository.default_branch", "github.workflow", "github.ref_name", "github.sha", "github.ref")


def _concurrency() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["concurrency"]


def _evaluate(template: str, ctx: dict) -> object:
    """Evaluate a GitHub expression template made only of the contexts above, string literals, ``==``, ``!=``, ``&&``, ``||`` and ``!``.

    Each ``${{ … }}`` becomes a Python expression (``&&``/``||`` keep GitHub's value-returning short-circuit as ``and``/``or``). A template
    that is a single expression returns its value; text around expressions is joined as strings. Anything else is refused, so a new
    construct in the workflow fails here loudly instead of being evaluated wrongly.
    """
    parts = re.split(r"(\$\{\{.*?\}\})", template)
    values = []
    for part in parts:
        if not part.startswith("${{"):
            values.append(part)
            continue
        expr = part[3:-2].strip()
        unknown = [m for m in re.findall(r"\bgithub(?:\.\w+)+", expr) if m not in _CONTEXT_NAMES]
        assert not unknown, f"the concurrency expression reads a context this test does not model: {unknown}"
        expr = re.sub(r"\bgithub(?:\.\w+)+", lambda m: f"ctx[{m.group(0)!r}]", expr)
        expr = expr.replace("&&", " and ").replace("||", " or ")
        expr = re.sub(r"!(?!=)", " not ", expr)
        leftover = re.sub(r"ctx\['[^']+'\]|'[^']*'|==|!=|\band\b|\bor\b|\bnot\b|[()\s]", "", expr)
        assert not leftover, f"the concurrency expression uses something this evaluator does not know: {leftover!r} in {part!r}"
        values.append(eval(expr, {"__builtins__": {}}, {"ctx": ctx}))  # noqa: S307 - only the vetted tokens above remain
    values = [v for v in values if v != ""]
    return values[0] if len(values) == 1 else "".join(str(v) for v in values)


def _ctx(ref: str, sha: str) -> dict:
    return {
        "github.workflow": "CI",
        "github.ref": ref,
        "github.ref_name": ref.removeprefix("refs/heads/").removeprefix("refs/pull/"),  # a PR's ref_name is "<n>/merge"
        "github.sha": sha,
        "github.event.repository.default_branch": "main",
    }


def _group(ref: str, sha: str, **override: str) -> str:
    return str(_evaluate(_concurrency()["group"], {**_ctx(ref, sha), **override}))


def _cancels(ref: str, sha: str, **override: str) -> bool:
    value = _concurrency()["cancel-in-progress"]
    return bool(value if isinstance(value, bool) else _evaluate(value, {**_ctx(ref, sha), **override}))


def test_two_merge_commits_on_main_never_share_a_group_and_neither_is_cancelled():
    first, second = _group("refs/heads/main", "a" * 40), _group("refs/heads/main", "b" * 40)
    assert first != second, "two merges to main share one concurrency group, so the newer one replaces the older one's queued run"
    assert not _cancels("refs/heads/main", "a" * 40), "a run on main can be cancelled by the next merge"


def test_a_pull_requests_pushes_share_one_group_and_the_newer_cancels_the_older():
    ref = "refs/pull/1831/merge"
    assert _group(ref, "a" * 40) == _group(ref, "b" * 40), "a PR's superseded run would no longer be replaced"
    assert _cancels(ref, "a" * 40), "a PR's superseded run would keep holding runners"
    assert _group(ref, "a" * 40) != _group("refs/pull/1832/merge", "a" * 40), "two PRs would cancel each other"


def test_main_and_a_pull_request_on_the_same_commit_do_not_share_a_group():
    sha = "c" * 40
    assert _group("refs/heads/main", sha) != _group("refs/pull/1831/merge", sha)


def test_a_scheduled_run_never_shares_a_group_with_a_merge_to_main():
    """A schedule payload carries no ``repository``, so ``default_branch`` reads empty there: the weekly run falls back to the per-ref group.

    That group is no longer the one main's pushes use, so the cron run and a merge's run cannot cancel or replace each other.
    """
    blank = {"github.event.repository.default_branch": ""}
    scheduled = _group("refs/heads/main", "d" * 40, **blank)
    assert scheduled not in {_group("refs/heads/main", "d" * 40), _group("refs/heads/main", "e" * 40)}
    assert _cancels("refs/heads/main", "d" * 40, **blank), "the per-ref fallback no longer cancels its superseded run"


@pytest.mark.parametrize(
    "template",
    [
        pytest.param("${{ github.workflow }}-${{ github.ref }}", id="the-old-per-ref-group"),
        pytest.param("${{ github.workflow }}-${{ github.sha }}", id="per-commit-everywhere-so-a-PR-stops-cancelling"),
    ],
)
def test_the_tests_catch_the_two_regressions(monkeypatch, template):
    """Each mutant of the group fails one of the tests above; otherwise those tests would pass on a broken workflow."""
    real = _concurrency()
    monkeypatch.setitem(globals(), "_concurrency", lambda: {**real, "group": template})
    with pytest.raises(AssertionError):
        test_two_merge_commits_on_main_never_share_a_group_and_neither_is_cancelled()
        test_a_pull_requests_pushes_share_one_group_and_the_newer_cancels_the_older()
