"""A Stop during a live mailbox pull ends it (R640).

The pull was airplane-gated only at its start: a pull that had already connected when the operator went offline went on sending
commands and fetching messages up to its limit. The IMAP and POP3 loops now read the switch again before every command and every
message; once it is engaged no further command is sent, the connection the pull opened is closed WITHOUT LOGOUT/QUIT (one more write
to the provider), and the messages fetched before the Stop are kept and marked ``stopped``. No real network: the imaplib/poplib
classes are replaced by recorders.
"""

from __future__ import annotations

import imaplib
import poplib

import pytest

from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.email import MailboxPull, fetch_imap, fetch_mailbox, fetch_pop3


@pytest.fixture(autouse=True)
def _net():
    clear_kill_switch()
    yield
    clear_kill_switch()


class _Imap:
    """Records every command; ``stop_on`` names the command (and, for ``fetch``, the message number) DURING which the Stop lands."""

    last: _Imap

    def __init__(self, host, port, msgs=5, stop_on=None):
        self.commands: list[str] = []
        self.msgs = msgs
        self.stop_on = stop_on
        self.shut = False
        type(self).last = self
        if stop_on == "connect":
            activate_kill_switch()

    def _cmd(self, name):
        self.commands.append(name)
        if self.stop_on == name:
            activate_kill_switch()

    def login(self, user, password):
        self._cmd("login")

    def select(self, folder):
        self._cmd("select")

    def search(self, charset, criteria):
        self._cmd("search")
        return ("OK", [b" ".join(str(i + 1).encode() for i in range(self.msgs))])

    def fetch(self, mid, parts):
        self._cmd(f"fetch {int(mid)}")
        return ("OK", [(b"%s (RFC822" % mid, b"message %s" % mid)])

    def logout(self):
        self.commands.append("logout")

    def shutdown(self):
        self.shut = True


class _Pop:
    last: _Pop

    def __init__(self, host, port, msgs=5, stop_on=None):
        self.commands: list[str] = []
        self.msgs = msgs
        self.stop_on = stop_on
        self.closed = False
        type(self).last = self
        if stop_on == "connect":
            activate_kill_switch()

    def _cmd(self, name):
        self.commands.append(name)
        if self.stop_on == name:
            activate_kill_switch()

    def user(self, u):
        self._cmd("user")

    def pass_(self, p):
        self._cmd("pass")

    def list(self):
        self._cmd("list")
        return (b"+OK", [b"%d 100" % (i + 1) for i in range(self.msgs)])

    def retr(self, i):
        self._cmd(f"retr {i}")
        return (b"+OK", [b"message %d" % i], 100)

    def quit(self):
        self.commands.append("quit")

    def close(self):
        self.closed = True


def _use(monkeypatch, cls, **kw):
    factory = lambda host, port, timeout=None: cls(host, port, **kw)  # noqa: E731
    if cls is _Imap:
        monkeypatch.setattr(imaplib, "IMAP4_SSL", factory)
    else:
        monkeypatch.setattr(poplib, "POP3_SSL", factory)


def test_imap_stop_during_a_message_keeps_what_came_before_and_sends_nothing_more(monkeypatch):
    _use(monkeypatch, _Imap, stop_on="fetch 2")
    raws = fetch_imap("h", "u", "p", limit=5)
    conn = _Imap.last
    assert list(raws) == [b"message 1", b"message 2"]
    assert raws.stopped is True
    assert conn.commands == ["login", "select", "search", "fetch 1", "fetch 2"], (
        "a command was sent after the Stop"
    )
    assert conn.shut is True and "logout" not in conn.commands


@pytest.mark.parametrize(
    ("stop_on", "sent"),
    [
        ("connect", []),
        ("login", ["login"]),
        ("select", ["login", "select"]),
        ("search", ["login", "select", "search"]),
    ],
)
def test_imap_stop_before_each_command(monkeypatch, stop_on, sent):
    _use(monkeypatch, _Imap, stop_on=stop_on)
    raws = fetch_imap("h", "u", "p")
    assert list(raws) == [] and raws.stopped is True
    assert _Imap.last.commands == sent
    assert _Imap.last.shut is True


def test_pop_stop_during_a_message_keeps_what_came_before_and_sends_nothing_more(monkeypatch):
    _use(monkeypatch, _Pop, stop_on="retr 3")
    raws = fetch_pop3("h", "u", "p", limit=4)  # the newest four of five: 2..5
    conn = _Pop.last
    assert list(raws) == [b"message 2", b"message 3"]
    assert raws.stopped is True
    assert conn.commands == ["user", "pass", "list", "retr 2", "retr 3"]
    assert conn.closed is True and "quit" not in conn.commands


@pytest.mark.parametrize(
    ("stop_on", "sent"),
    [
        ("connect", []),
        ("user", ["user"]),
        ("pass", ["user", "pass"]),
        ("list", ["user", "pass", "list"]),
    ],
)
def test_pop_stop_before_each_command(monkeypatch, stop_on, sent):
    _use(monkeypatch, _Pop, stop_on=stop_on)
    raws = fetch_pop3("h", "u", "p")
    assert list(raws) == [] and raws.stopped is True
    assert _Pop.last.commands == sent
    assert _Pop.last.closed is True


@pytest.mark.parametrize("cls", [_Imap, _Pop])
def test_a_pull_with_no_stop_is_whole_and_logs_out(monkeypatch, cls):
    _use(monkeypatch, cls)
    raws = fetch_mailbox("imap" if cls is _Imap else "pop3", "h", "u", "p", limit=3)
    assert isinstance(raws, MailboxPull) and raws.stopped is False and len(raws) == 3
    assert cls.last.commands[-1] == ("logout" if cls is _Imap else "quit")


def test_an_error_while_the_switch_is_engaged_ends_the_pull_as_the_stop(monkeypatch):
    """A failure that surfaces after the Stop closes the connection without LOGOUT too, and the pull ends as the Stop it follows: a
    stopped (here empty) pull, never an error that would throw away what came before it."""

    class _Failing(_Imap):
        def select(self, folder):
            activate_kill_switch()
            raise OSError("connection reset")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: _Failing(host, port))
    raws = fetch_imap("h", "u", "p")
    assert list(raws) == [] and raws.stopped is True
    assert _Failing.last.shut is True and "logout" not in _Failing.last.commands


@pytest.mark.parametrize("cls", [_Imap, _Pop])
def test_an_error_after_the_stop_keeps_what_was_fetched(monkeypatch, cls):
    """Security read B: an exception after the Stop used to discard the messages already fetched."""
    if cls is _Imap:

        class _Late(_Imap):
            def fetch(self, mid, parts):
                if int(mid) == 2:
                    activate_kill_switch()
                    raise OSError("connection reset")
                return super().fetch(mid, parts)

        monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: _Late(host, port))
        raws = fetch_imap("h", "u", "p", limit=5)
        assert _Late.last.shut is True and "logout" not in _Late.last.commands
    else:

        class _LatePop(_Pop):
            def retr(self, i):
                if i == 2:
                    activate_kill_switch()
                    raise OSError("connection reset")
                return super().retr(i)

        monkeypatch.setattr(poplib, "POP3_SSL", lambda host, port, timeout=None: _LatePop(host, port))
        raws = fetch_pop3("h", "u", "p", limit=5)
        assert _LatePop.last.closed is True and "quit" not in _LatePop.last.commands
    assert list(raws) == [b"message 1"] and raws.stopped is True


@pytest.mark.parametrize("cls", [_Imap, _Pop])
def test_an_error_while_online_is_still_an_error_and_logs_out(monkeypatch, cls):
    if cls is _Imap:

        class _Broken(_Imap):
            def select(self, folder):
                raise OSError("connection reset")

        monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: _Broken(host, port))
        with pytest.raises(OSError):
            fetch_imap("h", "u", "p")
        assert _Broken.last.commands[-1] == "logout"
    else:

        class _BrokenPop(_Pop):
            def list(self):
                raise OSError("connection reset")

        monkeypatch.setattr(poplib, "POP3_SSL", lambda host, port, timeout=None: _BrokenPop(host, port))
        with pytest.raises(OSError):
            fetch_pop3("h", "u", "p")
        assert _BrokenPop.last.commands[-1] == "quit"


@pytest.mark.parametrize("cls", [_Imap, _Pop])
def test_a_stopped_pull_never_logs_out_even_if_the_switch_is_cleared_again(monkeypatch, cls):
    """The finally reads the pull's own ``stopped`` first: a switch turned off again before the cleanup must not bring LOGOUT/QUIT back."""
    import src.ingest.email as email_mod

    answers = iter(
        [False, False, False, False, True]
    )  # clear for the setup commands and message 1, engaged before message 2
    monkeypatch.setattr(email_mod, "_stop_requested", lambda: next(answers, False))
    _use(monkeypatch, cls)
    raws = (
        fetch_imap("h", "u", "p", limit=3) if cls is _Imap else fetch_pop3("h", "u", "p", limit=3)
    )
    assert raws.stopped is True and len(raws) == 1
    assert cls.last.commands[-1] not in ("logout", "quit")


class _CapImap:
    """A real class (so the module's stop-aware subclass wraps it) whose constructor and login ask for CAPABILITY themselves, as imaplib
    does when the greeting or the LOGIN reply carries none."""

    last: _CapImap
    stop_on: str | None = None

    def __init__(self, host, port, timeout=None):
        self.commands: list[str] = []
        self.shut = False
        _CapImap.last = self  # on this class: the module wraps it in a subclass of its own
        if self.stop_on == "connect":
            activate_kill_switch()
        self._get_capabilities()

    def _get_capabilities(self):
        self.commands.append("capability")

    def login(self, user, password):
        self.commands.append("login")
        if self.stop_on == "login":
            activate_kill_switch()
        self._get_capabilities()

    def logout(self):
        self.commands.append("logout")

    def shutdown(self):
        self.shut = True


@pytest.mark.parametrize(("use_ssl", "attr"), [(True, "IMAP4_SSL"), (False, "IMAP4")])
@pytest.mark.parametrize(("stop_on", "sent"), [("connect", []), ("login", ["capability", "login"])])
def test_imaplibs_own_capability_command_is_held_to_the_switch(
    monkeypatch, stop_on, sent, use_ssl, attr
):
    """Security read B: a Stop during LOGIN let imaplib send CAPABILITY from inside ``login``. It is now refused like any command, on
    the SSL class and the plain one alike."""
    monkeypatch.setattr(_CapImap, "stop_on", stop_on)
    monkeypatch.setattr(imaplib, attr, _CapImap)
    raws = fetch_imap("h", "u", "p", use_ssl=use_ssl)
    assert list(raws) == [] and raws.stopped is True
    assert _CapImap.last.commands == sent
    assert "logout" not in _CapImap.last.commands


def test_imaplibs_capability_command_goes_out_while_online(monkeypatch):
    monkeypatch.setattr(_CapImap, "stop_on", None)

    class _Full(_CapImap):
        def select(self, folder):
            self.commands.append("select")

        def search(self, charset, criteria):
            return ("OK", [b""])

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _Full)
    raws = fetch_imap("h", "u", "p")
    assert raws.stopped is False
    assert _CapImap.last.commands == ["capability", "login", "capability", "select", "logout"]


def test_an_injected_connection_is_its_callers_and_is_left_open():
    conn = _Imap("h", 993, stop_on="fetch 1")
    raws = fetch_imap("h", "u", "p", conn=conn)
    assert list(raws) == [b"message 1"] and raws.stopped is True
    assert conn.commands == ["select", "search", "fetch 1"]
    assert conn.shut is False and "logout" not in conn.commands


def test_without_the_per_message_check_the_pull_runs_on(monkeypatch):
    """Remove the guard, a test fails: with the switch read answering "clear" after the start, the pull fetches every message."""
    import src.ingest.email as email_mod

    monkeypatch.setattr(email_mod, "_stop_requested", lambda: False)
    _use(monkeypatch, _Imap, stop_on="fetch 2")
    raws = fetch_imap("h", "u", "p", limit=5)
    assert len(raws) == 5 and raws.stopped is False


def test_a_refused_capability_stays_a_stop_even_if_the_switch_is_cleared_again(monkeypatch):
    """Security reads A and B: the refusal raised inside imaplib counts by its type, so a switch turned off again before the handler
    cannot let it out of the module, nor bring LOGOUT back."""
    import src.ingest.email as email_mod

    monkeypatch.setattr(_CapImap, "stop_on", None)
    answers = iter(
        [False, False, True]
    )  # clear at the constructor's CAPABILITY and before LOGIN, engaged at login's CAPABILITY
    monkeypatch.setattr(email_mod, "_stop_requested", lambda: next(answers, False))
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _CapImap)
    raws = fetch_imap("h", "u", "p")
    assert raws.stopped is True and list(raws) == []
    assert _CapImap.last.commands == ["capability", "login"] and _CapImap.last.shut is True
