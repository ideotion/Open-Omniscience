"""The medical lane's ONE egress: NLM's PubMed update files, fetched on a consented click (S07-01; R745, R750).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHERE IT GOES. Only ``https://ftp.ncbi.nlm.nih.gov/pubmed/updatefiles/``: the session is held to
that host AND that directory (``guarded_session(allowed_hosts=..., allowed_path_prefixes=...)``),
so a redirect anywhere else is refused before it is sent, and no part of any URL comes from input
or configuration: the directory listing names the files, and a name is used only when it matches
NLM's own pattern (``FILE_NAME``). It reads no robots.txt: these are DATA files NLM publishes for
bulk download, the same posture as the climate datasets (``docs/SECURITY.md``).

WHAT IS KEPT (R745). A file is the TRANSPORT. It is read whole and only the records whose PMID,
DOI or PMCID the corpus cites, or the user named, are kept; the rest is discarded and the
downloaded bytes are never written to disk. The corpus-cited ids come from a READ-ONLY scan of the
corpus's outbound links (``cited_in_corpus``): nothing in the corpus is re-extracted or written.

WHAT IT CANNOT FIND (R750). Update files carry only the papers NLM revised recently. A paper the
corpus cites that no update file carried is NOT FOUND YET -- never "does not exist" -- and the
status says how many are in that state. The baseline walk that would reach the rest is a separate,
later opt-in (R750 (b)); E-utilities by id is not built (R750 (c)), because it would send NCBI the
list of papers the user's corpus cites.

THE BOUNDS. Each body is read in chunks under a byte cap (``_bounded_get``), the kill switch is
read between chunks so Stop ends a download under way, and the gzip stream is read under its own
decompressed-size cap, so a compression bomb stops the same way. Each file is checked against
NLM's ``.md5`` before a single record of it is applied. The timeout bounds each read, not the
whole transfer: a server that drips bytes keeps the call waiting (named, not hidden). Peak memory
for one file is about twice ``MAX_FILE_BYTES`` (the read buffer and its copy coexist briefly). The
decompressed cap bounds the bytes parsed, not the size of one record's parse tree: a single record
of near-cap size served by the host itself would be held whole while it is read (named, not hidden).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
from collections.abc import Callable
from typing import IO, Any

from src.ingest import DEFAULT_USER_AGENT, kill_switch_active
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.medical import store as M
from src.medical.pubmed_xml import ParseTally, parse_pubmed

PUBMED_HOST = "ftp.ncbi.nlm.nih.gov"
PUBMED_HOSTS = (PUBMED_HOST,)
PUBMED_PATHS = ("/pubmed/updatefiles/",)
UPDATE_BASE = "https://" + PUBMED_HOST + PUBMED_PATHS[0]

#: The directory listing is one HTML page of a few thousand names.
MAX_LISTING_BYTES = 8 * 1024 * 1024
#: An update file is tens of megabytes compressed; this is several times the largest seen.
MAX_FILE_BYTES = 256 * 1024 * 1024
#: The decompressed XML of one file; a body that inflates past this is refused, not read on.
MAX_XML_BYTES = 2 * 1024 * 1024 * 1024
#: Files one click may take, and the default.
DEFAULT_FILES = 7
MAX_FILES = 30

DISCLOSURE = (
    "Each PubMed update file is tens of megabytes. The app reads it whole and keeps only the papers "
    "your articles cite or that you named; the rest is discarded, never stored."
)
GAP = (
    "Only papers NLM revised recently are in the update files, so most papers your articles cite "
    "will not be found yet. A paper not found here is not missing from PubMed."
)

_HREF = re.compile(r'href="(pubmed[0-9]{2}n[0-9]{4}\.xml\.gz)"')
_MD5 = re.compile(r"\b([0-9a-f]{32})\b")

# The corpus scan: which outbound links name a paper, and how its id is read from the link.
_CITE_PMID = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)([1-9][0-9]{0,9})(?![0-9])", re.I)
_CITE_PMCID = re.compile(r"(?:pmc\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pmc)/articles/(PMC[1-9][0-9]{0,9})(?![0-9])", re.I)
_CITE_DOI = re.compile(r"(?:^|//|//www\.)(?:dx\.)?doi\.org/(10\.[0-9]{4,9}/[^\s?#\"'<>]+)", re.I)
_LINK_HINTS = ("%pubmed%", "%/pmc/articles/%", "%pmc.ncbi%", "%doi.org/10.%")
_SCAN_BATCH = 5000


class FileRefused(ValueError):
    """A file this fetch will not apply: a body past its cap, or a checksum that does not match. Names sizes, never a URL."""


def cited_ids(urls: list[str]) -> M.Wanted:
    """The paper ids a list of link URLs names. A malformed id is skipped, never guessed."""
    from urllib.parse import unquote

    out = M.Wanted()
    for url in urls:
        for m in _CITE_PMID.finditer(url):
            out.pmid.add(m.group(1))
        for m in _CITE_PMCID.finditer(url):
            out.pmcid.add(m.group(1).upper())
        for m in _CITE_DOI.finditer(unquote(url)):  # a DOI link often percent-encodes its slash
            try:
                out.doi.add(M.normalise_id("doi", m.group(1).rstrip(".,;)")))
            except ValueError:
                continue
    return out


def cited_in_corpus(db: Any, *, stopping: Callable[[], bool] = lambda: False) -> M.Wanted:
    """The ids the corpus's outbound links cite. READ-ONLY and batched by link id: nothing is written."""
    from sqlalchemy import or_, select

    from src.database.models import ArticleLink

    out = M.Wanted()
    after = 0
    hint = or_(*[ArticleLink.url.ilike(h) for h in _LINK_HINTS])
    while not stopping():
        rows = db.execute(
            select(ArticleLink.id, ArticleLink.url)
            .where(ArticleLink.id > after, hint)
            .order_by(ArticleLink.id)
            .limit(_SCAN_BATCH)
        ).all()
        if not rows:
            break
        after = rows[-1][0]
        found = cited_ids([u for _i, u in rows if u])
        for kind in M.WANTED_KINDS:
            out._set(kind).update(found._set(kind))
    return out


def _session() -> Any:
    from src.safety.fetcher import guarded_session

    return guarded_session(user_agent=DEFAULT_USER_AGENT, allowed_hosts=PUBMED_HOSTS, allowed_path_prefixes=PUBMED_PATHS)


def _get(session: Any, url: str, max_bytes: int) -> bytes:
    from src.stats.fetch import BodyTooLarge, _bounded_get

    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    try:
        resp = _bounded_get(session, url, max_chars=max_bytes // 4)
    except BodyTooLarge as exc:
        raise FileRefused(str(exc)) from exc
    resp.raise_for_status()
    return bytes(resp.content)


def list_update_files(session: Any) -> list[str]:
    """The update files NLM lists, in NLM's order. Only names matching NLM's pattern are kept."""
    html = _get(session, UPDATE_BASE, MAX_LISTING_BYTES).decode("utf-8", "replace")
    names = {n for n in _HREF.findall(html) if M.FILE_NAME.fullmatch(n)}
    return sorted(names, key=M.file_sequence)


def _expected_md5(session: Any, name: str) -> str:
    body = _get(session, UPDATE_BASE + name + ".md5", 4096).decode("ascii", "replace")
    m = _MD5.search(body.lower())
    if m is None:
        raise FileRefused("NLM's checksum file for this update file could not be read")
    return m.group(1)


class _CappedReader(io.RawIOBase):
    """A reader that refuses to deliver more than ``cap`` bytes of the stream it wraps."""

    def __init__(self, raw: IO[bytes] | gzip.GzipFile, cap: int) -> None:
        self._raw = raw
        self._cap = cap
        self._read = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        chunk = self._raw.read(len(b))
        self._read += len(chunk)
        if self._read > self._cap:
            raise FileRefused(f"the file inflates past {self._cap} bytes, the most one update file may hold; reading stopped")
        b[: len(chunk)] = chunk
        return len(chunk)


def apply_body(name: str, body: bytes, expected_md5: str, wanted: M.Wanted) -> dict:
    """Check one downloaded file against its checksum and apply it to the lane, in one transaction."""
    from src.versioned import store

    got = hashlib.md5(body, usedforsecurity=False).hexdigest()
    if got != expected_md5:
        raise FileRefused("the file does not match NLM's checksum; nothing of it was applied")
    tally = ParseTally()
    stream = io.BufferedReader(_CappedReader(gzip.GzipFile(fileobj=io.BytesIO(body)), MAX_XML_BYTES))
    with store.lane_session(M.LANE) as s:
        out = M.apply_file(
            s,
            name,
            parse_pubmed(stream, tally),
            tally,
            wanted,
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
        )
        s.commit()
    return out


def _done_files() -> set[str]:
    from sqlalchemy import select

    from src.medical.lane_models import MedicalFile
    from src.versioned import store

    with store.lane_session(M.LANE) as s:
        return set(s.execute(select(MedicalFile.name).where(MedicalFile.status == "finished")).scalars())


def _record_failure(name: str, exc: BaseException) -> None:
    from src.versioned import store

    with store.lane_session(M.LANE) as s:
        M.record_failed_file(s, name, exc)
        s.commit()


def run_fetch(
    files: int = DEFAULT_FILES,
    *,
    progress: Callable[[int, int, str], None] = lambda done, total, detail: None,
    stopping: Callable[[], bool] = lambda: False,
    session: Any = None,
) -> dict:
    """One consented click: scan the corpus for cited ids, list the update files, and apply the next ``files`` not yet applied.

    The oldest unapplied files go first, so a later file always lands after the one before it. A
    file that fails is recorded as failed (its error class is named, never a URL) and the run goes on
    to the next one, so one file that fails the same way every time cannot block every later file;
    the failed one is tried again on the next click, and ``apply_file`` skips whatever a newer file
    already overtook. Airplane mode coming on ends the run, named as such.
    """
    from src.database.session import session_scope
    from src.versioned import store

    files = max(1, min(int(files), MAX_FILES))
    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    store.create_lane(M.LANE)  # idempotent: the file and its schema, under the factory's own key rules
    progress(0, files + 1, "reading the papers your articles cite")
    with session_scope() as db:
        cited = cited_in_corpus(db, stopping=stopping)
    if stopping():
        # A scan cut short is partial: it must not replace the last full snapshot, and a stop asked
        # for before any request means no request is sent.
        return {"cited_ids": None, "named_ids": None, "listed": None, "remaining": None, "applied": [],
                "failed": None, "stopped": True, "coverage": None}
    with store.lane_session(M.LANE) as s:
        n_cited = M.replace_cited(s, cited)
        named = M.user_wanted(s)
        s.commit()
    wanted = M.Wanted()
    for kind in M.WANTED_KINDS:
        wanted._set(kind).update(cited._set(kind) | named._set(kind))

    http = session if session is not None else _session()
    listed = list_update_files(http)
    done = _done_files()
    todo = [n for n in listed if n not in done][:files]
    applied: list[dict] = []
    failed: dict | None = None
    failures = 0
    for i, name in enumerate(todo, start=1):
        if stopping():
            break
        progress(i, len(todo) + 1, name)
        try:
            body = _get(http, UPDATE_BASE + name, MAX_FILE_BYTES)
            applied.append(apply_body(name, body, _expected_md5(http, name), wanted))
        except Exception as exc:  # noqa: BLE001 - recorded on the file's row and named in the result
            if kill_switch_active():
                # Airplane mode came on mid-run: named as such (#14e), and not charged to the file, which did nothing wrong.
                failed = {"file": name, "error": "airplane_mode", "reason": NETWORK_REFUSED}
                break
            _record_failure(name, exc)
            failures += 1
            if failed is None:
                failed = {
                    "file": name,
                    "error": type(exc).__name__,
                    "reason": str(exc)[:300] if isinstance(exc, FileRefused) else None,
                }
    with store.lane_session(M.LANE) as s:
        cov = M.coverage(s)
    return {
        "cited_ids": n_cited,
        "named_ids": len(named),
        "listed": len(listed),
        "remaining": max(0, len([n for n in listed if n not in done]) - len(applied)),
        "applied": applied,
        "failed": failed,
        "failed_files": failures,
        "stopped": stopping() and len(applied) + failures < len(todo),
        "coverage": cov,
    }
