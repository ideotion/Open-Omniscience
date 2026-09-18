"""
Wikimedia ORES (edit-quality model) client + response parser.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ORES is a Wikimedia service giving per-revision "damaging" and "good-faith"
probabilities. We use it as an *attributed* signal: scores are stored with their
provenance and presented as "labelled-by-ORES", never as ground truth. Optional
and fail-open — if the service is unavailable, tracking proceeds without scores.

The parser is pure (unit-tested with a fixture); the HTTP call is injectable.
"""

from __future__ import annotations

import logging

from src.ingest import OO_VERSION

_LOG = logging.getLogger(__name__)
ORES_ENDPOINT = "https://ores.wikimedia.org/v3/scores"
PROVENANCE = "ores:damaging,goodfaith"
ORES_USER_AGENT = f"OpenOmniscienceBot/{OO_VERSION} (+https://github.com/ideotion/Open-Omniscience)"

#: When this endpoint's SHAPE was last confirmed against the live service.
#:
#: Q717 = a asks to "verify Wikimedia's current scoring endpoint (the ORES -> Lift Wing
#: migration, FROM MEMORY), keep it opt-in, approximate-labelled". THE VERIFICATION IS
#: THE OPERATOR'S AND IT HAS NOT HAPPENED: every Wikimedia host answers ``000`` from
#: the sandbox this was written in (probed 2026-09-17, with ``api.github.com``
#: answering 200 as the control), so a claim here that the endpoint was checked would
#: be a fabricated measurement. The date below is the date of the LAST verification on
#: record, not today's, and the registry's freshness check is what surfaces the gap.
#:
#: WHAT IS FROM MEMORY, NAMED AS SUCH: Wikimedia announced a migration of its scoring
#: models from ORES to Lift Wing. This app has NOT confirmed whether the v3 path above
#: still answers, what it answers with, or what the replacement's shape is. Nothing
#: here has been changed on the strength of that memory -- guessing a new URL would be
#: worse than an old one that fails loudly, and :meth:`OresClient.score` now fails
#: loudly (see :data:`OUTCOMES`).
#:
#: THE DATE IS THE ONE THE RECORD SUPPORTS AND NO BETTER: it is the day this client was
#: written against the documented v3 shape (``ce8450f0``, git-verified), which is the
#: last moment anyone in this repository is known to have looked at that shape. It is
#: NOT a re-verification, and dating it today to make a freshness check go quiet would
#: be the fabricated-pass shape.
ORES_AS_OF = "2026-06-06"

#: What one scoring attempt DID. The closed vocabulary exists because the old code
#: returned ``{}`` for every failure, so "this service no longer exists" and "the
#: network hiccuped" were indistinguishable -- and an app whose scores quietly stopped
#: appearing would look to its operator like a wiki nobody was vandalising.
#:
#: These are TOKENS. The sentence an operator reads is composed by the UI and ships x12.
OUTCOMES: tuple[str, ...] = (
    "ok",
    "empty_request",
    "endpoint_gone",       # 404/410: the strongest available evidence of the migration
    "refused_offline",     # OUR kill switch, named as ours (invariant #14e's corollary)
    "http_error",
    "transport_error",
    "unreadable_response",
)


def dbname(wiki: str) -> str:
    """Wiki code -> ORES database name (e.g. 'en' -> 'enwiki')."""
    return f"{(wiki or 'en').strip().lower()}wiki"


def _prob_true(model_block: dict) -> float | None:
    try:
        return float(model_block["score"]["probability"]["true"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_ores(payload: dict, wiki: str) -> dict:
    """Parse an ORES v3 response into {revid: {damaging, goodfaith, provenance}}."""
    out: dict[int, dict] = {}
    scores = (payload or {}).get(dbname(wiki), {}).get("scores", {})
    for revid_str, models in scores.items():
        try:
            revid = int(revid_str)
        except (TypeError, ValueError):
            continue
        out[revid] = {
            "damaging": _prob_true(models.get("damaging", {})),
            "goodfaith": _prob_true(models.get("goodfaith", {})),
            "provenance": PROVENANCE,
        }
    return out


class OresClient:
    """Score revisions via ORES. ``session`` is injectable for testing."""

    def __init__(
        self,
        *,
        session=None,
        timeout: float = 20.0,
        user_agent: str = ORES_USER_AGENT,
    ):
        # Through the guarded factory: kill switch + protected-mode proxy apply
        # to ORES too. ``session`` stays injectable for the pure-parser tests.
        if session is None:
            from src.safety.fetcher import guarded_session

            session = guarded_session(user_agent=user_agent)
        else:
            session.headers.update({"User-Agent": user_agent})
        self.session = session
        self.timeout = timeout
        #: What the LAST attempt did, as one of :data:`OUTCOMES`. ``None`` before any
        #: attempt -- an absence, never "ok".
        self.last_outcome: str | None = None
        #: The detail behind a non-ok outcome, for a log or a status line. Never shown
        #: to an operator as prose in their own language; the UI composes that.
        self.last_detail: str | None = None

    def _note(self, outcome: str, detail: str | None = None) -> None:
        self.last_outcome = outcome
        self.last_detail = detail

    def score(self, wiki: str, revids: list[int]) -> dict:
        """Return {revid: {...}} for the given revids. Empty on any failure.

        STILL FAIL-OPEN, and now fail-LOUD. Tracking never breaks on a scoring
        failure -- that contract is unchanged and is why this returns ``{}`` rather
        than raising. What changed is that the failure is NAMED on
        :attr:`last_outcome` instead of vanishing: a 404 or 410 from this path is the
        strongest evidence available from inside the app that the ORES -> Lift Wing
        migration has landed (Q717), and the old code turned exactly that signal into
        the same empty dict as a dropped packet.
        """
        if not revids:
            self._note("empty_request")
            return {}
        params = {"models": "damaging|goodfaith", "revids": "|".join(str(r) for r in revids)}
        try:
            resp = self.session.get(
                f"{ORES_ENDPOINT}/{dbname(wiki)}/", params=params, timeout=self.timeout
            )
        except Exception as exc:  # noqa: BLE001 - ORES is optional; never break tracking
            # OUR OWN REFUSAL IS NAMED AS OURS. Invariant #14e's corollary: an
            # operator pointed at Wikimedia for their own airplane mode has been sent
            # to look in the wrong place.
            from src.ingest import kill_switch_active

            if kill_switch_active():
                self._note("refused_offline", "the network kill switch is active (airplane mode)")
                _LOG.info("ORES scoring refused by THIS APP: airplane mode is engaged")
            else:
                self._note("transport_error", f"{type(exc).__name__}: {exc}")
                _LOG.warning("ORES scoring failed for %s", wiki, exc_info=True)
            return {}
        status = getattr(resp, "status_code", None)
        if status in (404, 410):
            self._note("endpoint_gone", f"HTTP {status} from {ORES_ENDPOINT}")
            # WARNING, not debug: this is the one failure that means the feature is
            # over rather than unlucky, and it is what Q717's verification is looking
            # for. An operator whose scores stopped deserves to find this in the log.
            _LOG.warning(
                "the scoring endpoint answered HTTP %s -- ORES may have been retired in "
                "favour of Lift Wing. Scores are off until this app is updated; nothing "
                "else about tracking is affected.",
                status,
            )
            return {}
        try:
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            self._note("http_error", f"{type(exc).__name__}: {exc}")
            _LOG.warning("ORES scoring failed for %s", wiki, exc_info=True)
            return {}
        try:
            out = parse_ores(resp.json(), wiki)
        except Exception as exc:  # noqa: BLE001
            # A 200 whose BODY is not what this parser expects is its own outcome: it
            # is what a migrated service answering at the old path would look like.
            self._note("unreadable_response", f"{type(exc).__name__}: {exc}")
            _LOG.warning("ORES answered with a body this build cannot read", exc_info=True)
            return {}
        self._note("ok")
        return out
