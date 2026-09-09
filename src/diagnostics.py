"""
``open-omniscience doctor`` -- a friendly health check.

Prints a plain-language report so a non-technical user (or a bug report) can see
at a glance whether the install is healthy: Python version, where data lives and
whether it is writable, the database and what's in it, which optional components
are present, and whether the local LLM (Ollama) is reachable.

Design rules: never crash (every probe is isolated and degrades to a clear line),
never touch the network except the explicit, local Ollama check, and exit non-zero
only when something is actually broken (a critical FAIL), so scripts/CI can rely on
the exit code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ANSI only when writing to a terminal.
if sys.stdout.isatty():
    _G, _Y, _R, _B, _D, _RST = (
        "\033[32m",
        "\033[33m",
        "\033[31m",
        "\033[1m",
        "\033[2m",
        "\033[0m",
    )
else:
    _G = _Y = _R = _B = _D = _RST = ""

OK, WARN, FAIL = f"{_G}ok{_RST}", f"{_Y}!!{_RST}", f"{_R}XX{_RST}"


class _Report:
    """Collects lines and tracks whether anything failed (for the exit code)."""

    def __init__(self) -> None:
        self.failed = False

    def line(self, status: str, label: str, detail: str = "") -> None:
        tail = f"  {_D}{detail}{_RST}" if detail else ""
        print(f"  [{status}] {label}{tail}")
        if status == FAIL:
            self.failed = True


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("open-omniscience")
    except Exception:
        return "unknown"


def _check_python(r: _Report) -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} at {sys.executable}"
    if (v.major, v.minor) in ((3, 13), (3, 14)):
        r.line(OK, "Python", detail)
    else:
        r.line(WARN, "Python", f"{detail} -- this project targets 3.13+")
    # The stdlib venv/ensurepip module is a separate apt package on Debian/Ubuntu;
    # flag it so a broken base interpreter (can't create venvs / reinstall) is
    # visible rather than only surfacing as a cryptic installer failure.
    import importlib.util

    if importlib.util.find_spec("ensurepip") is not None:
        r.line(OK, "venv module", "ensurepip available")
    else:
        r.line(
            WARN,
            "venv module",
            "missing -- install python3-venv (Qubes: in the TemplateVM) to (re)create the virtualenv",
        )


def _check_data_dir(r: _Report) -> Path | None:
    try:
        from src.paths import data_dir

        d = data_dir()
    except Exception as exc:  # pragma: no cover - defensive
        r.line(FAIL, "Data directory", f"could not resolve: {exc}")
        return None
    if os.access(d, os.W_OK):
        r.line(OK, "Data directory", str(d))
    else:
        r.line(FAIL, "Data directory", f"{d} is NOT writable")
    return d


def _brief(exc: Exception, limit: int = 200) -> str:
    """One bounded line describing an exception.

    A SQLAlchemy error stringifies to the failing statement plus a docs URL: the
    schemaless-database case below produced a fifteen-line SELECT dump with every
    column of ``sources`` spelled out, inside a report whose whole purpose is to be
    readable by someone who is not a programmer. The FIRST line carries the cause
    ("(sqlite3.OperationalError) no such table: sources"); the rest is the essay.
    Keep the cause, bound the length, and never let a probe's detail line become a
    page.
    """
    first = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    first = " ".join(first.split())
    return first if len(first) <= limit else first[: limit - 1] + "\u2026"


def _check_database(r: _Report) -> None:
    try:
        from src.database.models import Article, Source
        from src.database.session import DATABASE_URL, engine, session_scope
    except Exception as exc:
        r.line(FAIL, "Database", f"could not import layer: {exc}")
        return
    where = DATABASE_URL.replace("sqlite:///", "")
    if DATABASE_URL.startswith("sqlite") and not Path(where).exists():
        r.line(WARN, "Database", f"not created yet ({where}); it builds on first launch")
        return
    # A file that EXISTS but carries no schema is the SAME situation as no file at
    # all -- first launch has not finished building it -- and it was reported as a
    # critical [XX] with a raw SQL dump, which is neither true nor readable. It is a
    # reachable state for a real operator (an interrupted first launch, or a database
    # that has been alembic-STAMPED without being upgraded) and not only a test
    # artifact, though a test found it: importing the API app stamps the revision, so
    # `doctor` run afterwards in the same process failed on a healthy install.
    #
    # Asked of the INSPECTOR rather than by matching the driver's error text: "no
    # such table" is SQLite's wording, not SQLAlchemy's, and a string match would
    # quietly stop working on any other backend. If inspection itself fails, say
    # nothing here and let the query below report the real reason.
    try:
        from sqlalchemy import inspect as _sa_inspect

        insp = _sa_inspect(engine)
        missing = [t for t in (Source.__tablename__, Article.__tablename__) if not insp.has_table(t)]
    except Exception:
        missing = []
    if missing:
        r.line(
            WARN,
            "Database",
            f"no schema yet ({where}); missing: {', '.join(missing)} -- it builds on first launch",
        )
        return
    try:
        with session_scope() as s:
            sources = s.query(Source).count()
            articles = s.query(Article).count()
        r.line(OK, "Database", f"{sources} sources, {articles} articles ({where})")
    except Exception as exc:
        r.line(FAIL, "Database", f"reachable but query failed: {_brief(exc)}")


def _check_components(r: _Report) -> None:
    # Analysis extra: representative imports.
    try:
        import numpy  # noqa: F401
        import vaderSentiment  # noqa: F401

        r.line(OK, "Analysis tools", "installed (numpy, sentiment, ...)")
    except Exception:
        r.line(WARN, "Analysis tools", "not installed -- add with: ./install.sh (choose Analysis)")


def _check_ollama(r: _Report) -> None:
    try:
        from src.llm.ollama import CATALOG_AS_OF, OLLAMA_TESTED_VERSION, OllamaClient

        client = OllamaClient()
        if client.is_available():
            models = client.list_installed()
            client.close()
            if models:
                r.line(
                    OK,
                    "Local LLM (Ollama)",
                    f"running; models: {', '.join(models)} "
                    f"(tested with Ollama {OLLAMA_TESTED_VERSION}; pick models in-app -> "
                    f"Settings -> Local models; suggestions as of {CATALOG_AS_OF})",
                )
            else:
                r.line(
                    WARN,
                    "Local LLM (Ollama)",
                    "running but no models -- pull one in-app (Settings -> Local models) "
                    "or run: ollama pull llama3.2:1b",
                )
        else:
            client.close()
            r.line(
                WARN, "Local LLM (Ollama)", "not reachable (LLM features will say 'unavailable')"
            )
    except Exception as exc:
        r.line(WARN, "Local LLM (Ollama)", f"not available: {exc}")


def _check_launcher(r: _Report) -> None:
    xdg = os.getenv("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    desktop = base / "applications" / "open-omniscience.desktop"
    mac = Path.home() / "Desktop" / "Open Omniscience.command"
    if desktop.exists() or mac.exists():
        r.line(
            OK, "Launcher", "installed (look for 'Open Omniscience' in your apps menu / Desktop)"
        )
    else:
        r.line(WARN, "Launcher", "not installed -- re-run ./install.sh to create it")


def run_doctor() -> int:
    """Print the report; return 0 if healthy, 1 if any critical check failed."""
    print(f"\n{_B}Open Omniscience -- doctor{_RST}  (v{_app_version()})\n")
    r = _Report()
    _check_python(r)
    _check_data_dir(r)
    _check_database(r)
    _check_components(r)
    _check_ollama(r)
    _check_launcher(r)
    print()
    if r.failed:
        print(f"  {_R}{_B}Some critical checks failed.{_RST} See the [XX] lines above.\n")
        return 1
    # NOT "optional extras you can add later": two of the warnings this report can
    # emit are about the database not being built yet, which is neither optional nor
    # an extra. The line now says the one thing that is true of every (!!) -- it is
    # not a failure -- and sends the reader to the line itself for what it needs.
    print(
        f"  {_G}{_B}Core looks healthy.{_RST} "
        f"Warnings (!!) are not failures -- each line says what it is missing.\n"
    )
    return 0
