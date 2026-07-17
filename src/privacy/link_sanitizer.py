"""
Network-free sanitisation of links found in imported newsletters.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Newsletter links are engineered to identify the *recipient*: click-tracking
redirect wrappers embed a per-subscriber token, and otherwise-clean URLs carry
recipient query parameters (``mc_eid``, ``mkt_tok`` ...). This module strips what
it can, flags what it cannot, and **never makes a network call** -- we refuse to
contact a tracker even to resolve a destination, because doing so confirms the
"open/click" back to the sender and can deanonymise the recipient.

Three outcomes per URL:
  * **clean** -- recipient/campaign params stripped from an ordinary link;
  * **unwrapped** -- a redirect wrapper whose true destination was embedded in
    the URL (no network needed) is recovered, then itself cleaned;
  * **tracker-wrapped** -- a wrapper whose destination is resolved *server-side*
    (unrecoverable without a refused network call) and whose path is typically
    recipient-keyed: we keep only ``scheme://host`` and flag it, never present
    it as the real source.

The denylists are an evidence-based snapshot (``DENYLIST_AS_OF``); novel trackers
may pass. The honest claim is "removed all KNOWN trackers as of <date>", never
"anonymised" -- no fabricated security.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

DENYLIST_AS_OF = "2026-06-15"

# Query parameters that identify the individual recipient. Stripped from any URL
# we keep. Compared lowercase.
RECIPIENT_PARAMS: frozenset[str] = frozenset(
    {
        "mc_eid",  # Mailchimp per-recipient id
        "mkt_tok",  # Marketo recipient token (base64 of the lead id)
        "_hsenc",
        "_hsmi",  # HubSpot
        "ck_subscriber_id",  # ConvertKit
        "oly_enc_id",
        "oly_anon_id",  # Sailthru
        "vero_id",
        "vero_conv",  # Vero
        "ml_subscriber",
        "ml_subscriber_hash",  # MailerLite
        "sib_id",  # Sendinblue / Brevo
        "_branch_match_id",
    }
)

# Campaign params -- not recipient-identifying, but useless in a research corpus
# and occasionally recipient-keyed. Stripped too (kept as a SEPARATE set so the
# distinction stays documented and a caller could choose to keep them).
CAMPAIGN_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "mc_cid",  # Mailchimp campaign id (not the recipient -- but noise)
        "gclid",
        "fbclid",
        "igshid",
    }
)

# Query-parameter names that may hold the *real destination* of a redirect
# wrapper, so we can recover it locally (no network). A value is only accepted if
# it decodes to an ``http(s)`` URL, so harmless same-named params (e.g. Mailchimp
# ``u=<userid>``) are ignored.
_EMBED_PARAMS: frozenset[str] = frozenset(
    {"url", "u", "redirect", "redirect_url", "destination", "dest", "target", "r", "q", "upn", "ru"}
)

# Hosts whose links resolve the destination SERVER-SIDE (not in the URL) and
# whose path is typically recipient-keyed. Matched as a suffix.
_OPAQUE_HOST_SUFFIXES: tuple[str, ...] = (
    "list-manage.com",  # Mailchimp
    "sendgrid.net",
    "beehiiv.com",
    "mailgun.org",
    "sparkpostmail.com",
    "rs6.net",  # Constant Contact
    "mailchimpapp.net",
    "sendgrid.com",
    "hubspotlinks.com",
    "mandrillapp.com",
)

# Path markers of click-tracking wrappers (kept specific to avoid catching
# legitimate URLs).
_OPAQUE_PATH_MARKERS: tuple[str, ...] = (
    "/track/click",
    "/ss/c/",
    "/ls/click",
    "/wf/click",
    "/wf/open",
    "/cl0/",
)

_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}>\"'"


@dataclass
class SanitizedLink:
    """The outcome of sanitising one URL."""

    original: str
    url: str  # cleaned/unwrapped URL, or bare ``scheme://host`` when tracker-wrapped
    tracker_wrapped: bool = False
    unwrapped: bool = False
    stripped_params: list[str] = field(default_factory=list)
    text: str | None = None  # visible anchor text, when known (recipient-safe)


@dataclass
class SanitizeStats:
    """Counts surfaced to the user so the de-tracking is honest and visible."""

    links_seen: int = 0
    params_stripped: int = 0
    unwrapped: int = 0
    trackers_wrapped: int = 0


def _norm(u: str) -> str:
    return u.strip().rstrip("/").lower()


def _try_b64(value: str) -> str | None:
    """Best-effort base64 / base64url decode to UTF-8; ``None`` on failure."""
    s = value.strip()
    if len(s) < 8:
        return None
    pad = "=" * (-len(s) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return decoder(s + pad).decode("utf-8")
        except Exception:
            continue
    return None


def _as_http_url(value: str) -> str | None:
    """Return ``value`` as an http(s) URL if it plainly is one (or base64-encodes one)."""
    s = unquote(value)
    if s.lower().startswith(("http://", "https://")):
        return s
    decoded = _try_b64(value)
    if decoded and decoded.lower().startswith(("http://", "https://")):
        return decoded
    return None


def _embedded_in_path(path: str) -> str | None:
    """A redirect destination sometimes sits inside the path (plain or %-encoded)."""
    decoded = unquote(path)
    m = re.search(r"https?://[^\s]+", decoded)
    return m.group(0) if m else None


def _is_parseable_url(s: str) -> bool:
    """True iff ``urlsplit`` accepts ``s`` without raising.

    A recovered/embedded destination is an UNQUOTED, attacker- or
    sender-encoding-bug-controlled string -- it can contain a malformed
    IPv6-literal-looking bracket sequence (``[bad-ipv6-not-closed/x``) that
    ``urlsplit`` raises ``ValueError`` on. That must never propagate: a single
    malformed embedded link would otherwise crash the whole ``sanitize_text``
    call, and by extension the caller's whole message batch (field bug
    2026-07-16, reproduced directly against this module -- a percent-encoded
    ``?url=http://[bad-ipv6-not-closed/x`` redirect-wrapper param crashed
    ``ingest_emails`` for the entire uncommitted batch, not just this one
    message). Only a recovered candidate that ``urlsplit`` genuinely accepts is
    ever treated as a destination; anything else is honestly "not a valid
    embedded URL", not a crash.
    """
    try:
        urlsplit(s)
    except ValueError:
        return False
    return True


def _recover_destination(parts) -> str | None:
    for key, val in parse_qsl(parts.query, keep_blank_values=False):
        if key.lower() in _EMBED_PARAMS and val:
            cand = _as_http_url(val)
            if cand and _is_parseable_url(cand):
                return cand
    embedded = _embedded_in_path(parts.path)
    return embedded if embedded and _is_parseable_url(embedded) else None


def _host_of(parts) -> str:
    return parts.netloc.lower().split("@")[-1].split(":")[0]


def _is_opaque_tracker(host: str, path: str) -> bool:
    if any(host == s or host.endswith("." + s) for s in _OPAQUE_HOST_SUFFIXES):
        return True
    pl = path.lower()
    return any(marker in pl for marker in _OPAQUE_PATH_MARKERS)


def sanitize_url(url: str, text: str | None = None, _depth: int = 0) -> SanitizedLink:
    """Sanitise a single URL. Pure; never touches the network.

    Belt-and-braces (field bug 2026-07-16): ``_recover_destination`` already
    validates a recovered/embedded destination before it reaches here, but this
    function is also a public entry point callable directly with untrusted
    input. Any unanticipated ``urlsplit``/``urlunsplit`` failure on a malformed
    URL degrades to "leave this one link unsanitised" rather than crashing the
    caller's whole batch -- a single bad link must never cost every other
    message in an import its data.
    """
    try:
        return _sanitize_url_inner(url, text, _depth)
    except ValueError:
        return SanitizedLink(original=url, url=url, text=text)


def _sanitize_url_inner(url: str, text: str | None, _depth: int) -> SanitizedLink:
    raw = url
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        # mailto:, tel:, etc. -- no recipient-tracking surface we handle here.
        return SanitizedLink(original=raw, url=url, text=text)

    # 1) Unwrap a redirect wrapper whose destination is embedded in the URL.
    if _depth < 3:
        dest = _recover_destination(parts)
        if dest and _norm(dest) != _norm(url):
            inner = sanitize_url(dest, text=text, _depth=_depth + 1)
            inner.original = raw
            inner.unwrapped = True
            return inner

    # 2) Opaque tracker wrapper -- destination is server-side, path recipient-keyed.
    host = _host_of(parts)
    if _is_opaque_tracker(host, parts.path):
        bare = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        return SanitizedLink(original=raw, url=bare, tracker_wrapped=True, text=text)

    # 3) Ordinary link -- strip recipient + campaign params (keep order, keep fragment).
    kept: list[tuple[str, str]] = []
    stripped: list[str] = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in RECIPIENT_PARAMS or key.lower() in CAMPAIGN_PARAMS:
            stripped.append(key)
        else:
            kept.append((key, val))
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    return SanitizedLink(original=raw, url=cleaned, stripped_params=stripped, text=text)


def sanitize_text(text: str) -> tuple[str, SanitizeStats]:
    """Rewrite every http(s) URL found in plain text to its sanitised form.

    Tracker-wrapped links are replaced with a visible, recipient-safe marker
    (``[tracked link -> scheme://host]``) rather than silently kept or dropped.
    """
    stats = SanitizeStats()
    if not text:
        return text, stats

    def _repl(m: re.Match[str]) -> str:
        raw = m.group(0)
        trail = ""
        while raw and raw[-1] in _TRAILING:
            trail = raw[-1] + trail
            raw = raw[:-1]
        link = sanitize_url(raw)
        stats.links_seen += 1
        stats.params_stripped += len(link.stripped_params)
        if link.unwrapped:
            stats.unwrapped += 1
        if link.tracker_wrapped:
            stats.trackers_wrapped += 1
            return f"[tracked link -> {link.url}]" + trail
        return link.url + trail

    return _URL_RE.sub(_repl, text), stats
