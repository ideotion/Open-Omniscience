#!/usr/bin/env python3
"""
thesaurus_build -- build a SKOS thesaurus (EuroVoc first) into the data directory, on this computer (R737, row 119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The thesaurus is never bundled in the repository: its licence is read first, by the operator, and the file
is built where it is used. This command reads a SKOS RDF/XML file (or a ZIP holding one), keeps the labels
of the languages asked for, and writes two files into ``<data dir>/thesauri/``:

  <scheme>.json          the thesaurus the app reads (topic tagging, the topic measurement);
  <scheme>.summary.json  what the build saw: counts, the source's and the output's SHA-256, the format and
                         this tool's version. It is a few kilobytes, holds no label and no path, and it is
                         the ONE file to send back.

The output is DETERMINISTIC: the same source file and the same options give the same bytes, so the same
SHA-256, on any machine. The app checks that hash and the format on every read
(``src/catalog/thesaurus_store.py``) and sets the file aside, with its reason, when they do not hold.

OFFLINE (the default; no connection is opened):

    python scripts/thesaurus_build.py --source ~/Downloads/eurovoc_skos.zip \\
        --vintage 2026-10-01 --license "CC BY 4.0 (as read on the publisher's page)"

ONLINE (only when asked, and only from the publisher's host): ``--fetch-url URL --online`` downloads the
file first. The URL is the operator's, copied from the publisher's download page; it must be https on a host
this command knows for that thesaurus (EuroVoc: op.europa.eu, publications.europa.eu), and so must every
redirect. It goes out on the transport this data directory names (Tor or a proxy), and refuses when none is
named unless --clearnet is given: a silent clearnet default would be a downgrade. The download is kept beside
the thesaurus (``<scheme>.source``) so the next build can run offline. Run it with the app stopped: the app's
airplane state lives in the app's process and is not visible from here, so --online is this run's consent.

Exit status: 0 built; 2 refused (the reason is printed); 1 the source could not be read as a thesaurus.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.catalog import skos, thesaurus_store  # noqa: E402

#: The hosts a thesaurus may be fetched from, per scheme (exact host names; every redirect hop is held to them).
#: A scheme without an entry is built from a file only.
PUBLISHER_HOSTS: dict[str, tuple[str, ...]] = {
    "eurovoc": ("op.europa.eu", "publications.europa.eu"),
}

#: The labels kept by default: the app's UI languages the thesaurus carries (EuroVoc: five of the twelve).
DEFAULT_LANGUAGES: dict[str, tuple[str, ...] | None] = {
    "eurovoc": ("de", "en", "es", "fr", "pt"),
}

#: Where the registry says each thesaurus comes from (written into the file when --upstream is not given).
DEFAULT_UPSTREAM: dict[str, str] = {
    "eurovoc": "https://op.europa.eu/en/web/eu-vocabularies/dataset/-/resource?uri=http://publications.europa.eu/resource/dataset/eurovoc",
    "unesco-thesaurus": "https://vocabularies.unesco.org/",
    "agrovoc": "https://www.fao.org/agrovoc/",
    "iptc-media-topics": "https://iptc.org/standards/media-topics/",
}

#: The summary must stay small enough to send back (the user's limit is 200 KB per file; this is far under it).
SUMMARY_MAX_BYTES = 64 * 1024
DEFAULT_MAX_MB = 2048
_XML_SUFFIXES = (".rdf", ".xml", ".owl", ".skos")


class BuildRefused(Exception):
    """A refusal with its reason, printed as it is (exit 2)."""


class _TooLarge(skos.SkosError):
    """Raised inside the parser (which names every other error as unparseable); turned back into a refusal."""


class _Capped(io.RawIOBase):
    """A reader that refuses past ``limit`` bytes: a ZIP member's declared size is the archive's word, not a bound."""

    def __init__(self, inner: BinaryIO, limit: int, what: str) -> None:
        self._inner, self._left, self._what, self._limit = inner, limit, what, limit

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        data = self._inner.read(min(len(b), self._left + 1))
        if len(data) > self._left:
            raise _TooLarge(f"{self._what} is larger than {self._limit // (1024 * 1024)} MB once uncompressed (--max-mb)")
        self._left -= len(data)
        b[: len(data)] = data
        return len(data)


def sha256_path(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def _pick_member(zf: zipfile.ZipFile, member: str | None) -> zipfile.ZipInfo:
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if member is not None:
        for i in infos:
            if i.filename == member:
                return i
        raise BuildRefused(f"the ZIP holds no member named {member!r}")
    xml = [i for i in infos if i.filename.lower().endswith(_XML_SUFFIXES)]
    if len(xml) == 1:
        return xml[0]
    names = ", ".join(sorted(i.filename for i in xml)[:20]) or "none"
    raise BuildRefused(f"the ZIP holds {len(xml)} RDF/XML members ({names}); name one with --member")


def parse_source(path: Path, *, member: str | None, max_bytes: int) -> tuple[dict[str, Any], str | None]:
    """Parse the SKOS RDF/XML in ``path`` (a file, or one member of a ZIP); returns (parsed, member name or None)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            info = _pick_member(zf, member)
            if info.file_size > max_bytes:
                raise BuildRefused(f"{info.filename} declares {info.file_size} bytes, more than --max-mb allows")
            with zf.open(info) as raw:
                try:
                    return skos.parse_rdfxml(io.BufferedReader(_Capped(raw, max_bytes, info.filename))), info.filename
                except _TooLarge as exc:
                    raise BuildRefused(str(exc)) from None
    if member is not None:
        raise BuildRefused("--member names a ZIP member, and the source is not a ZIP")
    if path.stat().st_size > max_bytes:
        raise BuildRefused(f"{path.name} is larger than --max-mb allows")
    with open(path, "rb") as fh:
        return skos.parse_rdfxml(fh), None


def canonical_artifact(artifact: dict[str, Any], *, source_sha256: str) -> dict[str, Any]:
    """The artifact with every list in one order, plus its format and the source's hash: what makes the bytes repeatable."""
    concepts = {}
    for uri, c in artifact["concepts"].items():
        concepts[uri] = {
            "pref": dict(c.get("pref") or {}),
            "alt": {lang: sorted(labels) for lang, labels in (c.get("alt") or {}).items()},
            "broader": sorted(c.get("broader") or []),
        }
    gaps = sorted(artifact.get("gaps") or [], key=lambda g: json.dumps(g, sort_keys=True, ensure_ascii=False))
    return {**artifact, "concepts": concepts, "gaps": gaps,
            "format": thesaurus_store.FORMAT_VERSION, "source_sha256": source_sha256}


def summarise(artifact: dict[str, Any], parsed: dict[str, Any], *, source: dict[str, Any], output: dict[str, Any],
              fetched_from_host: str | None) -> dict[str, Any]:
    """The small file the operator sends back: counts and hashes, never a label, a concept id or a local path."""
    pref, alt = Counter(), Counter()
    with_broader = 0
    for c in artifact["concepts"].values():
        pref.update(c["pref"].keys())
        for lang, labels in c["alt"].items():
            alt[lang] += len(labels)
        with_broader += bool(c["broader"])
    return {
        "scheme": artifact["scheme"], "format": thesaurus_store.FORMAT_VERSION,
        "tool": "scripts/thesaurus_build.py", "tool_version": thesaurus_store.BUILD_TOOL_VERSION,
        "vintage": artifact["vintage"], "license": artifact["license"], "upstream": artifact["upstream"],
        "languages": artifact["languages"],
        "source": source, "output": output, "fetched_from_host": fetched_from_host,
        "counts": {
            "concepts_seen": parsed.get("n_seen"), "concepts_kept": artifact["n_concepts"],
            "concepts_with_broader": with_broader,
            "pref_labels_by_language": dict(sorted(pref.items())),
            "alt_labels_by_language": dict(sorted(alt.items())),
            "gaps_by_kind": dict(sorted(Counter(g.get("kind", "?") for g in artifact["gaps"]).items())),
        },
    }


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def build(scheme: str, source_path: Path, out_dir: Path, *, vintage: str, license: str, upstream: str,
          languages: tuple[str, ...] | None, member: str | None = None, max_bytes: int = DEFAULT_MAX_MB << 20,
          fetched_from_host: str | None = None) -> dict[str, Any]:
    """Build ``scheme`` from ``source_path`` into ``out_dir``; returns the summary. Opens no connection."""
    if scheme not in skos.SCHEMES:
        raise BuildRefused(f"unknown scheme {scheme!r}; known: {', '.join(skos.SCHEMES)}")
    if not source_path.is_file():
        raise BuildRefused(f"no file at {source_path}")
    src_sha, src_bytes = sha256_path(source_path)
    parsed, picked = parse_source(source_path, member=member, max_bytes=max_bytes)
    art = skos.build_artifact(scheme, parsed, vintage=vintage, license=license, upstream=upstream, languages=languages)
    art = canonical_artifact(art, source_sha256=src_sha)
    data = thesaurus_store.canonical_bytes(art)
    out_name = thesaurus_store.thesaurus_path(scheme, out_dir).name
    summary = summarise(
        art, parsed,
        source={"name": source_path.name, "member": picked, "sha256": src_sha, "bytes": src_bytes},
        output={"name": out_name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
        fetched_from_host=fetched_from_host,
    )
    sdata = (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    if len(sdata) > SUMMARY_MAX_BYTES:  # pragma: no cover - counts only; a guard, not an expected path
        raise BuildRefused(f"the summary came to {len(sdata)} bytes, over {SUMMARY_MAX_BYTES}")
    out_dir.mkdir(parents=True, exist_ok=True)
    # The thesaurus first, its summary second: a run cut in between leaves a file the app reads as
    # changed (hash_mismatch) or unverified, never one that passes a check it should not.
    _write_atomic(thesaurus_store.thesaurus_path(scheme, out_dir), data)
    _write_atomic(thesaurus_store.summary_path(scheme, out_dir), sdata)
    return summary


# --------------------------------------------------------------------------- fetch (only with --online)


def check_fetch_url(url: str, hosts: tuple[str, ...]) -> None:
    """Refuse ``url`` unless it is https on one of ``hosts`` (both URL readings, no user name, port 443)."""
    from src.safety.fetcher import RedirectRefused, refuse_unlisted_host

    try:
        refuse_unlisted_host(url, hosts)
    except RedirectRefused as exc:
        raise BuildRefused(f"refusing the fetch URL: {exc} (this thesaurus is fetched only from {', '.join(hosts)})") from None


def fetch_source(url: str, hosts: tuple[str, ...], dest: Path, *, max_bytes: int, session: Any = None) -> str:
    """Download ``url`` to ``dest`` through the guarded session held to ``hosts``; returns the host that answered."""
    from urllib.parse import urlparse

    from src.ingest import DEFAULT_USER_AGENT
    from src.safety.fetcher import guarded_session

    check_fetch_url(url, hosts)
    s = session if session is not None else guarded_session(user_agent=DEFAULT_USER_AGENT, allowed_hosts=hosts)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as fh, s.get(url, stream=True, timeout=60) as resp:
            check_fetch_url(str(getattr(resp, "url", "") or ""), hosts)  # where the answer came from, after redirects
            if resp.status_code != 200:
                raise BuildRefused(f"the publisher answered HTTP {resp.status_code}")
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise BuildRefused(f"the publisher declares {declared} bytes, more than --max-mb allows")
            n = 0
            for chunk in resp.iter_content(1 << 20):
                n += len(chunk)
                if n > max_bytes:
                    raise BuildRefused("the download is larger than --max-mb allows")
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())
            host = urlparse(str(resp.url)).hostname or ""
        if n == 0:
            raise BuildRefused("the publisher answered with an empty file")
        os.replace(tmp, dest)
        return host
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _transport_refusal(clearnet: bool) -> str | None:
    """The gazetteer build's rule: --online goes out on the transport this data directory or the environment names,
    and refuses an unnamed one unless --clearnet says clearnet is wanted."""
    from src.entities.gazetteer_build import transport_state

    ts = transport_state()
    if ts["explicit"] or clearnet:
        return None
    return ("refused: this data directory and your environment name no transport, so --online would go out on "
            "clearnet by default. If you use Tor or a proxy, set OO_FETCH_MODE=protected and OO_HTTP_PROXY; "
            "if clearnet is what you want, say so with --clearnet")


# --------------------------------------------------------------------------- command line


def _languages(value: str | None, scheme: str) -> tuple[str, ...] | None:
    if value is None:
        return DEFAULT_LANGUAGES.get(scheme)
    if value.strip().lower() == "all":
        return None
    langs = tuple(sorted({v.strip().lower() for v in value.split(",") if v.strip()}))
    if not langs:
        raise BuildRefused("--languages is empty; say 'all' to keep every language")
    return langs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0].strip())
    ap.add_argument("--scheme", default="eurovoc", choices=skos.SCHEMES)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source", type=Path, help="a SKOS RDF/XML file, or a ZIP holding one, already on this computer")
    src.add_argument("--fetch-url", help="download the source from the publisher first (needs --online)")
    ap.add_argument("--online", action="store_true", help="with --fetch-url: say yes to contacting the publisher's host")
    ap.add_argument("--clearnet", action="store_true",
                    help="with --online: accept clearnet when this data directory and your environment name no transport")
    ap.add_argument("--member", help="the RDF/XML member to read when the ZIP holds several")
    ap.add_argument("--vintage", required=True, help="the release date the publisher gives, YYYY-MM-DD")
    ap.add_argument("--license", required=True, help="the licence as read on the publisher's page")
    ap.add_argument("--upstream", default=None, help="the publisher's page (default: the registry's)")
    ap.add_argument("--languages", default=None,
                    help="comma-separated language codes to keep, or 'all' (default for eurovoc: de,en,es,fr,pt)")
    ap.add_argument("--out-dir", type=Path, default=None, help="default: the data directory's thesauri folder")
    ap.add_argument("--max-mb", type=int, default=DEFAULT_MAX_MB, help="the largest download or uncompressed source read")
    args = ap.parse_args(argv)

    try:
        langs = _languages(args.languages, args.scheme)
        out_dir = args.out_dir if args.out_dir is not None else thesaurus_store.thesauri_dir()
        max_bytes = max(1, args.max_mb) << 20
        host = None
        if args.fetch_url is not None:
            hosts = PUBLISHER_HOSTS.get(args.scheme)
            if not hosts:
                raise BuildRefused(f"{args.scheme} has no publisher host here; download it yourself and pass --source")
            check_fetch_url(args.fetch_url, hosts)
            if not args.online:
                raise BuildRefused(f"refusing: this downloads from {', '.join(hosts)}; say --online to allow it, "
                                   "or download the file yourself and pass --source")
            why = _transport_refusal(args.clearnet)
            if why:
                raise BuildRefused(why)
            source = out_dir / f"{args.scheme}.source"
            print(f"downloading from {', '.join(hosts)} to {source} ...", file=sys.stderr)
            host = fetch_source(args.fetch_url, hosts, source, max_bytes=max_bytes)
        else:
            source = args.source.expanduser()
        summary = build(args.scheme, source, out_dir, vintage=args.vintage, license=args.license,
                        upstream=args.upstream or DEFAULT_UPSTREAM[args.scheme], languages=langs,
                        member=args.member, max_bytes=max_bytes, fetched_from_host=host)
    except BuildRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (skos.SkosError, zipfile.BadZipFile, ValueError) as exc:
        print(f"the source could not be read as a SKOS thesaurus: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:  # a transport refusal, the kill switch (NetworkBlocked), a disk error
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    c = summary["counts"]
    spath = thesaurus_store.summary_path(args.scheme, out_dir)
    print(f"built {summary['output']['name']}: {c['concepts_kept']} concepts in {', '.join(summary['languages'])}, "
          f"{sum(c['gaps_by_kind'].values())} gap(s), SHA-256 {summary['output']['sha256'][:12]}...")
    print(f"send back: {spath} ({spath.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
