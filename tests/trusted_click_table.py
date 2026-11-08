"""The names a person's own click reaches with no prompt, each with the reason that is acceptable (A-024 stage 2, R443).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Not a test module (no ``test_`` prefix): ``test_oo_on_helper_allowlist.py`` and ``test_destructive_surfaces.py`` both read it.

This replaces ``GESTURE_ONLY``, the 31-name list ``src/static/oo-on.js`` used to carry. That list GATED: a listed name ran only for
a trusted click. Stage 2 gates EVERY name that way (``TRUSTED_EVENTS``), so a list in the dispatcher would gate nothing and could
only drift. What is left to say is an ACCOUNT, and it belongs next to the tests that hold it: of the names that stop, pause, cancel,
erase, remove or hide something and have no ``confirm()`` in their own body, why a trusted click alone is enough. A name found by
either finder (the verbs in its name, the request it makes) has to confirm, sit in ``_VIEW_ONLY``/``_REQUEST_EXEMPT`` or sit here;
an entry here whose function starts to confirm, or that is bound to anything but a click, fails and is named.

The five that left the old list because they now ask first: ``removeAnnotation``, ``removeAuthor``, ``removeDraftItem``,
``familyResetGroup`` (new prompts, R443) and ``secureErase`` (which already asked; it was listed from before that).
"""

from __future__ import annotations

_JOB = (
    "stops, pauses or cancels running work: it can be started or resumed again, what is lost is the work done so far, and "
    "nothing the person wrote or collected is erased"
)
_CURATION = (
    "a one-click curation edit the person redoes or reverses in one click (a paired control, Settings, or re-import); "
    "nothing the person authored is lost"
)

_GROUPS: dict[str, tuple[str, ...]] = {
    _JOB: (
        "_uxPauseResume", "cancelP0Validation", "cancelPull", "dumpFtsCancel", "jobCancel", "maintAction", "mbRun",
        "pauseDump", "pauseOsm", "qualifyBulkCancel", "releaseRunCancel", "runAiCheck", "schedulerStop", "stopVllm",
        "toggleAiCoordinator", "unattendedStop",
    ),
    _CURATION: (
        "disableUnmanagedLanguages",  # its own toast says it: the sources are kept, re-enable any time
        "excludeKeyword",             # Settings lists every exclusion and re-includes it
        "familySplit",                # familyResetGroup (which asks) puts the family back
        "kxHide",                     # the same exclusion list as excludeKeyword
        "kxRemoveTag",                # the tag is added again from the same box
        "lawSetWatched",              # the watch toggle; resuming re-adds by URL and asks to go online
        "osmPickRemove",              # one region leaves the picker's selection; picking it again is one click
        "removeUserCalendar",         # the route says it: reversible, re-import the .ics
        "revertAllCollapse",          # it IS the undo of the integrity collapses
        "sgRemoveMember",             # the super-group's member list: add it again
    ),
}

#: ``{name: reason}`` for every name that runs on a trusted click with no prompt of its own.
TRUSTED_CLICK_ONLY: dict[str, str] = {name: reason for reason, names in _GROUPS.items() for name in names}

#: Destructive names that left the old gesture list because they confirm in their own body now.
NOW_CONFIRM = ("familyResetGroup", "removeAnnotation", "removeAuthor", "removeDraftItem", "secureErase")
