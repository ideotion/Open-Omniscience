#!/usr/bin/env python3
"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""The scripted pass that puts every config's country in the form the app speaks on the wire (S05-02 S3, Q305).

Q305 ruled that the shipped catalogues follow Q301: the ``country:`` and ``jurisdiction:`` values in the
YAML files the loaders read are rewritten from lowercase alpha-2 (and the law catalogue's own spellings,
``uk``/``usa``/``uae``) to uppercase alpha-3, in ONE scripted pass, and a repo test pins that none is left.

How it stays safe, in the order it matters:

* It edits TEXT, never a parse-and-dump round trip: comments, quoting, ordering and every byte that is not a
  country value stay exactly as they were, so the config diff is reviewable line for line.
* It only touches a value in KEY position (line start, or after ``{`` / ``,`` inside a flow mapping). Prose
  that happens to contain the word ``jurisdiction:`` (the law notes do) is left alone.
* The rewrite of a value is :func:`src.catalog.countries.country_payload` -- the SAME function the JSON
  boundary uses -- so a catalogue and a payload can never disagree about a country's alpha-3. A value it
  cannot place (an unrecognised code, a prose token) is left exactly as written and LISTED with its reason, never
  guessed, and it never blocks the other rewrites (the exit code says there is something left, 1).
* The write is atomic as a SET: every new file is staged beside its target and fsynced first, then renamed over the
  originals; a failure leaves every original as it was (a refusal to prove one file writes none).
* After writing it PARSES the old and the new text and proves they differ ONLY in country/jurisdiction
  values, and that each differing value satisfies ``normalize_country(new) == normalize_country(old)``:
  the loaders read countries through that function, so the data they produce is unchanged.

Usage::

    python scripts/rewrite_config_countries.py            # report only (exit 1 if anything would change)
    python scripts/rewrite_config_countries.py --write    # rewrite in place
    python scripts/rewrite_config_countries.py --write --report out.json
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.catalog.countries import (  # noqa: E402
    country_payload,
    country_payload_iso3,
    normalize_country,
)

#: The YAML files the loaders read. Research artefacts under ``docs/`` are records, not configs.
TARGETS = tuple(sorted(str(p.relative_to(ROOT)) for p in (ROOT / "configs").glob("*.yml")))

KEYS = ("country", "jurisdiction")

# A key in KEY position: at the start of a (possibly "- " prefixed) line, or after "{" / "," in a flow mapping.
_VALUE = re.compile(
    r"""(?P<lead>(?:^|^\s*-\s+|^\s+|[{,]\s*)(?P<key>country|jurisdiction)\s*:\s*)"""
    r"""(?P<quote>["']?)(?P<val>[^\s,"'{}\[\]#]+)(?P=quote)""",
)


def _is_flow_or_block_line(line: str) -> bool:
    """A line that can hold keys: a block mapping line or a flow mapping entry, not a comment."""
    return not line.lstrip().startswith("#")


def _split_comment(body: str) -> tuple[str, str]:
    """``(code, comment)``: the comment starts at the first ``#`` outside quotes that opens the line or follows a space.

    A quote OPENS a quoted scalar only where a scalar starts (line start, or after ``:`` ``,`` ``[`` ``{`` ``-``): an
    apostrophe inside a plain scalar (``don't``) is just a character, and treating it as a quote would swallow the
    real comment after it."""
    quote = ""
    escaped = False
    for i, ch in enumerate(body):
        if escaped:
            escaped = False
        elif quote:
            if ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            before = body[:i].rstrip()
            if not before or before[-1] in ":,[{-":
                quote = ch
        elif ch == "#" and (i == 0 or body[i - 1] in " \t"):
            return body[:i], body[i:]
    return body, ""


def rewrite_text(text: str) -> tuple[str, list[dict]]:
    """Return ``(new_text, changes)``; ``changes`` lists every value looked at, rewritten or not."""
    out: list[str] = []
    changes: list[dict] = []
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        if not _is_flow_or_block_line(line):
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        eol = line[len(body):]

        def sub(m: re.Match, number: int = number) -> str:
            val = m.group("val")
            # Only a flow mapping or a real key line can carry a value here; the `lead` alternatives enforce it.
            new = country_payload(val)
            if new is None or new == val:
                changes.append({"line": number, "key": m.group("key"), "old": val, "new": val, "changed": False})
                return m.group(0)
            changes.append({"line": number, "key": m.group("key"), "old": val, "new": new, "changed": True})
            return m.group("lead") + m.group("quote") + new + m.group("quote")

        code, comment = _split_comment(body)  # a trailing comment is never edited
        out.append(_VALUE.sub(sub, code) + comment + eol)
    return "".join(out), changes


def _walk_pairs(node, path=()):
    """Yield (path, value) for every country/jurisdiction value in a parsed document, a list-valued one included
    (the text pass never rewrites it, so ``leftovers`` has to be able to name it)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in KEYS and not isinstance(v, dict):
                yield path + (k,), v
            else:
                yield from _walk_pairs(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_pairs(v, path + (i,))


def _strip_country_values(node):
    """The parsed document with every country/jurisdiction value blanked, to compare everything ELSE."""
    if isinstance(node, dict):
        return {k: (None if k in KEYS and not isinstance(v, dict) else _strip_country_values(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_strip_country_values(v) for v in node]
    return node


def prove_equivalent(old_text: str, new_text: str) -> list[str]:
    """Problems found comparing the parsed old and new text; empty means the rewrite changed only countries."""
    problems: list[str] = []
    old, new = yaml.safe_load(old_text), yaml.safe_load(new_text)
    if _strip_country_values(old) != _strip_country_values(new):
        problems.append("something other than a country/jurisdiction value changed")
    old_pairs, new_pairs = dict(_walk_pairs(old)), dict(_walk_pairs(new))
    if old_pairs.keys() != new_pairs.keys():
        problems.append("the set of country/jurisdiction keys changed")
        return problems
    for path, was in old_pairs.items():
        now = new_pairs[path]
        if was == now:
            continue
        if was is False and now == "NOR":
            # YAML 1.1 reads an unquoted `NO` as the boolean False (the Norway problem): the old file never said
            # "Norway" to a loader at all. The text says NO, the rewrite makes it the string it always meant.
            continue
        if normalize_country(str(now)) != normalize_country(str(was)) or normalize_country(str(was)) is None:
            problems.append(f"{'/'.join(map(str, path))}: {was!r} -> {now!r} does not read as the same country")
    return problems


def leftovers(text: str) -> list[str]:
    """Every country/jurisdiction value still not in the wire form, whatever the text form it was written in, each
    with the reason it is listed.

    The regex pass reads ``key: value`` text; a quoted key, an anchor, a tag, a list or a value on the next line is
    invisible to it. This reads the PARSED document, so such a value is named instead of skipped, and a value no
    country code answers to (``ZZZ``, ``WLD``) is named too."""
    bad = []
    for path, value in _walk_pairs(yaml.safe_load(text)):
        if isinstance(value, str) and value.isupper() and country_payload_iso3(value) == value:
            continue
        if isinstance(value, list):
            why = "a list, which the pass does not rewrite"
        elif not isinstance(value, str):
            why = "not a string (YAML read it as another type)"
        elif country_payload_iso3(value) is None:
            why = "not a recognised country code, left as written"
        else:
            why = "a country, but not in the wire form (the text pass could not reach it)"
        bad.append(f"{'/'.join(map(str, path))}: {value!r} ({why})")
    return bad


def _fsync_dir(directory: Path) -> None:
    """Make a rename durable. A platform that cannot open a directory has nothing to sync."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_all_atomically(items: list[tuple[Path, bytes, bytes]]) -> None:
    """Replace each ``(path, old_bytes, new_bytes)`` so that a failure leaves EVERY original as it was.

    Every new file is first written beside its target (same directory, so the rename stays on one filesystem),
    flushed and fsynced; only when all of them are on disk are they renamed over the originals, then the
    directories are synced. A failure while staging removes the temporary files and touches no original. A failure
    during the renames puts back the ones already replaced; a file that cannot be put back is named in the error,
    never hidden."""
    staged: list[tuple[Path, Path, bytes]] = []
    try:
        for path, old, new in items:
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            tmp = Path(tmp_name)
            staged.append((path, tmp, old))
            with os.fdopen(fd, "wb") as handle:
                handle.write(new)
                handle.flush()
                os.fsync(handle.fileno())
            shutil.copymode(path, tmp)
    except BaseException:
        for _path, tmp, _old in staged:
            tmp.unlink(missing_ok=True)
        raise
    replaced: list[tuple[Path, bytes]] = []
    try:
        for path, tmp, old in staged:
            os.replace(tmp, path)
            replaced.append((path, old))
        for directory in {path.parent for path, _tmp, _old in staged}:
            _fsync_dir(directory)
    except BaseException:
        stuck = []
        for path, old in replaced:
            try:
                _write_one(path, old)
            except OSError:
                stuck.append(str(path))
        for _path, tmp, _old in staged:
            tmp.unlink(missing_ok=True)
        if stuck:
            raise RuntimeError("rewritten and could not be put back (git checkout restores them): " + ", ".join(stuck)) from None
        raise


def _write_one(path: Path, data: bytes) -> None:
    """One file, the same way: a temporary beside it, fsynced, renamed over it."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _write_report(path: str | None, report: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite the files in place")
    ap.add_argument("--report", help="write a JSON report of every value looked at")
    args = ap.parse_args()

    report: dict = {"files": {}, "unplaced": [], "left": [], "refused": None}
    would_change = 0
    # PROVE EVERY FILE FIRST, write after: a refusal on the last file must not leave the first ones rewritten.
    planned: list[tuple[str, str, str, list[dict]]] = []
    for rel in TARGETS:
        old_text = (ROOT / rel).read_bytes().decode("utf-8")
        new_text, changes = rewrite_text(old_text)
        problems = prove_equivalent(old_text, new_text)
        if problems:
            print(f"REFUSED {rel}: {problems[:5]}", file=sys.stderr)
            report["refused"] = {"file": rel, "problems": problems[:5]}
            _write_report(args.report, report)
            return 2
        planned.append((rel, old_text, new_text, changes))
    # A value the pass cannot place stays exactly as written and is LISTED with its reason; it never blocks the
    # other rewrites (the repo test is what insists none is left in a committed file).
    left = [(rel, v) for rel, _, new_text, _ in planned for v in leftovers(new_text)]
    report["left"] = [{"file": rel, "value": v} for rel, v in left]
    to_write = []
    for rel, old_text, new_text, changes in planned:
        tally = Counter("rewritten" if c["changed"] else "kept" for c in changes)
        unplaced = sorted({(c["key"], c["old"]) for c in changes if not c["changed"] and country_payload_iso3(c["old"]) is None})
        report["files"][rel] = {"values": len(changes), **tally}
        report["unplaced"] += [{"file": rel, "key": k, "value": v} for k, v in unplaced]
        would_change += tally.get("rewritten", 0)
        if args.write and new_text != old_text:
            to_write.append((ROOT / rel, old_text.encode("utf-8"), new_text.encode("utf-8")))
        print(f"{rel}: {len(changes)} values, {tally.get('rewritten', 0)} rewritten, {len(unplaced)} distinct unplaced")
    if to_write:
        try:
            write_all_atomically(to_write)
        except (OSError, RuntimeError) as exc:
            print(f"WRITE FAILED ({type(exc).__name__}): every original was left as it was unless said otherwise: {exc}", file=sys.stderr)
            report["refused"] = {"write_failed": type(exc).__name__}
            _write_report(args.report, report)
            return 2
    print(f"total rewritten: {would_change}")
    if left:
        print("not in the wire form after the pass (left as written):")
        for rel, v in left:
            print(f"  {rel}: {v}")
    if report["unplaced"]:
        print("left as written (not a recognised country code):")
        for u in report["unplaced"]:
            print(f"  {u['file']}: {u['key']}: {u['value']}")
    _write_report(args.report, report)
    return 0 if (not left and (args.write or would_change == 0)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
