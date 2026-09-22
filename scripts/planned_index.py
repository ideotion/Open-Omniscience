#!/usr/bin/env python3
"""Generate the PLANNED-WORK REVERSE INDEX: which file does a decision already own?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (maintainer-asked 2026-09-22): "find a way so that future bug discovery
would not contradict what has been planned ... to help future unaware sessions to become
aware of the changes, and to avoid redoing some thinking that has already been done."

THE GAP IT FILLS. ``shipped.csv`` has a ``key_paths`` column, but it is RETROSPECTIVE: it
says which files WERE touched, never which files a PLANNED decision owns. The rulings index
names paths only sometimes and only in prose. ``CLAUDE.md`` names none of the plan files at
all, and its only grep instruction is "before asking the maintainer anything" -- never
"before editing a file". So a session fixing an unrelated bug has nothing pointing at the
thirty-eight slice briefs that may already have decided the question it is about to answer
for itself. That has already cost the project once: ``LESSONS.md`` records a session that
trusted a stale code comment and spent one of the maintainer's decisions re-ratifying a
setting that was already ruled.

THE KEY IS THE THING A SESSION ACTUALLY DOES -- open a file -- not the thing it must
remember to do. Everything else here follows from that.

WHAT IT REFUSES TO DO. It does not judge whether a change contradicts a plan; it says what
the plan is and where to read it. A generator that guessed would be a composite score over
prose, and would be wrong in the direction that matters (a confident false negative reads
as "nothing is planned here").
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: The repo root. ``--root`` overrides it, which is how the test drives the generator
#: against a fixture tree rather than against the live repository.
ROOT = Path(__file__).resolve().parent.parent
BRIEFS = ROOT / "docs" / "plans" / "2026-09-12-beta-pathway"
GATES = ROOT / "docs" / "product"
RULINGS = ROOT / "docs" / "ledger" / "RULINGS_INDEX.md"
QUEUE = ROOT / "docs" / "ledger" / "OPEN_QUEUE.md"
OUT = ROOT / "docs" / "ledger" / "PLANNED_INDEX.tsv"

COLUMNS = ("path", "id", "kind", "status", "title", "where")

#: A backticked token is a PATH only if it starts at a real top-level directory or is a
#: bare ``*.py``/``*.js`` filename. Anything looser matches prose like `country:` and
#: `normalize_country`, and an index full of those is an index nobody reads.
_ROOTS = ("src/", "tests/", "scripts/", "docs/", "configs/", "alembic/", ".github/")
_PATH = re.compile(r"`([^`\n]+?)`")
_ID_IN_TITLE = re.compile(r"^#\s*(S\d\d-\d\d)\b")
_GATE_ROW = re.compile(r"`(RELEASE_0\.\d_GATE\.md)`\s*row\s*([A-Z0-9]+)", re.I)
#: Only the real prefixes. An earlier cut accepted a bare letter + digits and read "K = 3"
#: in a brief's own scope line as a ruling id -- an index that mislabels its rows is worse
#: than one that leaves them anonymous, because the wrong id sends the reader to the wrong
#: ruling with full confidence.
_RULING_ID = re.compile(r"\b((?:Q|RC|PF|R)\d{1,4})\b")

#: How many QUEUE rows one path may carry. The queue is 14,703 lines and some paths are
#: named in dozens of entries; twenty pointers is the same as none.
_QUEUE_CAP = 3

#: How many rows of ANY kind one path may carry. Over the cap the index keeps the
#: highest-priority ones and emits ONE overflow row carrying the REAL total -- never a
#: silent truncation, which would read as "that is all there is".
_PATH_CAP = 12


def _clean_path(tok: str) -> str | None:
    """A backticked token reduced to a repo path, or None if it is not one."""
    t = tok.strip().strip(",;.()")
    t = t.split(":", 1)[0]  # `csv_io.py:130` -> `csv_io.py`
    if t.startswith(_ROOTS):
        # A BARE ROOT IS NOT AN INDEX KEY. S08-01's scope says "new modules under `src/`",
        # which is true and useless: taken as a directory entry it matched every source
        # file in the tree, so two 0.7/0.8 briefs appeared on every lookup a session ever
        # ran. An index that answers every question the same way answers none of them.
        if t.rstrip("/") in {r.rstrip("/") for r in _ROOTS}:
            return None
        return t
    # A bare filename is useful only when it is UNAMBIGUOUS in the tree; resolve it against
    # a listing walked once. Walking per token cost 4.9 s a run, which is enough for a
    # session to stop reaching for the tool -- and a tool nobody runs is the failure this
    # whole mechanism exists to prevent.
    if re.fullmatch(r"[\w.-]+\.(py|js|json|yml|yaml|md|css|html|tsv|csv)", t):
        hits = _by_name().get(t, ())
        if len(hits) == 1:
            return hits[0]
    return None


_NAMES: dict[str, tuple[str, ...]] | None = None


def _by_name() -> dict[str, tuple[str, ...]]:
    """filename -> every repo-relative path carrying it (walked once per process)."""
    global _NAMES
    if _NAMES is None:
        acc: dict[str, list[str]] = {}
        skip = {".git", "node_modules", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
        for p in ROOT.rglob("*"):
            if p.is_file() and not skip & set(p.parts):
                acc.setdefault(p.name, []).append(str(p.relative_to(ROOT)))
        _NAMES = {k: tuple(v) for k, v in acc.items()}
    return _NAMES


def _paths_in(text: str) -> list[str]:
    out, seen = [], set()
    for tok in _PATH.findall(text):
        p = _clean_path(tok)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


@dataclass(frozen=True)
class Entry:
    path: str
    id: str
    kind: str
    status: str
    title: str
    where: str

    def row(self) -> str:
        return "\t".join(
            v.replace("\t", " ").replace("\n", " ")
            for v in (self.path, self.id, self.kind, self.status, self.title, self.where)
        )


def pending_ruling_ids() -> set[str]:
    """The ruling ids whose OWN row says they are unanswered.

    THE FALSE POSITIVE THIS REPLACES. The first cut marked a slice "blocked" when a ⛔
    appeared anywhere in its header -- but a header reading «Implements: Q301 ⛔ = c» names
    a ⛔-CLASS ruling that is ANSWERED. That marked 241 rows blocked, most of them wrongly,
    and an index that cries blocked on answered work is one a reader learns to scroll past.
    A ruling is blocked here only when its own row in RULINGS_INDEX.md says PENDING."""
    out: set[str] = set()
    for ln in RULINGS.read_text(encoding="utf-8").split("\n"):
        if not ln.startswith("| "):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 5:
            continue
        m = _RULING_ID.match(cells[0].replace("⛔", "").replace("🔒", "").strip())
        if m and ("PENDING" in cells[3] or "PENDING" in cells[4]):
            out.add(m.group(1))
    return out


def _header_block(text: str) -> str:
    """The brief's own blockquote header -- Scope / Implements / Gated on / Sequencing."""
    lines, block = text.split("\n"), []
    for ln in lines:
        if ln.startswith(">"):
            block.append(ln.lstrip("> ").rstrip())
        elif block:
            break
    return " ".join(block)


def from_briefs() -> list[Entry]:
    """A slice brief owns the files its own Scope names -- and, LOUDER, the files its
    'Must NOT touch' names, because that is a decision a later session is most likely to
    cross without knowing it existed."""
    out: list[Entry] = []
    pending = pending_ruling_ids()
    for f in sorted(BRIEFS.glob("S*.md")):
        text = f.read_text(encoding="utf-8")
        first = text.split("\n", 1)[0]
        m = _ID_IN_TITLE.match(first)
        if not m:
            continue
        sid = m.group(1)
        title = first.lstrip("# ").strip()
        where = f"{f.relative_to(ROOT)}"
        header = _header_block(text)

        scope, forbidden = header, ""
        for marker in ("Must NOT touch:", "Must not touch:", "MUST NOT touch:"):
            if marker in header:
                scope, forbidden = header.split(marker, 1)
                break
        # 'Gated on:' names a PRECONDITION, not this slice's own files -- and a slice whose
        # gate is an unanswered question is one no session may start.
        gated = ""
        if "Gated on:" in scope:
            scope, gated = scope.split("Gated on:", 1)
        # Blocked only if a ruling this slice IMPLEMENTS is itself unanswered.
        implements = set(_RULING_ID.findall(header.split("Gated on:")[0]))
        blocked = bool(implements & pending)

        for p in _paths_in(scope):
            out.append(Entry(p, sid, "slice", "slice-blocked" if blocked else "planned", title, where))
        for p in _paths_in(forbidden):
            out.append(Entry(p, sid, "slice", "must-not-touch", title, where))
        for p in _paths_in(gated):
            out.append(Entry(p, sid, "slice", "precondition", title, where))
    return out


def from_gates() -> list[Entry]:
    """A gate row is the release's own promise about a surface."""
    out: list[Entry] = []
    for f in sorted(GATES.glob("RELEASE_0.*_GATE.md")):
        rel = str(f.relative_to(ROOT))
        for n, ln in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if not ln.startswith("| ") or ln.startswith("|---"):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            # A row label is a letter or a digit or two -- never a word. "Gate" in the
            # first cell of a prose table was being indexed as a release row.
            if len(cells) < 3 or not re.fullmatch(r"[A-Z0-9]{1,3}", cells[0]):
                continue
            blocked = "⛔" in ln or "PENDING" in ln or "BLOCKED" in ln
            title = f"row {cells[0]}: {cells[1][:120]}"
            for p in _paths_in(ln):
                out.append(Entry(p, f"{f.stem} row {cells[0]}", "gate-row",
                                 "row-blocked" if blocked else "planned", title, f"{rel}:{n}"))
    return out


def from_rulings() -> list[Entry]:
    """The 'where enforced' column, for the rulings that name a path in it."""
    out: list[Entry] = []
    rel = str(RULINGS.relative_to(ROOT))
    for n, ln in enumerate(RULINGS.read_text(encoding="utf-8").split("\n"), 1):
        if not ln.startswith("| ") or ln.startswith("|---") or ln.startswith("| id "):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 5:
            continue
        rid = cells[0].replace("⛔", "").replace("🔒", "").strip()
        # THE ONLY STATUS THAT SAYS "DO NOT DECIDE THIS YOURSELF": a ruling that names a
        # path and is itself unanswered. A SLICE being blocked means that slice cannot
        # start -- it never means the file is untouchable, and conflating the two made the
        # strict check fire on `src/static/index.html`, which nearly every PR edits.
        blocked = "⛔" in cells[0] or "PENDING" in cells[3] or "PENDING" in cells[4]
        title = cells[2][:160]
        for p in _paths_in(cells[4]):
            out.append(Entry(p, rid, "ruling", "pending-ruling" if blocked else "ruled",
                             title, f"{rel}:{n}"))
    return out


def from_queue() -> list[Entry]:
    """Queue entries that are OPEN -- a pending ruling, a contingency, a deliberate
    omission. Only the entry's own TITLE line is read for the marker, so a passing mention
    of the word PENDING three paragraphs down does not mark a closed entry as open."""
    out: list[Entry] = []
    rel = str(QUEUE.relative_to(ROOT))
    lines = QUEUE.read_text(encoding="utf-8").split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.startswith("- **")]
    for k, i in enumerate(starts):
        j = starts[k + 1] if k + 1 < len(starts) else len(lines)
        body = "\n".join(lines[i:j])
        head = " ".join(lines[i : i + 3])
        open_markers = ("⛔", "PENDING", "NEEDS A RULING", "RULING NEEDED", "STILL OPEN",
                        "UNSTATED", "NOT BUILT", "OPEN QUESTION")
        if not any(m in body[:1200] for m in open_markers):
            continue
        title = re.sub(r"\*\*", "", lines[i].lstrip("- ").strip())[:160]
        rid = (_RULING_ID.search(head) or [None, f"queue:{i + 1}"])[1] if _RULING_ID.search(head) else f"queue:{i + 1}"
        for p in _paths_in(body):
            out.append(Entry(p, rid, "queue", "open", title, f"{rel}:{i + 1}"))
    return out


def build() -> list[Entry]:
    seen: set[tuple] = set()
    out: list[Entry] = []
    queue_per_path: dict[str, int] = {}
    for e in from_briefs() + from_gates() + from_rulings() + from_queue():
        # A gate file naming itself in every one of its own rows is not information.
        if e.path == e.where.split(":")[0]:
            continue
        if e.kind == "queue":
            n = queue_per_path.get(e.path, 0)
            if n >= _QUEUE_CAP:
                continue
            queue_per_path[e.path] = n + 1
        k = (e.path, e.id, e.status)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    # must-not-touch first, then blocked, then the rest: the loudest thing a reader needs.
    order = {"must-not-touch": 0, "pending-ruling": 1, "slice-blocked": 2, "row-blocked": 3,
             "precondition": 4, "open": 5, "planned": 6, "ruled": 7}
    out.sort(key=lambda e: (e.path, order.get(e.status, 9), e.id))

    capped: list[Entry] = []
    i = 0
    while i < len(out):
        j = i
        while j < len(out) and out[j].path == out[i].path:
            j += 1
        group = out[i:j]
        capped.extend(group[:_PATH_CAP])
        if len(group) > _PATH_CAP:
            capped.append(Entry(
                out[i].path, "—", "overflow", "more",
                f"{len(group) - _PATH_CAP} further entries not listed ({len(group)} total for this path)",
                "docs/ledger/RULINGS_INDEX.md + docs/plans/2026-09-12-beta-pathway/",
            ))
        i = j
    return capped


def render(entries: list[Entry]) -> str:
    head = (
        "# GENERATED by scripts/planned_index.py -- do not hand-edit; run the script.\n"
        "# The planned-work REVERSE INDEX: which file does a decision already own?\n"
        "# Query it with: python scripts/planned.py <path>   (or --diff for a changeset)\n"
        "# status: must-not-touch > pending-ruling > slice-blocked > row-blocked >\n"
        "#         precondition > open > planned > ruled\n"
    )
    return head + "\t".join(COLUMNS) + "\n" + "\n".join(e.row() for e in entries) + "\n"


def _set_root(root: Path) -> None:
    """Point every source at another tree (the test fixture, or a worktree)."""
    global ROOT, BRIEFS, GATES, RULINGS, QUEUE, OUT, _NAMES
    global _NAMES
    _NAMES = None
    ROOT = root.resolve()
    BRIEFS = ROOT / "docs" / "plans" / "2026-09-12-beta-pathway"
    GATES = ROOT / "docs" / "product"
    RULINGS = ROOT / "docs" / "ledger" / "RULINGS_INDEX.md"
    QUEUE = ROOT / "docs" / "ledger" / "OPEN_QUEUE.md"
    OUT = ROOT / "docs" / "ledger" / "PLANNED_INDEX.tsv"


def main(argv: list[str]) -> int:
    if "--root" in argv:
        _set_root(Path(argv[argv.index("--root") + 1]))
    out_override = None
    if "--out" in argv:
        out_override = Path(argv[argv.index("--out") + 1])
    entries = build()
    text = render(entries)
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale -- run: python scripts/planned_index.py")
            return 1
        print(f"{OUT.relative_to(ROOT)} is current ({len(entries)} rows)")
        return 0
    dest = out_override or OUT
    dest.write_text(text, encoding="utf-8")
    paths = len({e.path for e in entries})
    print(f"wrote {dest}: {len(entries)} rows over {paths} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
