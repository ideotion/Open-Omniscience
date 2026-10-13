"""A pass's per-entity errors are the entity and the failure's CLASS: the words (a store failure carries a statement and its bound
values) go to the ``log_failure`` line, because ``PassResult.errors`` is copied into the wiki drain's ``last_drain``, which the status
serves and the release run stores."""

from __future__ import annotations

import logging

from src.versioned.adapters import WikiLaneAdapter
from tests.test_versioned_lane import _pass, lane  # noqa: F401 - the fixture

MARKER = "bound-value-7f3a"


def test_a_failed_fetch_names_the_class_in_the_result_and_the_words_in_the_log(lane, monkeypatch, caplog):  # noqa: F811
    def boom(self, external_id):
        raise RuntimeError(f"cannot fetch ({MARKER})")

    monkeypatch.setattr(WikiLaneAdapter, "fetch_version", boom)
    with caplog.at_level(logging.WARNING):
        result, _ = _pass()
    assert result.errors, "the fixture pass should have tried an entity"
    assert all(e.endswith(": RuntimeError") for e in result.errors), result.errors
    assert MARKER not in repr(result.as_dict())
    assert MARKER in caplog.text
