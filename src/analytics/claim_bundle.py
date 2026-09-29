"""The Claim Workspace's step ⑥ -- the trail exported as a signed evidence bundle.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Gate row K of ``docs/product/RELEASE_0.5_GATE.md``, brief ``S05-11`` S2. The reader has
walked a claim through the corpus (:func:`src.analytics.claim_workspace.build_workspace`);
this writes that trail as ONE ZIP that someone else can check without this app:

* ``trail.json`` -- the trail exactly as the workspace drew it (steps ① to ⑤, the claim,
  the words searched, every count with its population);
* ``articles/<id>.json`` -- each article of the trail: its metadata, the SHA-256 of its
  stored text, and the text itself unless the reader left it out;
* ``sources.json`` -- the sources those articles came from;
* ``corroboration/<n>.json`` -- a weather slice for an offer of step ④, only when this
  machine ALREADY holds it (read from the local cache; building a bundle never fetches);
* ``ATTRIBUTION.md`` -- the licence lines that apply to these contents (Q1008 = a);
* ``WHAT-A-READER-CAN-SEE.md`` -- the §18 enumeration, measured against this bundle;
* ``README.md`` -- what this is, the plaintext disclosure, how to verify it;
* ``manifest.json`` -- every member above with its size and SHA-256, and a Merkle root
  over them; ``SIGNATURE.json`` -- the custody signer's signature over the manifest's
  canonical bytes, with the public identity that made it.

THREE REFUSALS, each load-bearing:

* **No verdict travels.** The bundle carries the trail, never a score; the walk of the
  payload's keys that guards the workspace also guards ``trail.json`` (tests).
* **OSM stops at the Q823 seam.** Every carried row names the table it came from, and the
  set becomes ``table:<name>`` signals for :func:`src.backup.attribution.attribution_dicts`,
  which raises :class:`~src.backup.attribution.PendingRulingError` on an OSM-derived one.
  The bundle is then REFUSED whole -- no bytes are returned -- rather than written with an
  attribution block that would be silently short (brief ``S05-11`` §6).
* **A bundle that cannot be verified is not a bundle.** The signature covers the manifest,
  the manifest covers every member by hash, and :func:`verify_trail_bundle` checks both
  plus that no member was added or removed. It needs no database and no network, and this
  module imports nothing at load time beyond the standard library, so
  ``scripts/verify_claim_trail.py`` runs without the app's database stack.

THE KEY, stated where it travels: the signer is this install's CUSTODY key (the one that
signs the chain-of-custody log), so a verified bundle proves which install made it -- and
the same public key on every bundle links every recipient's copy to that install.
``WHAT-A-READER-CAN-SEE.md`` says so; §18 asks for exactly that statement.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

SCHEMA = "oo-claim-trail-1"
MANIFEST = "manifest.json"
SIGNATURE = "SIGNATURE.json"

DISCLOSURE = (
    "PLAINTEXT. Your corpus is encrypted at rest; this bundle is not. It carries the claim "
    "you checked, the trail your corpus holds about it and, unless you left it out, the full "
    "text of every article in that trail. Anyone who has the file can read all of it."
)

_METHOD = (
    "measured against the exact articles, sources and weather slices this bundle carries, "
    "on this corpus, at the moment it was written"
)


class TrailBundleError(ValueError):
    """The trail cannot be written as a bundle (nothing to carry)."""


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str, sort_keys=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _merkle(hashes: list[str]) -> str:
    from src.crypto.merkle_tree import compute_merkle_root

    return compute_merkle_root(hashes)


def _canonical(payload: dict) -> bytes:
    from src.custody.signing import canonical_bytes

    return canonical_bytes(payload)


def carried_tables(ws: dict) -> set[str]:
    """The corpus tables whose rows this trail carries, as named by the rows themselves.

    Articles and sources always; the place a weather offer is pinned to names where its
    coordinate came from (``coords_from``). An offer pinned by an OSM-derived table would
    add an ``osm_*`` name here, and that is what makes the Q823 refusal fire.
    """
    tables = {"articles", "sources"}
    for op in (ws.get("corroboration") or {}).get("offers") or []:
        src = (op.get("coords_from") or "").strip()
        if src:
            tables.add(src)
    return tables


def _signals(tables: Iterable[str], sources: list[dict], weather_members: int) -> set[str]:
    from src.backup.attribution import files_signal, signals_from_sources, table_signal

    sig = {table_signal(t) for t in tables}
    sig |= signals_from_sources(sources)
    if weather_members:
        sig.add(files_signal("weather_context"))
    return sig


def trail_privacy(session, ws: dict, article_ids: list[int], *, full_text: bool,
                  identity: dict, weather_members: int, n_sources: int) -> dict:
    """The §18 enumeration for ONE trail bundle, in the bulletin's shape so the same
    renderer writes it. Every count is over what this bundle carries."""
    from src.bulletin.privacy import (
        _CAVEAT,
        LOCAL_IMPORT_DOMAINS,
        SYNTHETIC_SCHEMES,
        _count_and_examples,
        _item,
    )
    from src.database.models import Article, Source

    items: list[dict] = [
        _item(
            "claim_and_query",
            "The claim you checked and the words searched for it.",
            "They say what you were looking into, in your own words -- often the most "
            "revealing line in the file.",
            present=True,
            basis="trail.json and README.md carry the claim and the query verbatim",
        ),
        _item(
            "source_names_and_domains",
            "The names and domains of the sources in the trail.",
            "Together they are part of your reading list: which publications, in which "
            "countries, in which languages.",
            present=n_sources > 0,
            basis="sources.json carries every source an article of the trail came from",
            n=n_sources,
        ),
        _item(
            "article_ids_and_corpus_totals",
            "This install's own article numbers, and how many articles matched the claim.",
            "The ids mean nothing on another machine; the match count is a lower bound on "
            "how much your corpus holds on the subject.",
            present=True,
            basis="one file per article, named by this install's own id; trail.json "
                  "carries the number of matches",
            n=len(article_ids),
        ),
    ]
    n_news, ex_news = _count_and_examples(
        session, article_ids, Source.domain.in_(LOCAL_IMPORT_DOMAINS), Article.title,
        join_source=True,
    )
    items.append(_item(
        "newsletter_subject_lines",
        "The subject lines of newsletters imported from local mail.",
        "A subject line names a subscription, which no web source reveals.",
        present=n_news > 0,
        basis="articles of the trail whose source is a local .eml or mailbox import; their "
              "titles are the subject lines",
        n=n_news,
        examples=ex_news,
    ))
    clauses = [Article.url.startswith(s) for s in SYNTHETIC_SCHEMES]
    where = clauses[0]
    for extra in clauses[1:]:
        where = where | extra
    n_syn, ex_syn = _count_and_examples(session, article_ids, where, Article.url)
    items.append(_item(
        "synthetic_uris",
        "Addresses this app minted for things it did not fetch from the web.",
        "They say which verticals this install runs, a fact about your setup.",
        present=n_syn > 0,
        basis="article URLs whose scheme this app mints "
              f"({', '.join(SYNTHETIC_SCHEMES)}); a floor, as in the bulletin's list",
        n=n_syn,
        examples=ex_syn,
    ))
    items.append(_item(
        "signing_key",
        "The public key of this install's custody signer.",
        "It proves this install made the bundle, and the same key on every bundle you send "
        "links every recipient's copy to the same install. That is the price of a signature "
        "that proves provenance; a fresh key per bundle would prove only that the file was "
        "not changed.",
        present=True,
        basis="SIGNATURE.json carries the signer's public identity beside the signature",
        examples=[str(identity.get("ed25519_pub") or "")[:16] + "…"],
    ))
    items.append(_item(
        "weather_points_and_windows",
        "The points and date windows of the weather slices carried.",
        "A point and a window say which place and period you were looking into.",
        present=weather_members > 0,
        basis="corroboration/ carries only slices this machine already held; none are "
              "fetched to write the bundle",
        n=weather_members,
    ))
    items.append(_item(
        "timestamps_and_timezone",
        "When the bundle was written, and when each article was published.",
        "A generation time narrows when you were working on this.",
        present=True,
        basis="manifest.json carries generated_at; every article file carries its dates",
    ))
    items.append(_item(
        "publisher_full_text",
        "The full stored text of articles you did not write.",
        "A file that travels carries someone else's words in full. Whether that is yours to "
        "pass on depends on each publisher's terms; this app says the text is there and "
        "does not answer that.",
        present=bool(full_text),
        basis=("each article file carries its whole stored text" if full_text
               else "left out by you: each article file carries its metadata and the SHA-256 "
                    "of its text, not the text"),
        n=len(article_ids) if full_text else None,
    ))
    return {
        "schema": "oo-claim-trail-privacy-1",
        "kind": "claim trail bundle",
        "items": items,
        "items_total": len(items),
        "unmeasured": [],
        "unmeasured_count": 0,
        "articles_measured": len(article_ids),
        "method": _METHOD,
        "caveat": _CAVEAT,
    }


def _readme(ws: dict, *, generated_at: str, full_text: bool, n_articles: int,
            weather_members: int) -> str:
    q = ws.get("query") or {}
    related = ws.get("related") or {}
    out = [
        "# Claim trail",
        "",
        f"> {DISCLOSURE}",
        "",
        "## The claim",
        "",
        "> " + str(ws.get("claim") or "").replace("\n", "\n> "),
        "",
        f"Words searched: `{q.get('text') or ''}`"
        + (" (taken from the claim)" if q.get("derived") else " (typed by the reader)"),
        "",
        "## What this is",
        "",
        "An evidence TRAIL, never a verdict: what one corpus held about this claim when the "
        "bundle was written, and how those articles connect. Nothing in it scores the claim, "
        "and no model wrote any of it.",
        "",
        f"- Written: {generated_at} (UTC).",
        f"- Articles matched: {related.get('total')}; read for this trail: {n_articles}.",
        f"- Full text of each article: {'included' if full_text else 'left out (metadata and SHA-256 only)'}.",
        f"- Weather slices carried: {weather_members} (only slices this machine already held).",
        "",
        "## What is in the file",
        "",
        "- `trail.json`: the trail as the workspace drew it, steps 1 to 5.",
        "- `articles/<id>.json`: each article of the trail.",
        "- `sources.json`: the sources those articles came from.",
        "- `corroboration/`: weather slices for step 4's offers, if any were held.",
        "- `ATTRIBUTION.md`: the licence lines that apply to these contents.",
        "- `WHAT-A-READER-CAN-SEE.md`: what someone holding this file can learn from it.",
        "- `manifest.json`: every file above with its SHA-256, and a Merkle root over them.",
        "- `SIGNATURE.json`: the signature over the manifest, and the key that made it.",
        "",
        "## How to verify it",
        "",
        "1. Every member's SHA-256 must equal the one `manifest.json` lists, no member may be "
        "missing, and nothing else may be in the ZIP besides the manifest and the signature.",
        "2. The signature in `SIGNATURE.json` must verify over the manifest's canonical bytes "
        "(JSON with sorted keys and no spaces).",
        "3. To prove WHO made it, compare the public key in `SIGNATURE.json` with the one the "
        "sender gave you some other way. A valid signature alone proves only that the key "
        "holder made it.",
        "",
        "`python scripts/verify_claim_trail.py <file.zip>` does all three offline.",
        "",
    ]
    return "\n".join(out)


def _article_record(art, source_domain: str | None, *, full_text: bool) -> dict:
    content = art.get_content() or ""
    rec = {
        "id": int(art.id),
        "title": art.title,
        "url": art.url,
        "canonical_url": art.canonical_url,
        "source_id": int(art.source_id) if art.source_id is not None else None,
        "source": source_domain,
        "published_at": art.published_at.isoformat() if art.published_at else None,
        "created_at": art.created_at.isoformat() if art.created_at else None,
        "language": art.language,
        "detected_language": art.detected_language,
        "author": art.author,
        "word_count": art.word_count,
        "stored_hash": art.hash,
        "content_sha256": _sha(content.encode("utf-8")),
        "content_included": bool(full_text),
    }
    if full_text:
        rec["content"] = content
    return rec


def build_trail_bundle(session, ws: dict, *, full_text: bool = True, signer=None,
                       now: datetime | None = None) -> tuple[bytes, dict]:
    """Write the trail ``ws`` as a signed ZIP. Returns ``(zip_bytes, report)``.

    Built in memory: a trail is bounded (``MAX_TRAIL`` articles), and a bundle that never
    touches the disk cannot be left half-written. Raises
    :class:`~src.backup.attribution.PendingRulingError` when the trail carries an
    OSM-derived row (Q823), and :class:`TrailBundleError` when there is nothing to carry.
    """
    from src.backup.attribution import attribution_dicts
    from src.bulletin.evidence import _attribution_markdown
    from src.bulletin.privacy import privacy_markdown
    from src.database.models import Article, Source
    from src.weather.openmeteo import read_cached_slice

    article_ids = [int(a["id"]) for a in (ws.get("related") or {}).get("articles") or []]
    if not article_ids:
        raise TrailBundleError("the trail holds no article, so there is nothing to export")

    # The seam first: a refused bundle reads nothing it would have carried.
    weather: list[tuple[dict, dict]] = []
    for op in (ws.get("corroboration") or {}).get("offers") or []:
        url = op.get("request_url")
        held = read_cached_slice(url) if url else None
        if held is not None:
            weather.append((op, held))

    rows = (
        session.query(Article, Source)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(article_ids))
        .all()
    )
    by_id = {int(a.id): (a, s) for a, s in rows}
    sources: dict[int, dict] = {}
    for _a, s in rows:
        if s is not None:
            sources[int(s.id)] = {
                "id": int(s.id), "name": s.name, "domain": s.domain, "country": s.country,
                "language": s.language, "source_type": s.source_type,
            }
    src_rows = [sources[k] for k in sorted(sources)]
    attribution = attribution_dicts(_signals(carried_tables(ws), src_rows, len(weather)))

    if signer is None:
        from src.custody.settings import load_settings
        from src.custody.signing import HybridSigner

        signer = HybridSigner(use_pqc=load_settings().pqc_enabled)
    identity = signer.public_identity().to_dict()
    generated_at = (now or datetime.now(UTC)).isoformat()

    members: list[dict] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        def add(name: str, text: str) -> None:
            data = text.encode("utf-8")
            zf.writestr(name, data)
            members.append({"name": name, "bytes": len(data), "sha256": _sha(data)})

        present = [aid for aid in article_ids if aid in by_id]
        add("README.md", _readme(ws, generated_at=generated_at, full_text=full_text,
                                 n_articles=len(present), weather_members=len(weather)))
        add("trail.json", _json(ws))
        for aid in present:
            a, s = by_id[aid]
            add(f"articles/{aid}.json",
                _json(_article_record(a, s.domain if s is not None else None, full_text=full_text)))
        add("sources.json", _json(src_rows))
        for n, (op, held) in enumerate(weather, start=1):
            add(f"corroboration/{n}.json", _json({"offer": op, "slice": held}))
        add("ATTRIBUTION.md", _attribution_markdown(attribution))
        add("WHAT-A-READER-CAN-SEE.md", privacy_markdown(trail_privacy(
            session, ws, present, full_text=full_text, identity=identity,
            weather_members=len(weather), n_sources=len(src_rows))))

        manifest = {
            "schema": SCHEMA,
            "generated_at": generated_at,
            "claim": ws.get("claim"),
            "articles": len(present),
            "full_text": bool(full_text),
            "weather_slices": len(weather),
            "disclosure": DISCLOSURE,
            "attribution": attribution,
            "members": members,
            "merkle_root": _merkle([m["sha256"] for m in members]),
            "note": (
                "manifest.json and SIGNATURE.json are not listed in members: a file cannot "
                "carry its own hash, and the signature is made over this manifest"
            ),
        }
        zf.writestr(MANIFEST, _json(manifest))
        signature = signer.sign(_canonical(manifest))
        zf.writestr(SIGNATURE, _json({
            "signed": "the canonical bytes of manifest.json (sorted keys, no spaces)",
            "signature": signature,
            "identity": identity,
        }))

    data = buf.getvalue()
    stamp = generated_at[:10].replace("-", "")
    digest = _sha(str(ws.get("claim") or "").encode("utf-8"))[:8]
    return data, {
        "filename": f"{stamp}-claim-trail-{digest}.zip",
        "bytes": len(data),
        "articles": len(present),
        "full_text": bool(full_text),
        "weather_slices": len(weather),
        "members": [m["name"] for m in members] + [MANIFEST, SIGNATURE],
        "attribution": attribution,
        "algorithm": signature.get("algorithm"),
        "identity": identity,
        "merkle_root": manifest["merkle_root"],
        "disclosure": DISCLOSURE,
    }


def verify_trail_bundle(data: bytes, *, pinned: dict | None = None) -> dict:
    """Check a trail bundle offline.

    Returns ``{verified, problems, issues, signature, key_checked, identity, members}``:
    ``problems`` are ``{code, member?, detail?}`` rows a page can word in its own language;
    ``issues`` are the same, as English lines, for the command-line verifier.

    ``pinned`` is the signer's public identity as the recipient knows it from elsewhere;
    without it the signature is checked against the key the bundle carries, which proves
    the file was not changed since that key signed it, not who holds the key -- and the
    result says which of the two was checked.
    """
    from src.custody.signing import PublicIdentity, verify

    problems: list[dict] = []

    def out(identity=None, members=0, reason=None):
        return {
            "verified": not problems,
            "problems": problems,
            "issues": [_issue_line(p) for p in problems],
            "signature": reason,
            "key_checked": "pinned" if pinned else "the key the bundle carries",
            "identity": identity,
            "members": members,
        }

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        problems.append({"code": "not_zip"})
        return out()
    with zf:
        names = set(zf.namelist())
        if MANIFEST not in names or SIGNATURE not in names:
            problems.append({"code": "no_manifest"})
            return out()
        try:
            manifest = json.loads(zf.read(MANIFEST))
            sig_doc = json.loads(zf.read(SIGNATURE))
        except ValueError:
            problems.append({"code": "unreadable_manifest"})
            return out()
        if manifest.get("schema") != SCHEMA:
            problems.append({"code": "unknown_schema", "detail": str(manifest.get("schema"))})
        listed = manifest.get("members") or []
        listed_names = {m.get("name") for m in listed}
        for m in sorted(listed, key=lambda m: str(m.get("name"))):
            name = m.get("name")
            if name not in names:
                problems.append({"code": "member_missing", "member": name})
            elif _sha(zf.read(name)) != m.get("sha256"):
                problems.append({"code": "member_altered", "member": name})
        for extra in sorted(names - listed_names - {MANIFEST, SIGNATURE}):
            problems.append({"code": "member_extra", "member": extra})
        if _merkle([m.get("sha256") for m in listed]) != manifest.get("merkle_root"):
            problems.append({"code": "merkle_mismatch"})
        identity = sig_doc.get("identity") or {}
        key = dict(identity)
        if pinned:
            key["ed25519_pub"] = pinned.get("ed25519_pub", "")
            # A recipient usually holds the short classical key only. Pinning it is enough
            # to prove provenance: a hybrid signature verifies only when BOTH halves do.
            if pinned.get("ml_dsa_pub"):
                key["ml_dsa_variant"] = pinned.get("ml_dsa_variant")
                key["ml_dsa_pub"] = pinned["ml_dsa_pub"]
        ok, reason = verify(
            sig_doc.get("signature") or {}, _canonical(manifest),
            pinned=PublicIdentity(
                ed25519_pub=key.get("ed25519_pub", ""),
                ml_dsa_variant=key.get("ml_dsa_variant"),
                ml_dsa_pub=key.get("ml_dsa_pub"),
            ),
        )
        if not ok:
            problems.append({"code": "signature", "detail": reason})
    return out(identity, len(listed), reason)


_ISSUE_LINES = {
    "not_zip": "not a ZIP file",
    "no_manifest": "manifest.json or SIGNATURE.json is missing",
    "unreadable_manifest": "manifest.json or SIGNATURE.json is not valid JSON",
    "unknown_schema": "unknown schema {detail!r}",
    "member_missing": "member missing: {member}",
    "member_altered": "member altered: {member}",
    "member_extra": "member not in the manifest: {member}",
    "merkle_mismatch": "the Merkle root does not match the members listed",
    "signature": "signature: {detail}",
}


def _issue_line(problem: dict) -> str:
    return _ISSUE_LINES[problem["code"]].format(
        member=problem.get("member"), detail=problem.get("detail"))
