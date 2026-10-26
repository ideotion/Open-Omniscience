"""Every surface that destroys, stops or overrides stored state is either guarded or accounted for, found by what it DOES (audit 0.5.0 follow-on to the gesture gate; coordinator ruling 2026-10-26).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``test_oo_on_helper_allowlist.py`` finds a destructive ALLOWLISTED name by the verbs inside it. That net has
three holes, and this file closes them the same way (by reading, not by trusting a name):

* the UI's functions are found by the REQUEST they make (a DELETE, or a POST/PUT to a route with a verb in it),
  so ``toggleAiCoordinator`` and ``mbRun`` (a press cancels a running job; no verb in either name) and
  ``deleteCustomPrompt`` (a one-click delete reached from a plain ``onclick``, never from an allowlisted
  binding) cannot hide behind a harmless-sounding name;
* the SERVER's routes are found from the source of every router file, by method and by the verbs in the path or
  the handler's name, and each either takes a ``confirm`` field or sits in a table that says why not;
* the ORM relationships that cascade a delete are listed, because a plain ``DELETE /api/sources/7`` erased every
  article the source had collected and carried no confirmation of its own.

A new destructive route, a new destructive function or a new cascade fails here and is named; the way out is to
guard it or to add a line to a table below with the reason, which a reviewer then reads.

What none of this sees (stated limits): a cascade made by the DATABASE (``ForeignKey(..., ondelete="CASCADE")``, live
because the session turns ``foreign_keys`` on) rather than by an ORM relationship; a ``confirm`` parameter that exists
but is not enforced (the two new routes have behavioural refusal tests, the older ones were read by hand); a request
made through a helper with a variable URL under a name with no verb; and a trusted click that is not intent.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.js_source_helper import _function_span

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_API = _ROOT / "src" / "api"
_OO_ON = (_STATIC / "oo-on.js").read_text(encoding="utf-8")

# The words that destroy, stop, hide or override something, plus the words a ROUTE adds (a restore or a merge is
# additive today, and listed so the day it stops being additive it is read again).
_VERBS = frozenset(
    {
        "delete", "remove", "reset", "disable", "cancel", "exclude", "clear", "erase", "wipe", "purge", "uninstall", "shutdown",
        "panic", "secure", "pause", "stop", "hide", "revert", "discard", "dismiss", "decline", "restore", "prune", "vacuum",
        "merge", "split", "quarantine", "encrypt", "drop", "forget", "undo",
    }
)


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", text)}


def _set_literal(name: str) -> set[str]:
    m = re.search(rf"const {name} = new Set\(\[(.*?)\]\);", _OO_ON, re.S)
    assert m, f"oo-on.js must declare {name} as a literal Set"
    return set(re.findall(r'"([^"]*)"', m.group(1)))


# --------------------------------------------------------------------------------------------------------------- #
# The server: every non-GET route with a destructive verb (or any DELETE), read from the routers' own source.
# --------------------------------------------------------------------------------------------------------------- #

def _refuses_by_default(node: ast.expr | None) -> bool:
    """``confirm: bool = False``, ``Query(False, ...)`` or ``Field(default=False, ...)``; a missing default counts as required."""
    if node is None:
        return True  # no default: the caller has to send it
    if isinstance(node, ast.Call) and node.args:
        return _refuses_by_default(node.args[0])
    if isinstance(node, ast.Call):
        return any(k.arg == "default" and _refuses_by_default(k.value) for k in node.keywords)
    return isinstance(node, ast.Constant) and node.value is False


def _destructive_routes() -> dict[str, tuple[str, str, bool]]:
    """``{module.handler: (METHOD, path, takes_confirm)}`` for every destructive route in ``src/api``."""
    found: dict[str, tuple[str, str, bool]] = {}
    for path in sorted(_API.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        module = path.stem if path.parent == _API else f"{path.parent.name}.{path.stem}"
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in fn.decorator_list:
                if not (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in {"post", "put", "patch", "delete", "api_route"}
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id in {"router", "app"}
                ):
                    continue
                method = dec.func.attr.upper()
                if method == "API_ROUTE":  # @router.api_route(path, methods=[...]): any non-GET method counts
                    listed = next((k.value for k in dec.keywords if k.arg == "methods"), None)
                    names = {str(getattr(e, "value", "")).upper() for e in getattr(listed, "elts", [])}
                    if not names - {"GET", "HEAD", "OPTIONS"}:
                        continue
                    method = "DELETE" if "DELETE" in names else "POST"
                route = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else "?"
                if method != "DELETE" and not (_VERBS & (_words(fn.name) | _words(str(route)))):
                    continue
                positional = fn.args.args
                defaults = [None] * (len(positional) - len(fn.args.defaults)) + list(fn.args.defaults)
                params = list(zip(positional, defaults, strict=True)) + list(
                    zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True)
                )
                # a guard is a parameter named confirm whose default REFUSES: False, Query(False) or Field(default=False)
                confirm = any(a.arg == "confirm" and _refuses_by_default(d) for a, d in params)
                for a, _ in params:  # a request body model with such a field
                    model = classes.get(ast.unparse(a.annotation)) if a.annotation else None
                    if model and any(
                        isinstance(x, ast.AnnAssign)
                        and ast.unparse(x.target) == "confirm"
                        and _refuses_by_default(x.value)
                        for x in model.body
                    ):
                        confirm = True
                found[f"{module}.{fn.name}"] = (method, str(route), confirm)
    return found


_JOB_CONTROL = (
    "stops, pauses or cancels running work: nothing the person stored is removed (a cancelled job may discard its OWN "
    "partial output), and the work can be started again"
)
_REVERSIBLE = "a reversible edit: the paired route puts it back (named in the entry), and nothing is erased"
_ADDITIVE = "adds or merges only: it never overwrites or removes a stored row"
_DERIVED = "removes or rewrites DERIVED data that is rebuilt from what is stored (an index, a finished run's status list, unreferenced rows)"
_FILES = (
    "deletes a public file the app fetched (a dump, a map extract, a model) that can be fetched again, though a newer copy "
    "is not always byte-identical; the UI asks first"
)
_OWN_LISTS = (
    "empties a whole list the person built or decided (pinned cards, search history, imported annotations, dismissals, "
    "one restore's pending alternates); the UI asks first; a server-side confirm for this class is the proposal in "
    "audit-0.5.0/inputs/open-items.md (A-023/A-024 addendum 3)"
)
_ONE_RECORD = (
    "deletes ONE record of the person's own making (no cascade into collected data); the UI asks first; a server-side "
    "confirm for this class is the proposal in audit-0.5.0/inputs/open-items.md (A-023/A-024 addendum 3)"
)

_EXEMPT_GROUPS: dict[str, tuple[str, ...]] = {
    _JOB_CONTROL: (
        "ai.ai_detect_language_cancel", "backup_v2.import_queue_stop", "backup_v2.reindex_backlog_resume_cancel",
        "backup_v2.volume_backup_cancel", "backup_v2.volume_backup_pause", "bulletin.narration_stop",
        "diagnostics.ai_check.ai_check_cancel", "diagnostics.ai_coordinator.ai_coordinator_cancel",
        "diagnostics.corpus.card_audit_cancel", "diagnostics.discovery.discover_world_cancel",
        "diagnostics.keyword_triage.keyword_triage_cancel", "diagnostics.model_bench.model_bench_cancel",
        "diagnostics.p0.p0_validation_cancel", "diagnostics.perception.perception_extract_cancel",
        "diagnostics.release_run.release_run_cancel", "diagnostics.source_tags.source_tags_cancel",
        "geo.osm_download_pause", "jobs.cancel_job", "llm.llm_pull_cancel", "llm.ollama_stop", "llm.vllm_install_cancel",
        "llm.vllm_stop", "quarantine.quarantine_action", "scheduler.scheduler_stop",
        "source_management.qualify_sources_bulk_cancel", "system.unattended_stop", "wiki.dumps_index_cancel",
        "wiki.dumps_pause",
    ),
    _ADDITIVE: (
        "backup_v2.folder_backup_restore", "backup_v2.legacy_restore", "backup_v2.volume_backup_restore",
        "briefing.restore_card", "diagnostics.qualification_merge.source_qualification_merge",
        "signals.signals_record_dismiss_reason",
    ),
    _REVERSIBLE: (
        "briefing.dismiss_card",  # briefing.restore_card
        "insights.exclude_term",  # the exclusion list is editable and a hidden keyword keeps its mentions
        "insights.family_merge", "insights.family_split", "insights.family_override_clear",  # each other
        "insights.remove_keyword_tag",  # POST /keyword-tags
        "insights.remove_supergroup_member",  # POST /supergroups/{id}/members
        "ingestion.newsletter_attach_undo",  # it IS the paired route of the automatic attach; only rows that attach marked move
        "integrity.revert_all", "integrity.revert_collapse",  # POST /collapse/apply
        "law.remove_law_document",  # only stops tracking (watched=False); POST /documents re-activates it
        "quarantine.quarantine_host_pair_confirm", "quarantine.quarantine_host_pair_unconfirm",  # each other
        "source_management.batch_disable_groups", "source_management.batch_disable_sources",  # /batch/enable
        "source_management.batch_remove_tags",  # /batch/tags/add
        "source_management.admission_undo",  # reverses one automatic admission; the audit row stays
        "source_management.disable_unmanaged_language_sources",  # sources stay and can be re-enabled
        "source_management.dismiss_source_candidate",  # the row stays with status "dismissed"
        "source_management.overlay_revert",  # POST /overlay/adopt
        "source_management.remove_source_from_groups", "source_management.remove_sources_from_group",  # /groups/{id}/sources
    ),
    _DERIVED: (
        "backup_v2.import_queue_clear", "database.vacuum", "insights.insights_prune_keywords", "wiki.dumps_index_clear",
    ),
    _FILES: ("geo.osm_download_delete", "llm.llm_remove", "wiki.dumps_delete"),
    _OWN_LISTS: (
        "annotations.remove_author", "backup_v2.alternates_discard_batch", "briefing.clear_dismissed", "briefing.draft_clear",
        "search_advanced.clear_history",
    ),
    _ONE_RECORD: (
        "ai.delete_custom_prompt", "annotations.remove_mine", "briefing.draft_remove", "bulletin.remove_edition",
        "events.feed_remove_user", "insights.delete_supergroup", "markets.delete_rule", "source_management.delete_group",
        "source_management.delete_metadata", "stats.delete_stat_subscription", "watches.delete_watch",
    ),
}
_EXEMPT = {name: reason for reason, names in _EXEMPT_GROUPS.items() for name in names}

#: The routes that take a ``confirm`` field TODAY are found, not listed. These are pinned by name because each
#: cascades into collected data (an ORM ``delete-orphan``) or hides it in bulk, which is what makes a bare request dangerous.
_CASCADE_DELETERS = {"source_management.delete_source", "wiki.delete_page", "quarantine.quarantine_start"}


def test_every_destructive_route_confirms_or_says_why_not() -> None:
    routes = _destructive_routes()
    assert len(routes) >= 91, f"the route finder saw only {len(routes)} destructive routes: it has stopped finding them"
    unaccounted = sorted(n for n, (_, _, confirm) in routes.items() if not confirm and n not in _EXEMPT)
    assert not unaccounted, (
        "destructive routes with neither a confirm field nor an entry in _EXEMPT_GROUPS (guard them, or say why not): "
        + ", ".join(f"{n} [{routes[n][0]} {routes[n][1]}]" for n in unaccounted)
    )


def test_the_exemption_table_has_no_dead_or_contradicted_entries() -> None:
    routes = _destructive_routes()
    dead = sorted(set(_EXEMPT) - set(routes))
    assert not dead, f"_EXEMPT names routes that are not destructive routes any more: {dead}"
    now_guarded = sorted(n for n in _EXEMPT if routes.get(n, ("", "", False))[2])
    assert not now_guarded, f"_EXEMPT lists routes that now take confirm (remove the entry): {now_guarded}"
    listed_twice = [n for n in _EXEMPT if sum(n in names for names in _EXEMPT_GROUPS.values()) > 1]
    assert not listed_twice, f"listed under two reasons: {listed_twice}"


def test_the_routes_that_cascade_into_collected_data_refuse_without_confirm() -> None:
    routes = _destructive_routes()
    for name in sorted(_CASCADE_DELETERS):
        assert name in routes, f"{name} is no longer a destructive route"
        assert routes[name][2], f"{name} cascades into collected data and must take confirm"
        assert name not in _EXEMPT


def test_every_orm_cascade_that_deletes_children_is_accounted_for() -> None:
    """A parent row whose deletion takes children with it: each one says which route can delete it and what guards that."""
    accounted = {
        "Source": "DELETE /api/sources/{id}: takes confirm (it erases the source's articles)",
        "Article": "no route deletes one directly; POST /api/newsletters/remove-imported takes confirm",
        "WikiPage": "DELETE /api/wiki/pages/{id}: takes confirm (it erases the captured revisions)",
        "Watch": "DELETE /api/watches/{id}: a user record; the UI asks 'and its history'; server confirm is the A-023/A-024 proposal",
        "KeywordSuperGroup": "DELETE /api/insights/supergroups/{id}: memberships only, keyword data untouched",
        "LawDocument": "no route deletes it: DELETE /api/law/documents/{id} only stops tracking",
        "KeywordCategory": "no route deletes it",
        "ExternalSource": "no route deletes it",
        "SourceArticle": "no route deletes it directly",
        "MergeBatch": "no route deletes it",
    }
    tree = ast.parse((_ROOT / "src" / "database" / "models.py").read_text(encoding="utf-8"))
    parents: set[str] = set()

    def cascades(call: object) -> bool:
        return (
            isinstance(call, ast.Call)
            and getattr(call.func, "id", "") == "relationship"
            and any(k.arg == "cascade" and "delete" in ast.unparse(k.value) for k in call.keywords)
        )

    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        parents |= {cls.name for node in cls.body if cascades(getattr(node, "value", None))}
    for node in tree.body:  # ``Article.links = relationship(...)`` sits at module level, outside any class body
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and cascades(node.value):
            parents.add(target.value.id)
    assert len(parents) >= 10, f"the cascade finder saw only {len(parents)} parents: it has stopped finding them"
    assert parents == set(accounted), (
        f"cascade parents not accounted for: {sorted(parents - set(accounted))}; "
        f"accounted but gone: {sorted(set(accounted) - parents)}"
    )


# --------------------------------------------------------------------------------------------------------------- #
# The UI: every named function that makes a destructive request confirms, is gated to a gesture, or is listed.
# --------------------------------------------------------------------------------------------------------------- #

_NOT_SCANNED = {"i18n.js", "sw.js", "oo-on.js"}

#: Functions that make a destructive-shaped request without confirming and without being gesture-gated, each with the
#: reason it is safe as it is. The test checks every entry still makes that request, still does not confirm and is
#: not in GESTURE_ONLY, so an entry cannot outlive the reason for it.
_REQUEST_EXEMPT = {
    "_dismissCardNow": "files a dismissed card with its reason; the briefing's Restore puts it back (/api/briefing/restore)",
    "_leadDismissWith": "records the reason a lead was dismissed; additive, nothing is removed",
    "_pruneCore": "garbage-collects keywords with ZERO mentions: derived rows nothing references, rebuilt by the next index",
    "dismissRetiredMode": "clears one informational 'retired mode' notice flag in the scheduler config",
    "overlayMerge": "posts the picked export files and reads back a merged REPORT; it writes no corpus row",
    "runLangDetect": "no caller in src/static (dead code); its cancel half would stop a running detection pass (job control)",
    "stopWikiLane": "switches the wiki lane off in the scheduler config (job control; the toggle switches it on again)",
    "undoAdmission": "reverses ONE automatic admission from the audit list; the audit row stays",
    "volBackupCancel": "no caller in src/static (dead code); it would cancel a volume build, which discards that build's OWN partial set",
}


def _js_files() -> list[Path]:
    """Every first-party script under src/static, vendored libraries and the service worker excluded."""
    return [
        p for p in sorted(_STATIC.rglob("*.js")) if p.name not in _NOT_SCANNED and "vendor" not in p.relative_to(_STATIC).parts
    ]


def _confirms(body: str) -> bool:
    """A confirm()/prompt() that runs on EVERY path to the request: one behind ``&&`` guards only a branch.

    ``runAiCheck`` has ``if (deep && !confirm(...)) return;`` and ``deep`` is false on the cancel half, so a confirm
    counted anywhere in the body vouched for a request it never gates."""
    return any(
        not re.search(r"&&\s*!?\s*$", body[max(0, m.start() - 12) : m.start()])
        for m in re.finditer(r"\b(?:confirm|prompt|_confirmVacuum)\(", body)
    )


def _request_sites() -> dict[str, tuple[str, bool, str]]:
    """``{function: (file, confirms, first destructive request)}`` for every named function with such a request."""
    found: dict[str, tuple[str, bool, str]] = {}
    for path in _js_files():
        js = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:async\s+)?function\s+([\w$]+)\s*\(", js):
            name = m.group(1)
            try:
                _, body_at, body_end = _function_span(js, name)
            except AssertionError:
                continue
            body = js[body_at:body_end]
            why = ""
            for req in re.finditer(r"""["']?method["']?\s*:\s*([^,}]*)""", body):
                verbs = set(re.findall(r"\b(DELETE|POST|PUT|PATCH)\b", req.group(1)))
                if not verbs:
                    continue
                url = (re.findall(r"/api/[A-Za-z0-9_/\-.]*", body[max(0, req.start() - 250) : req.start()]) or ["?"])[-1]
                if "DELETE" in verbs or _VERBS & (_words(name) | _words(url)):
                    why = f"{'/'.join(sorted(verbs))} {url}"
                    break
            if why:
                found[name] = (path.name, _confirms(body), why)
    return found


def test_every_function_that_makes_a_destructive_request_confirms_or_is_accounted_for() -> None:
    sites = _request_sites()
    assert len(sites) >= 65, f"the request finder saw only {len(sites)} functions: it has stopped finding them"
    gated = _set_literal("GESTURE_ONLY")
    bare = sorted(n for n, (_, confirms, _) in sites.items() if not confirms and n not in gated and n not in _REQUEST_EXEMPT)
    assert not bare, "functions that make a destructive request and neither confirm, nor run only for a gesture, nor are listed: " + ", ".join(
        f"{n} ({sites[n][0]}: {sites[n][2]})" for n in bare
    )


def test_the_request_exemptions_are_real_and_not_also_guarded() -> None:
    sites = _request_sites()
    gated = _set_literal("GESTURE_ONLY")
    dead = sorted(set(_REQUEST_EXEMPT) - set(sites))
    assert not dead, f"_REQUEST_EXEMPT names functions that make no destructive request any more: {dead}"
    guarded = sorted(n for n in _REQUEST_EXEMPT if sites[n][1] or n in gated)
    assert not guarded, f"_REQUEST_EXEMPT lists functions that are now guarded (remove the entry): {guarded}"


def test_the_functions_the_request_finder_added_to_the_gesture_gate_stay_there() -> None:
    gated = _set_literal("GESTURE_ONLY")
    for name in ("toggleAiCoordinator", "mbRun", "runAiCheck", "familySplit", "maintAction"):
        assert name in gated, f"{name} makes a destructive request on an allowlisted binding and must run only for a gesture"
    sites = _request_sites()
    assert "deleteCustomPrompt" in sites and sites["deleteCustomPrompt"][1], "deleteCustomPrompt must ask before it deletes"


def test_request_sites_outside_any_named_function_are_the_known_delegated_click_handlers() -> None:
    """Seven requests sit in anonymous callbacks, all inside a delegated ``click`` listener (a person's own click):
    the reader's curation buttons and the task manager's job controls. A new one has to be looked at."""
    outside: dict[str, int] = {}
    for path in _js_files():
        js = path.read_text(encoding="utf-8")
        spans = []
        for m in re.finditer(r"(?:async\s+)?function\s+([\w$]+)\s*\(", js):
            try:
                _, body_at, body_end = _function_span(js, m.group(1))
            except AssertionError:
                continue
            spans.append((body_at, body_end))
        for req in re.finditer(r"""["']?method["']?\s*:\s*[^,}]*\b(?:DELETE|POST|PUT|PATCH)\b""", js):
            if not any(a <= req.start() < b for a, b in spans):
                outside[path.name] = outside.get(path.name, 0) + 1
    assert outside == {"reader.js": 3, "taskmanager.js": 4}, outside
