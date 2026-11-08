"""A streamed AI run that outlives its browser tab (2026-11-08, the background-mode thread, R600 follow-on).

WHY. Bulk summarize/translate, AI keyword extraction and the custom prompt runs answer as NDJSON streams, and the work was done
INSIDE the response generator: Starlette stops iterating a streaming response when the client leaves, so closing the tab (or the
browser, to save its memory on an instance left running) stopped the run after the article in flight. Every other long job in the
app (collection, downloads, backups, imports, the re-index) already ran on the server whatever the tab did.

WHAT THIS CHANGES. :func:`detached` runs the SAME generator on a thread of its own and hands its lines to the response through a
bounded queue. The tab still sees every line live while it is open. When it closes, the response ends and the run goes on to the
end; its row stays in the task manager (it registered there already) with real done/total, and its results are stored as before
(each runner writes with its own short session, never the request's).

WHAT KEEPS IT HONEST AND BOUNDED.
  * Stop: the task is registered ``cancellable`` and the producer checks :func:`src.monitoring.tasks.cancel_requested` after each
    line it receives, i.e. between articles, then closes the generator so its own ``finally`` (the task's finish, the batch hold's
    release) runs exactly as on a normal end. Closing the tab is no longer a stop, so the task manager's Stop is the way;
    the page's own Cancel sends the same Stop, finding the run by the ``X-OO-Task`` header its response carries.
  * Memory: the queue holds at most :data:`BUFFER` lines. A reader that lets it sit full for :data:`PUT_WAIT_S` is fed only while
    there is room until it reads again (the lines that did not fit are dropped and counted in the log), so the run never waits on
    a tab that has gone, and a slow tab still gets the end: the run's last line is fed by dropping the oldest unread one.
  * The end always arrives: the reader stops once the run is over and the queue is empty, whatever was dropped, and a Stop or a
    failure sends a last ``done`` line marked ``aborted``, so a tab still open never reads either as a finished run.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Generator, Iterator
from contextlib import suppress

from src.monitoring import tasks as _tasks
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: Lines held for the reader. One line is one article's event, well under a kilobyte.
BUFFER = 2000
#: How long the producer waits on a full queue before it decides nobody reads any more.
PUT_WAIT_S = 10.0
#: How often the reader wakes while waiting, so a reader whose response was dropped is collected promptly.
GET_WAIT_S = 1.0

def _closing_line(reason: str) -> str:
    """The last line of a run that did not end on its own: the same ``done`` shape the runners send, marked aborted, so a tab
    still open reads a Stop or a failure as one, never as a finished run."""
    return json.dumps({"event": "done", "aborted": True, "reason": reason}, separators=(",", ":")) + "\n"


def _is_done(line: str) -> bool:
    """Whether a line is a run's ``done`` event (every runner writes compact JSON, so the key reads exactly so)."""
    return '"event":"done"' in line


def detached(gen: Generator[str], token: int | None, *, name: str = "oo-detached-stream") -> Iterator[str]:
    """Run ``gen`` to its end on a thread of its own and return an iterator over its lines for the response.

    ``token`` is the run's task-manager token (registered ``cancellable=True``); None runs it with no Stop."""
    q: queue.Queue[str] = queue.Queue(maxsize=BUFFER)
    closed = threading.Event()  # the response has ended (finished, or the client left): nothing more is fed
    stalled = threading.Event()  # the reader let the queue sit full for PUT_WAIT_S: feed without waiting until it reads again
    finished = threading.Event()  # the run is over: the reader ends once the queue is empty
    dropped = [0]

    def _put(line: str) -> bool:
        """Feed one line; False when it was dropped."""
        if closed.is_set():
            dropped[0] += 1
            return False
        try:
            if stalled.is_set():
                q.put_nowait(line)
            else:
                q.put(line, timeout=PUT_WAIT_S)
            return True
        except queue.Full:
            # A slow reader, or one whose response was dropped without being closed yet. Either way the run must not wait on
            # it line after line: this line is dropped, and the next ones are fed only while there is room, until it reads.
            stalled.set()
            dropped[0] += 1
            return False

    def _put_last(line: str) -> None:
        """Feed the run's LAST line even into a full queue, by dropping the oldest unread one: a progress line can be lost, the
        end cannot, or a slow tab would read a stopped or failed run as a finished one."""
        if closed.is_set():
            return
        while True:
            try:
                q.put_nowait(line)
                return
            except queue.Full:
                with suppress(queue.Empty):
                    q.get_nowait()
                    dropped[0] += 1

    def _produce() -> None:
        last: str | None = None
        last_fed = True
        try:
            for line in gen:
                last, last_fed = line, _put(line)
                if _is_done(line):
                    continue  # the run's own end: a Stop that lands now changes nothing, so it never adds a second, aborted end
                if token is not None and _tasks.cancel_requested(token):
                    _LOG.info("%s: stopped from the task manager", name)
                    last = None
                    _put_last(_closing_line("stopped from the task manager"))
                    break
            else:
                if last is not None and not last_fed:
                    _put_last(last)  # the runner's own done line, dropped by a stalled reader: it still gets the end
        except Exception as exc:  # noqa: BLE001 - a failed run ends its stream, as it ended the response before
            log_failure(_LOG, f"{name}: the run failed", exc, level=logging.WARNING)
            _put_last(_closing_line("the run failed; the articles finished before it stay stored"))
        finally:
            with suppress(Exception):
                gen.close()  # the runner's own finally: the task's finish, the batch hold's release
            if dropped[0]:
                _LOG.info("%s: %d progress line(s) were not delivered to the tab; the results are stored", name, dropped[0])
            finished.set()

    threading.Thread(target=_produce, name=name, daemon=True).start()

    def _consume() -> Iterator[str]:
        try:
            while True:
                try:
                    line = q.get(timeout=GET_WAIT_S)
                except queue.Empty:
                    if finished.is_set() and q.empty():
                        return
                    continue
                stalled.clear()  # the reader is here: wait for room again
                yield line
        finally:
            closed.set()
            with suppress(queue.Empty):
                while True:
                    q.get_nowait()

    return _consume()
