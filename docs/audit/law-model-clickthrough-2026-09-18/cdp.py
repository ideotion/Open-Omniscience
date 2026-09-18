"""A minimal Chrome DevTools Protocol client over the stdlib.

Written because this sandbox cannot reach PyPI (pypi.org answers 503 here), so the
repo's usual `playwright` driver is not installable -- but the pinned Chromium build
IS present under /opt/pw-browsers. This drives THAT browser over its real protocol:
the rendering, the JS, the fonts and the screenshots are Chromium's, not a simulation.

Only what the walk needs: the WebSocket handshake, text frames, a request/response
loop keyed by CDP message id, and event collection.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request


class WS:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        assert url.startswith("ws://")
        rest = url[len("ws://") :]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake closed")
            buf += chunk
        head, _, tail = buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError(f"handshake failed: {head[:200]!r}")
        self._buf = tail

    # -- framing -------------------------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send(self, text: str) -> None:
        payload = text.encode()
        head = bytearray([0x81])
        n = len(payload)
        if n < 126:
            head.append(0x80 | n)
        elif n < (1 << 16):
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(head) + masked)

    def recv(self) -> str:
        chunks: list[bytes] = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                (n,) = struct.unpack(">H", self._recv_exact(2))
            elif n == 127:
                (n,) = struct.unpack(">Q", self._recv_exact(8))
            data = self._recv_exact(n) if n else b""
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode == 0x8:
                raise RuntimeError("server closed the websocket")
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    """One page target."""

    def __init__(self, ws_url: str, timeout: float = 30.0) -> None:
        self.ws = WS(ws_url, timeout=timeout)
        self._id = 0
        self.events: list[dict] = []

    def call(self, method: str, **params: object) -> dict:
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def pump(self, until: str, timeout: float = 30.0) -> dict:
        self.ws.sock.settimeout(timeout)
        while True:
            msg = json.loads(self.ws.recv())
            if "method" in msg:
                self.events.append(msg)
                if msg["method"] == until:
                    return msg

    def evaluate(self, expr: str):
        res = self.call(
            "Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True
        )
        if res.get("exceptionDetails"):
            raise RuntimeError(f"evaluate: {res['exceptionDetails']}")
        return res["result"].get("value")


def open_page(debug_port: int, timeout: float = 30.0) -> CDP:
    with urllib.request.urlopen(
        urllib.request.Request(
            f"http://127.0.0.1:{debug_port}/json/new?about:blank", method="PUT"
        ),
        timeout=timeout,
    ) as fh:
        target = json.load(fh)
    return CDP(target["webSocketDebuggerUrl"], timeout=timeout)
