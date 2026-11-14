"""ONE read path for the fail-open settings modules (A-036; R469).

``config/app_settings``, ``scheduler/settings`` and ``custody/settings`` each held a
byte-for-byte copy of the same four functions (``_use_kv``, ``_read_json_file``,
``_read_raw``, ``_read_raw_strict``) that differed only in the file name, the kv key, the
module's own error-class pair and a log string. They now delegate here; each module keeps
its own module-level names as one-line wrappers, so every caller and every test that
patches ``_settings_path`` or ``_use_kv`` is unchanged.

DELIBERATELY NOT HERE:
* ``safety/settings.py`` -- it fails CLOSED on a failed read (a read failure must never
  read as the default direct connection); this class fails OPEN (an unreadable file reads
  as the defaults, and the strict reader refuses instead). Folding the two would change one
  of them.
* the WRITE side -- the modules write separately (app_settings and scheduler each call
  atomic_replace at their own site, custody does too). It is not part of the read fold.

``scheduler/settings.py`` takes no module-level ``src.`` import (tests/test_wiki_tiers.py),
so its wrappers import this module inside the function.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable


class SettingsStore:
    """The read side of one settings blob: kv row first, legacy JSON file second."""

    def __init__(
        self,
        *,
        kv_key: str,
        file_name: str,
        path_getter: Callable[[], object],
        refusal: type[Exception],
        damaged: type[Exception],
        log: logging.Logger,
        use_kv_hook: Callable[[], bool] | None = None,
        json_hook: Callable[[], dict | None] | None = None,
    ) -> None:
        self.kv_key = kv_key
        self.file_name = file_name
        # Called at USE time, never captured: tests redirect the module's ``_settings_path``.
        self.path_getter = path_getter
        self.refusal = refusal
        self.logger_name = log.name  # the MODULE's own logger, so records keep their name
        self.damaged = damaged
        # The module's OWN wrappers, so a test that patches ``_use_kv`` / ``_read_json_file``
        # on the module still steers ``read_raw`` exactly as it did when the code lived there.
        self._use_kv = use_kv_hook or self.use_kv
        self._json = json_hook or self.read_json_file

    def use_kv(self) -> bool:
        """The encrypted ``app_state`` store at the DEFAULT location; a redirected path
        (test isolation) is honoured as JSON instead."""
        from src.paths import data_dir

        return self.path_getter() == data_dir() / self.file_name

    def read_json_file(self) -> dict | None:
        path = self.path_getter()
        if not path.exists():  # type: ignore[attr-defined]
            return None
        try:
            return json.loads(path.read_text("utf-8"))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - a bad file must not take the app down
            logging.getLogger(self.logger_name).warning("%s is unreadable; using defaults (%s)", self.file_name, type(exc).__name__)
            return None

    def _migrate(self, raw: dict) -> None:
        from src.config.kv_store import kv_set_json

        try:
            kv_set_json(self.kv_key, raw)
        except Exception as exc:  # noqa: BLE001 - migration is best-effort; retried next load
            logging.getLogger(self.logger_name).debug("%s migration into app_state deferred (%s)", self.file_name, type(exc).__name__)

    def read_raw(self) -> dict | None:
        """The ``app_state`` row, else the legacy file (migrated once). Any failure reads as
        ``None``/the file: a settings read must never take the app down."""
        if not self._use_kv():
            return self._json()
        from src.config.kv_store import kv_get_json

        raw = kv_get_json(self.kv_key)
        if raw is not None:
            return raw
        raw = self._json()
        if raw is None:
            return None
        self._migrate(raw)
        return raw

    def read_raw_checked(self) -> dict | None:
        """``read_raw`` that tells UNREADABLE from unset: a stored row that could not be read raises the module's error
        class (``damaged`` for a value there and unparseable), where ``read_raw`` reads it as absent. Same read as
        ``read_raw`` (read-only open, the 2 s hold on a failed read): for a reader, not for a save."""
        if not self._use_kv():
            return self._json()
        from src.config.kv_store import KvReadError, is_damaged, kv_get_json_checked, refusal_text

        try:
            raw = kv_get_json_checked(self.kv_key)
        except KvReadError as exc:  # refused, by class, as read_raw_strict does
            raise (self.damaged if is_damaged(exc) else self.refusal)(refusal_text(exc)) from None
        if raw is not None:
            return raw
        raw = self._json()
        if raw is None:
            return None
        self._migrate(raw)
        return raw

    def read_raw_strict(self) -> dict | None:
        """``read_raw`` for a caller that will REWRITE what it read: a stored row that cannot
        be read raises the module's error class (the class only, never the engine's text)
        instead of reading as the defaults."""
        if not self._use_kv():
            return self._json()
        from src.config.kv_store import is_damaged, kv_get_json_strict, refusal_text

        try:
            raw = kv_get_json_strict(self.kv_key)
        except Exception as exc:  # noqa: BLE001 - refused, by class
            raise (self.damaged if is_damaged(exc) else self.refusal)(refusal_text(exc)) from None
        if raw is not None:
            return raw
        raw = self._json()
        if raw is None:
            return None
        self._migrate(raw)
        return raw
