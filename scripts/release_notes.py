#!/usr/bin/env python3
"""
Release notes generated from ``docs/ledger/shipped.csv`` (Q111 = a, 2026-09-15).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q111 = a: "Tag + GitHub release notes generated from ``shipped.csv`` since the previous
tag + the no-telemetry re-check stated in the notes (the per-release ritual already in
``CLAUDE.md``)." This is the generator ``.github/workflows/release.yml`` calls where the
notes are produced; the workflow's fixed install / SHA-256 block is untouched, as is the
``v*`` trigger, the pre-release rule and the tag step.

EVERY LINE IT EMITS TRACES TO A ROW. Nothing is summarised into prose and nothing is
invented: a bullet quotes a row's ``area``, ``item``, ``date``, ``status`` and ``refs``
verbatim, and where a field is too long to print whole the truncation is marked with `…`
and DISCLOSED once, with the full text one lookup away in the CSV. The section headings
are the only derived text, and the document says how they were derived.

WHAT IT REFUSES, AND WHY EACH REFUSAL IS THE SAFE DIRECTION:

* **A dirty tree.** Notes are a permanent citation; generating them from a tree that does
  not match any commit makes the SHA they name a lie.
* **A shallow clone.** CLAUDE.md protocol rule (5b) records what this costs: a 56-commit
  clone answered ``#944`` for ten different rows because the search kept reporting its own
  truncation point, with nothing to distinguish that from a real answer. Here the
  truncation would move the *previous tag* and therefore the whole row selection. The
  generator unshallows once and REFUSES if the clone is still shallow — never quietly
  produces a range computed from a boundary artifact.
* **A ``PR pending`` placeholder in a row it would cite.** Protocol rule (5b): the
  placeholder is "a PLACEHOLDER, not a value". Publishing one into a release body makes a
  permanent citation out of a to-do. The check is COLUMN-AWARE, per the 2026-09-11 lesson
  that a line-grep for the phrase matches the ledger row that records the phrase's own
  removal — it reads the ``refs`` FIELD, never the file.
* **A telemetry re-check it could not run.** ``--telemetry-check=run`` (the default)
  refuses rather than degrading, because a degrade here would become the hiding place for
  the one claim the ritual exists to re-confirm. ``--telemetry-check=skip`` writes an
  explicit NOT RE-CHECKED line — an omitted section would read as "nothing to say".
* **A verification bar it cannot read from the gate.** The sentence is not mirrored here:
  it is read from ``docs/product/RELEASE_0.4_GATE.md`` behind a marker, so the gate stays
  the single place it lives. A copy would fail in the safe-looking direction — the gate
  could be reworded and this generator would go on quoting the old wording.

THE SELECTION RULE, stated so a reader can check it (brief S04-15 §6 leaves it revisable):

    prev  = the committer date (UTC, day resolution) of the commit the PREVIOUS v* tag
            points at; tagd = the same for the tag being released.
    IN RANGE   prev <  row.date <= tagd        -> the body
    BOUNDARY   row.date == prev                -> its own labelled section
    AFTER TAG  row.date >  tagd                -> counted, named, not in the body
    UNDATED    row.date is not YYYY-MM-DD      -> counted, never included

``shipped.csv`` records DAYS, not times, so a row dated on the previous tag's own day may
have landed on either side of it. Neither dropping it (which loses shipped work) nor
folding it into the body (which claims work for the wrong release) is honest, so it gets
its own section and says which ambiguity put it there. The same day-resolution reasoning
makes ``row.date == tagd`` an inclusion rather than an ambiguity: the tag is cut from the
tree at the end of its own day's work.

Usage::

    python3 scripts/release_notes.py --tag v0.4.0 -o release_notes_body.md
    python3 scripts/release_notes.py --tag v0.4.0 --telemetry-check skip   # local dry run
    python3 scripts/release_notes.py --tag v0.4.0 --json                   # the accounting
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CSV = _ROOT / "docs" / "ledger" / "shipped.csv"
_CONSENT_TEST = _ROOT / "tests" / "test_network_consent.py"
_GATE = _ROOT / "docs" / "product" / "RELEASE_0.4_GATE.md"

#: The marker the verification bar sits behind in the gate file. A rename makes the
#: generator REFUSE by name rather than quote a sentence that has moved.
_BAR_MARKER = "<!-- release-notes: verification-bar -->"

#: A row's ``date`` is only usable as a range key in this exact shape.
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Measured over ALL 997 rows of the real ledger on 2026-09-15: ``item`` runs to 3,970
#: characters, ``status`` to 490, ``refs`` to 365 and ``area`` to 145. (An earlier
#: comment here said 2,523 / 372 — true of the 244 rows in one tag's range, written as
#: though it described the file. A measurement carries its population or it is a guess.)
#: Printing any of them whole turns the notes into the CSV. The cap bounds what is
#: LISTED and is disclosed in the accounting — it never bounds a reported COUNT.
_ITEM_CAP = 200
_STATUS_CAP = 60


class ReleaseNotesError(Exception):
    """A refusal. The notes cannot be produced honestly from this input."""


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #
def _git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=_ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    if check and proc.returncode != 0:
        raise ReleaseNotesError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def require_clean_tree() -> None:
    """Refuse on a dirty tree: the notes name a SHA, so they must describe that SHA."""
    dirty = _git("status", "--porcelain")
    if dirty:
        raise ReleaseNotesError(
            "the working tree is dirty; release notes name a commit and must describe "
            "it. Commit or stash first:\n" + dirty
        )


def ensure_unshallow() -> bool:
    """Unshallow once if needed; refuse if the clone is still truncated.

    Returns True when this call performed the unshallow. A truncated history silently
    moves the previous tag, which silently moves every row the notes claim — the exact
    shape CLAUDE.md rule (5b) records as "ten identical, wrong, authoritative-looking
    PR numbers".
    """
    if _git("rev-parse", "--is-shallow-repository") != "true":
        return False
    _git("fetch", "--unshallow", "--tags", check=False)
    if _git("rev-parse", "--is-shallow-repository") == "true":
        raise ReleaseNotesError(
            "the clone is SHALLOW and could not be unshallowed. Every answer about "
            "'the previous tag' would be this clone's truncation point rather than a "
            "fact about the history (CLAUDE.md protocol rule 5b). Run "
            "`git fetch --unshallow --tags` with network access, or check out with "
            "fetch-depth: 0."
        )
    return True


def resolve_tag(tag: str | None) -> str:
    """The tag being released: given, or the one HEAD is exactly at."""
    if tag:
        if _git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", check=False) == "":
            raise ReleaseNotesError(f"no such tag in this clone: {tag}")
        return tag
    exact = _git("describe", "--tags", "--exact-match", "HEAD", check=False)
    if not exact:
        raise ReleaseNotesError(
            "HEAD is not at a tag; pass --tag vX.Y.Z (the notes must name the release "
            "they describe)"
        )
    return exact


def previous_tag(tag: str) -> str | None:
    """The nearest ``v*`` tag on the tag's FIRST-PARENT history, excluding itself.

    ``--first-parent`` is the ruling, not a detail: without it, ``git describe`` walks
    into merged side branches, and a ``v*`` tag that only ever existed on one of them
    is named as "the previous release". Demonstrated on a constructed history — a tag
    cut on a side branch and merged in is what the plain form returns, while the
    first-parent form correctly finds nothing there. CLAUDE.md rule (5b)'s own
    archaeology is first-parent for the same reason: the mainline is what released.
    Re-checked against this repo's real tags, where both forms answer ``v0.2.0``.

    ``None`` means this is the first tagged release on that history — a real state,
    reported as such rather than silently treated as "everything".
    """
    prev = _git(
        "describe", "--tags", "--abbrev=0", "--first-parent", "--match", "v*",
        f"{tag}^", check=False,
    )
    return prev or None


def utc_day(iso: str) -> str:
    """One ISO-8601 timestamp WITH an offset -> its UTC calendar day.

    Split out so the conversion is one pure, testable step rather than an argument to
    ``git log``. A timestamp with no offset is REFUSED: reading it as local time is
    exactly the defect below, wearing a default.
    """
    try:
        stamp = datetime.fromisoformat(iso.strip())
    except ValueError as exc:
        raise ReleaseNotesError(f"not an ISO-8601 committer date: {iso!r}") from exc
    if stamp.tzinfo is None:
        raise ReleaseNotesError(
            f"committer date carries no timezone: {iso!r} — refusing rather than "
            "assuming the local one, which is the whole defect this guards"
        )
    return stamp.astimezone(UTC).date().isoformat()


def commit_day(ref: str) -> str:
    """The committer date of the commit a ref points at, as a **UTC** calendar day.

    UTC EXPLICITLY, and the reason is a defect live-reproduced through this very
    function rather than reasoned about: ``git log --date=format-local`` renders in the
    PROCESS's timezone, so `v0.3.0` — committed ``2026-08-23T14:39:48+02:00``, i.e.
    12:39 UTC — reads **2026-08-23** under ``TZ=UTC0`` and **2026-08-24** under
    ``TZ=Pacific/Auckland``. That is a different cutoff day, and therefore a different
    set of ledger rows claimed by the same release, decided by whichever machine
    happened to generate the notes. A CI runner is UTC and would never have shown it.

    ``%cI`` carries the commit's own offset, so the conversion happens here, once, and
    gives the same answer everywhere.
    """
    return utc_day(_git("log", "-1", "--format=%cI", ref))


# --------------------------------------------------------------------------- #
# the ledger
# --------------------------------------------------------------------------- #
def read_rows(path: Path) -> list[dict[str, str]]:
    """Read ``shipped.csv`` in BINARY and parse it with the csv module.

    Binary because the file is mixed CRLF / LF and carries ``merge=union``: a
    ``read_text`` round trip normalises line endings, which the recorded 2026-08-11 and
    2026-09-10 lessons both cost a session. Nothing here writes the file — the binary
    read is so the parse sees exactly the bytes on disk, including a quoted field that
    spans lines, which ``csv`` handles and a line split does not.
    """
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = [dict(r) for r in reader]
    if not rows:
        raise ReleaseNotesError(f"{path} holds no rows")
    missing = {"date", "area", "item", "status", "refs"} - set(rows[0])
    if missing:
        raise ReleaseNotesError(f"{path} is missing column(s): {sorted(missing)}")
    return rows


def refs_carry_placeholder(row: dict[str, str]) -> bool:
    """Does this row's ``refs`` FIELD still carry the rule-(5b) placeholder?

    Column-aware on purpose. The 2026-09-11 lesson: a whole-file grep for the phrase
    matches the ledger row whose SUMMARY records the phrase being retired, so the check
    has to read the field the defect lives in, never the file.
    """
    return "pending" in (row.get("refs") or "").lower()


@dataclass
class Selection:
    """What the selection rule made of every row in the ledger."""

    tag: str
    tag_day: str
    prev_tag: str | None
    prev_day: str | None
    in_range: list[dict[str, str]] = field(default_factory=list)
    boundary: list[dict[str, str]] = field(default_factory=list)
    after_tag: list[dict[str, str]] = field(default_factory=list)
    undated: list[dict[str, str]] = field(default_factory=list)

    @property
    def cited(self) -> list[dict[str, str]]:
        """The rows the notes will quote — the only ones a placeholder can reach."""
        return [*self.in_range, *self.boundary]


def select(rows: list[dict[str, str]], sel: Selection) -> Selection:
    for row in rows:
        day = (row.get("date") or "").strip()
        if not _ISO_DAY.match(day):
            sel.undated.append(row)
        elif day > sel.tag_day:
            sel.after_tag.append(row)
        elif sel.prev_day is not None and day == sel.prev_day:
            sel.boundary.append(row)
        elif sel.prev_day is None or day > sel.prev_day:
            sel.in_range.append(row)
        # else: strictly before the previous tag's day — a previous release's row.
    return sel


def refuse_placeholders(sel: Selection) -> None:
    offenders = [r for r in sel.cited if refs_carry_placeholder(r)]
    if offenders:
        lines = "\n".join(
            f"  {r.get('date')} · {r.get('area')} · refs={r.get('refs')!r}"
            for r in offenders
        )
        raise ReleaseNotesError(
            f"{len(offenders)} row(s) this release would cite still carry a `PR pending` "
            "placeholder in their `refs` column. Protocol rule (5b): that is a "
            "PLACEHOLDER, not a value — sweep it to the real PR number before the tag, "
            "or the release notes make a permanent citation out of a to-do.\n" + lines
        )


# --------------------------------------------------------------------------- #
# the no-telemetry re-check (CLAUDE.md's per-release ritual)
# --------------------------------------------------------------------------- #
def outbound_call_sites(path: Path = _CONSENT_TEST) -> tuple[dict[str, str], tuple[str, ...]]:
    """Read the ratchet's own allowlist out of the test that enforces it.

    NOT a mirror. The recorded 2026-09-10 lesson: a hardcoded copy of a value that lives
    in another file fails in the safe-looking direction — the source widens, the copy
    stays narrow, and the check keeps passing while the claim stops being true. A shape
    this parser cannot read is a REFUSAL, never a fall back to a last-known value.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: dict[str, str] | None = None
    covered: tuple[str, ...] | None = None
    for node in tree.body:
        target, value = None, None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target is None or value is None:
            continue
        if target not in ("_ALLOWED_SOCKET_IMPORTERS", "_SOCKET_CAPABLE_MODULES"):
            continue
        try:
            literal = ast.literal_eval(value)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
            # A dict() call, a comprehension or an f-string value is a shape this
            # reader cannot evaluate. The docstring promises a REFUSAL; letting
            # literal_eval's own ValueError escape gives a traceback and an exit code
            # this tool never chose, which in a CI log reads as a crash rather than as
            # the actionable "go re-derive the reader" it is.
            raise ReleaseNotesError(
                f"{path}: `{target}` is not a literal this reader can evaluate "
                f"({type(exc).__name__}: {exc}). It is the list of outbound call sites "
                "the notes must state; re-derive the reader against the file's new "
                "shape rather than letting this generator guess."
            ) from exc
        if target == "_ALLOWED_SOCKET_IMPORTERS":
            sites = literal
        else:
            covered = tuple(literal)
    if not isinstance(sites, dict) or not sites:
        raise ReleaseNotesError(
            f"could not read `_ALLOWED_SOCKET_IMPORTERS` out of {path}. It is the list "
            "of outbound call sites the notes must state, and this generator will not "
            "fall back to a copy — re-derive the reader against the file's new shape."
        )
    if not covered:
        raise ReleaseNotesError(
            f"could not read `_SOCKET_CAPABLE_MODULES` out of {path}; the notes would "
            "claim a coverage they cannot name."
        )
    return sites, covered


@dataclass
class TelemetryCheck:
    """What was actually measured — never a template, and never a bare boolean."""

    mode: str
    command: list[str] | None = None
    returncode: int | None = None
    summary: str | None = None

    @property
    def ran(self) -> bool:
        return self.returncode is not None


#: pytest's own summary vocabulary. CASE-INSENSITIVE on purpose: pytest writes
#: ``ERROR: file or directory not found: ...`` in capitals, on STDERR, and a
#: case-sensitive pattern reads straight past the one line that says what went wrong.
_SUMMARY_LINE = re.compile(r"^.*\b(passed|failed|error|errors|no tests ran)\b.*$", re.M | re.I)


def run_telemetry_check(mode: str, node: str) -> TelemetryCheck:
    """Run the socket-importer ratchet and report exactly what happened."""
    if mode == "skip":
        return TelemetryCheck(mode="skip")
    cmd = [sys.executable, "-m", "pytest", "-q", node]
    try:
        proc = subprocess.run(
            cmd, cwd=_ROOT, capture_output=True, text=True, encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - environment failure
        raise ReleaseNotesError(
            f"could not run the no-telemetry ratchet ({' '.join(cmd)}): {exc}. The "
            "per-release ritual re-confirms a legally-binding claim; this generator "
            "will not state it without a run. Use --telemetry-check skip to say "
            "plainly that it was not re-checked."
        ) from exc
    # STDOUT FIRST, as its own stream. The first cut concatenated stdout + stderr and
    # scanned BACKWARD for the last keyword match -- and since stderr text always lands
    # after stdout text in that concatenation regardless of when it was actually
    # written, an unrelated interpreter-shutdown ResourceWarning on stderr silently
    # became "the result" of a legally-binding no-telemetry re-check. pytest writes its
    # verdict to stdout; stderr is the fallback for the case where it never got that
    # far (a missing node, an import error), and the stream is NAMED either way so a
    # reader can tell which one answered.
    def _last_match(blob: str) -> str:
        for line in reversed(blob.splitlines()):
            if _SUMMARY_LINE.match(line):
                return line.strip().strip("= ")
        return ""

    summary = _last_match(proc.stdout or "")
    err = _last_match(proc.stderr or "")
    if not summary:
        # pytest never got as far as a verdict (a missing node, an import error).
        summary = err or "(pytest produced no summary line)"
    elif proc.returncode != 0 and err and err != summary:
        # A FAILED run keeps both: stdout carries the verdict ("no tests ran in 0.10s")
        # and stderr usually carries the REASON ("ERROR: file or directory not found").
        # Reporting only the first is true and useless; only the second lets an
        # unrelated warning stand in for the result. Gated on a non-zero exit, so a
        # passing run's stray warning can never reach the notes at all.
        summary = f"{summary} — stderr: {err}"
    return TelemetryCheck(
        mode=mode, command=cmd, returncode=proc.returncode, summary=summary
    )


# --------------------------------------------------------------------------- #
# the verification bar (read from the gate, never mirrored)
# --------------------------------------------------------------------------- #
def verification_bar(path: Path = _GATE) -> str:
    """The one sentence every surface cites, read from the gate file behind its marker.

    THE MARKER IS MATCHED AS A WHOLE LINE, and this is the load-bearing part rather
    than a tidy-up. The first cut used ``text.find(_BAR_MARKER)`` and broke the SAME
    DAY it was written: the gate's own board table gained a row-status line saying
    *"the citable sentence lives in §2 row F behind `<!-- release-notes:
    verification-bar -->`"* — an entirely natural sentence to write in the file that
    DEFINES the mechanism — and ``find`` locked onto that prose mention 270 lines above
    the real marker, found no blockquote after it, and refused. In ``release.yml``,
    under ``set -euo pipefail``, that refusal blocks the whole release-publish step.

    It is the recorded trap of a guard satisfied by its own explanation, and the
    recorded repair applies unchanged: **never reword the prose** — that sentence is
    what a future reader needs — scope the match to the syntactic form the real thing
    takes. A marker on its own line cannot be a mid-sentence mention, and requiring
    EXACTLY ONE means a second real marker is a loud refusal rather than a silent pick.
    """
    text = path.read_text(encoding="utf-8")
    lines_all = text.splitlines()
    hits = [i for i, line in enumerate(lines_all) if line.strip() == _BAR_MARKER]
    if not hits:
        raise ReleaseNotesError(
            f"{path} carries no line that is exactly {_BAR_MARKER!r}. The verification "
            "bar (Q1128 = a) lives in the gate and is quoted from there; this generator "
            "will not mirror it. (A mention of the marker inside a sentence is "
            "deliberately NOT a match.)"
        )
    if len(hits) > 1:
        raise ReleaseNotesError(
            f"{path} carries {len(hits)} lines that are exactly {_BAR_MARKER!r} "
            f"(lines {', '.join(str(i + 1) for i in hits)}). The bar has ONE home; "
            "refusing rather than silently picking one of them."
        )
    # The contiguous blockquote that immediately follows the marker, blank lines
    # between the two tolerated. Anything else ends the quote.
    lines: list[str] = []
    for line in lines_all[hits[0] + 1:]:
        if not line.strip() and not lines:
            continue
        if line.startswith(">"):
            lines.append(line[1:].strip())
            continue
        break
    bar = " ".join(x for x in lines if x)
    if not bar:
        raise ReleaseNotesError(
            f"{path}: the {_BAR_MARKER!r} marker is not followed by a blockquote holding "
            "the bar. Refusing rather than quoting nothing."
        )
    return bar


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
#: Every line ending CommonMark recognises — including a LONE ``\r``, which is a valid
#: line ending there and which a ``\r\n``-then-``\n`` pair of replacements walks past.
_LINE_ENDINGS = re.compile(r"\r\n|\r|\n")

#: The characters that let a ledger field restructure the document it is printed in.
#: ``\`` first, so the escapes added below are not themselves re-escaped.
_MD_STRUCTURAL = ("\\", "`", "<", ">")


def _flatten(value: str) -> str:
    """One field's raw text as ONE line, still verbatim."""
    return _LINE_ENDINGS.sub(" ", value or "").strip()


def _md_text(value: str) -> str:
    """A ledger field, safe to interpolate into Markdown, with its text preserved.

    Ledger fields are PROSE written by sessions, not markup, and three shapes in them
    can restructure the release body. All three were verified against the real ledger
    rather than imagined:

    * a **backtick** opens a code span that closes at the next backtick run *anywhere
      later in the document* — so one stray backtick swallows the following bullet's
      own ``- `` list marker and that row stops being a list item. Today's 997 rows all
      carry even counts, so this is latent by luck, not by any guard.
    * a **newline** in ``area`` or ``refs`` (which are not clipped, so nothing was
      flattening them) ends the list item, and the next line at column 0 starting ``# ``
      is a real ATX heading in the release body.
    * **angle brackets** are inline raw HTML. Ten real rows carry them today, including
      one whose ``item`` names ``<style>``/``<script>`` — raw-text elements that swallow
      everything up to a closing tag this document does not contain.

    Backslash-escaping is the repair that keeps the text: ``\\```, ``\\<`` and ``\\>``
    render as the literal characters and carry no structure. Nothing is dropped, so a
    reader sees what the ledger says.
    """
    out = _flatten(value)
    for ch in _MD_STRUCTURAL:
        out = out.replace(ch, "\\" + ch)
    return out


def _code_span(value: str) -> str:
    """``value`` as a Markdown code span, fenced long enough to contain it.

    A code span ignores backslash escapes, so ``_md_text`` cannot be used here. The
    CommonMark construction instead: a fence one backtick longer than the longest run
    inside, padded with spaces when the content starts or ends with one. ``area`` has
    never contained a backtick in 997 rows — this is so that the day one does, the
    field renders rather than breaking the line.
    """
    runs = max((len(m) for m in re.findall(r"`+", value)), default=0)
    fence = "`" * (runs + 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{pad}{value}{pad}{fence}"


def _clip(value: str, cap: int) -> tuple[str, bool]:
    """Flatten, then clip to ``cap`` and mark the clip. Escaping happens AFTER.

    The cap is measured on the SOURCE text, never on the escaped form: escaping is
    invisible to a reader, so charging it against a length budget would silently clip
    two fields of the same real length differently depending on their punctuation.
    """
    value = _flatten(value)
    if len(value) <= cap:
        return value, False
    return value[: cap - 1].rstrip() + "…", True


def _section_of(area: str) -> str:
    """The derived heading: the ``area`` column's first path segment.

    Derived, and the document says so. The ledger carries 172 distinct ``area`` values in
    a single release's range, so one heading per area is a table of contents rather than
    a document; the FULL area still travels on every bullet, so nothing is lost.
    """
    seg = (area or "").split("/", 1)[0].strip()
    return seg or "(no area)"


def group_rows(
    rows: list[dict[str, str]], group_by: str
) -> "OrderedDict[str, list[dict[str, str]]]":
    key = (lambda r: (r.get("area") or "(no area)").strip()) if group_by == "area" else (
        lambda r: _section_of(r.get("area") or "")
    )
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    out: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for name in sorted(groups, key=str.lower):
        out[name] = sorted(
            groups[name], key=lambda r: ((r.get("area") or ""), (r.get("date") or ""))
        )
    return out


def _bullet(row: dict[str, str], clipped: dict[str, int]) -> str:
    """One row as one bullet. EVERY interpolated field goes through a sanitiser.

    The first cut flattened only ``item`` and ``status`` — because those are the two
    that are clipped, and the flattening happened to live inside ``_clip``. ``area``
    and ``refs`` were interpolated raw, which is how a newline in either one escaped
    the bullet entirely. Fields are handled by what they ARE, never by whether some
    other function happened to touch them on the way past.
    """
    raw_area = _flatten(row.get("area") or "")
    item, item_clipped = _clip(row.get("item") or "", _ITEM_CAP)
    status, status_clipped = _clip(row.get("status") or "", _STATUS_CAP)
    refs = _md_text(row.get("refs") or "")
    date = _flatten(row.get("date") or "")
    if item_clipped:
        clipped["item"] += 1
    if status_clipped:
        clipped["status"] += 1
    item, status = _md_text(item), _md_text(status)
    parts = [f"{_code_span(raw_area)} — {item}" if raw_area else item]
    tail = [p for p in (date, status, refs) if p]
    if tail:
        parts.append(" · ".join(tail))
    return "- " + " — ".join(parts)


def render(
    sel: Selection,
    *,
    group_by: str,
    telemetry: TelemetryCheck,
    sites: dict[str, str],
    covered: tuple[str, ...],
    bar: str,
    head_sha: str,
) -> str:
    clipped = {"item": 0, "status": 0}
    lines: list[str] = []
    add = lines.append

    since = f"since `{sel.prev_tag}`" if sel.prev_tag else "since the start of the ledger"
    add(f"### What shipped {since}")
    add("")
    if sel.prev_tag:
        add(
            f"Generated from `docs/ledger/shipped.csv` by `scripts/release_notes.py`: every "
            f"row dated after **{sel.prev_day}** (the day `{sel.prev_tag}` was committed) "
            f"and on or before **{sel.tag_day}** (the day `{sel.tag}` was committed). "
            f"Rows are quoted verbatim — `area` — `item` — `date` · `status` · `refs` — "
            f"and nothing is summarised into prose."
        )
    else:
        add(
            f"Generated from `docs/ledger/shipped.csv` by `scripts/release_notes.py`: no "
            f"earlier `v*` tag is reachable from `{sel.tag}`, so every row dated on or "
            f"before **{sel.tag_day}** is listed. Rows are quoted verbatim."
        )
    add("")
    if group_by == "segment":
        add(
            "Headings are the `area` column's first path segment — the only derived text "
            "in this section; each bullet carries its full `area`."
        )
    else:
        add("Headings are the `area` column, verbatim.")
    add("")

    groups = group_rows(sel.in_range, group_by)
    if not groups:
        add("_No ledger row falls in this range._")
        add("")
    for name, rows in groups.items():
        add(f"#### {name}")
        add("")
        for row in rows:
            add(_bullet(row, clipped))
        add("")

    if sel.boundary:
        add(f"#### Dated on `{sel.prev_tag}`'s own day ({sel.prev_day}) — ambiguous")
        add("")
        add(
            "`shipped.csv` records DAYS, not times, so these rows may have landed on "
            "either side of the previous tag. They are listed apart rather than dropped "
            "(which would lose shipped work) or folded in (which would claim work for "
            "the wrong release)."
        )
        add("")
        for row in sorted(sel.boundary, key=lambda r: (r.get("area") or "")):
            add(_bullet(row, clipped))
        add("")

    add("#### Accounting")
    add("")
    add(f"- Ledger rows in range: **{len(sel.in_range)}** in **{len(groups)}** group(s).")
    add(
        f"- Dated on the previous tag's own day (listed above, ambiguous): "
        f"**{len(sel.boundary)}**."
    )
    if sel.after_tag:
        days = sorted((r.get("date") or "") for r in sel.after_tag)
        span = days[0] if days[0] == days[-1] else f"{days[0]} … {days[-1]}"
        add(
            f"- Dated AFTER `{sel.tag}`'s commit day and therefore not in this release: "
            f"**{len(sel.after_tag)}**, dated {span}. The count is exact; filter "
            f"`docs/ledger/shipped.csv` on that range to read them."
        )
    else:
        add(f"- Dated after `{sel.tag}`'s commit day: **0**.")
    add(
        f"- Rows carrying no `YYYY-MM-DD` date, which no range can place: "
        f"**{len(sel.undated)}** — never included in any release's notes, in either "
        f"direction."
    )
    if clipped["item"] or clipped["status"]:
        add(
            f"- Truncated for length and marked `…`: **{clipped['item']}** `item` "
            f"field(s) over {_ITEM_CAP} characters and **{clipped['status']}** `status` "
            f"field(s) over {_STATUS_CAP}. The cap bounds what is LISTED, never a count "
            f"above; the full text is in `docs/ledger/shipped.csv`."
        )
    add(
        "- The `summary` column is not carried here; it is the ledger's long form and "
        "stays in the CSV."
    )
    add("")

    add("### No-telemetry re-check")
    add("")
    add(
        f"`docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md` (and its 11 translations) and "
        f"`docs/USER_MANUAL.md` state to the user that this app sends no telemetry. That "
        f"is a claim about the software's behaviour, so `CLAUDE.md`'s per-release ritual "
        f"re-confirms it before a tag rather than trusting that it still holds. Tree: "
        f"`{head_sha}`."
    )
    add("")
    if telemetry.ran:
        verdict = "PASSED" if telemetry.returncode == 0 else "FAILED"
        # The interpreter is named by its BASENAME: an absolute path to a build
        # agent's toolcache is noise in a public release body, and the basename is
        # what ran — not a shortening that claims anything the run did not do.
        cmd = list(telemetry.command or [])
        shown = " ".join([Path(cmd[0]).name, *cmd[1:]]) if cmd else "(no command)"
        add(
            f"- Socket-importer ratchet: `{shown}` → exit "
            f"**{telemetry.returncode}** ({verdict}) — `{telemetry.summary}`."
        )
    else:
        add(
            "- Socket-importer ratchet: **NOT RE-CHECKED in this run** "
            "(`--telemetry-check skip`). This release's no-telemetry claim has not been "
            "re-confirmed here; it is not a pass."
        )
    add(
        f"- The ratchet covers {len(covered)} socket-capable libraries: "
        + ", ".join(f"`{m}`" for m in covered)
        + "."
    )
    add("")
    add(
        f"The outbound call sites it allows — read from "
        f"`tests/test_network_consent.py`'s own `_ALLOWED_SOCKET_IMPORTERS`, not from a "
        f"copy — are these **{len(sites)}**, each with the reason recorded beside it:"
    )
    add("")
    for path in sorted(sites):
        reason = " ".join(str(sites[path]).split())
        add(f"- `{path}` — {reason}")
    add("")

    add("### Verification bar")
    add("")
    add(
        "The bar every surface in this release cites, ruled 2026-09-15 (Q1128 = a) and "
        "quoted from `docs/product/RELEASE_0.4_GATE.md`:"
    )
    add("")
    add(f"> {bar}")
    add("")
    add(
        "A surface is stamped *verified* only when BOTH halves happened; a Chromium run "
        "alone reads *Chromium-verified (remote sandbox) · awaiting human UX pass*. This "
        "generator does not list per-surface records — it has none to read — so the "
        "release preparer cites them here, one per surface, or says which are owed."
    )
    add("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def build(args: argparse.Namespace) -> tuple[str, dict[str, object]]:
    if not args.allow_dirty:
        require_clean_tree()
    unshallowed = ensure_unshallow()
    tag = resolve_tag(args.tag)
    prev = args.previous if args.previous else previous_tag(tag)
    sel = Selection(
        tag=tag,
        tag_day=commit_day(tag),
        prev_tag=prev,
        prev_day=commit_day(prev) if prev else None,
    )
    select(read_rows(Path(args.csv) if args.csv else _CSV), sel)
    refuse_placeholders(sel)

    sites, covered = outbound_call_sites()
    bar = verification_bar()
    telemetry = run_telemetry_check(args.telemetry_check, args.telemetry_node)
    head_sha = _git("rev-parse", tag)

    body = render(
        sel,
        group_by=args.group_by,
        telemetry=telemetry,
        sites=sites,
        covered=covered,
        bar=bar,
        head_sha=head_sha,
    )
    accounting: dict[str, object] = {
        "tag": tag,
        "tag_day": sel.tag_day,
        "previous_tag": prev,
        "previous_day": sel.prev_day,
        "unshallowed": unshallowed,
        "in_range": len(sel.in_range),
        "boundary": len(sel.boundary),
        "after_tag": len(sel.after_tag),
        "undated": len(sel.undated),
        "telemetry_mode": telemetry.mode,
        "telemetry_returncode": telemetry.returncode,
        "outbound_call_sites": len(sites),
        # Published because a GitHub release body has a maximum length and this one
        # grows with the ledger: 106,197 bytes for v0.2.0 -> v0.3.0. No threshold is
        # hard-coded — the limit was not verifiable from here, and a guessed ceiling
        # would be the fabricated constant this project refuses. The NUMBER is the
        # honest thing to publish, so whoever prepares a tag can see it.
        "body_bytes": len(body.encode("utf-8")),
    }
    return body, accounting


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("--tag", help="the tag being released (default: the tag HEAD is at)")
    ap.add_argument("--previous", help="override the previous tag (default: derived)")
    ap.add_argument("--csv", help="override the ledger path (tests use this)")
    ap.add_argument("-o", "--output", help="write the body here (default: stdout)")
    ap.add_argument(
        "--group-by",
        choices=("segment", "area"),
        default="segment",
        help="segment = the area's first path segment (default); area = the column verbatim",
    )
    ap.add_argument(
        "--telemetry-check",
        choices=("run", "skip"),
        default="run",
        help="run the socket-importer ratchet (default) or state plainly that it was not",
    )
    ap.add_argument(
        "--telemetry-node",
        default="tests/test_network_consent.py",
        help="the pytest node the ritual names",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="skip the clean-tree refusal (local drafting only; never for a tag)",
    )
    ap.add_argument("--json", action="store_true", help="print the accounting as JSON")
    args = ap.parse_args(argv)

    try:
        body, accounting = build(args)
    except ReleaseNotesError as exc:
        print(f"release_notes: REFUSED — {exc}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    print(
        f"release_notes: {accounting['in_range']} row(s) in range, "
        f"{accounting['body_bytes']} bytes",
        file=sys.stderr,
    )
    if args.json:
        print(json.dumps(accounting, indent=2, sort_keys=True), file=sys.stderr)
    # A ratchet that RAN and FAILED must not publish as though it had not.
    if accounting["telemetry_returncode"] not in (None, 0):
        print(
            "release_notes: the no-telemetry ratchet FAILED; the notes say so and this "
            "exits non-zero so a release cannot publish past it.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
