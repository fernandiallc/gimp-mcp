#!/usr/bin/env python3
"""Observability tests: rotating file log handler, per-request id, plugin-traceback
capture, and stdout purity (stdout is the JSON-RPC stdio channel — must stay empty).

No live GIMP required. FakeSocket drives the REAL GimpConnection.send_command recv
loop so the req-id/traceback logic executes; FakeConn (conftest) is used only for the
tool-level stdout test since it bypasses send_command entirely.
"""
import json
import logging
import re
import sys
from logging.handlers import RotatingFileHandler

import gimp_mcp_server as srv


class FakeSocket:
    """Feeds a canned JSON reply to the real GimpConnection.send_command recv loop."""

    def __init__(self, reply):
        self._buf = (json.dumps(reply) + "\n").encode("utf-8")

    def sendall(self, data):
        pass

    def recv(self, n):
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk

    def close(self):
        pass

    def settimeout(self, t):
        pass


def _conn(reply):
    c = srv.GimpConnection()
    c.sock = FakeSocket(reply)   # pre-set -> connect() is skipped
    return c


def test_file_handler_attached_no_stdout_target():
    rfh = [h for h in srv.logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rfh) == 1
    assert rfh[0].maxBytes == 2 * 1024 * 1024
    assert rfh[0].backupCount == 3
    handlers = list(srv.logger.handlers) + list(logging.getLogger().handlers)
    assert all(getattr(h, "stream", None) is not sys.stdout for h in handlers)


def test_tool_invocation_zero_stdout(fake_conn_factory, capsys):
    fake_conn_factory({"status": "success", "results": {"v": 1}})
    capsys.readouterr()              # clear
    srv.call_api(None, "exec", ["a"])
    assert capsys.readouterr().out == ""   # stderr/logs allowed; stdout must be empty


def test_send_command_logs_8char_req_id(caplog):
    with caplog.at_level(logging.INFO, logger="GimpMCPServer"):
        out = _conn({"status": "success", "results": {"ok": 1}}).send_command(
            "check_server", {"args": []}
        )
    assert out["status"] == "success"
    assert re.search(r"\[[0-9a-f]{8}\]", caplog.text)


def test_error_traceback_written_to_log_file():
    marker = "BoomError: unique-marker-7f3a9c"
    tb = f"Traceback (most recent call last):\n  File X\n{marker}"
    before = srv.LOG_FILE.stat().st_size if srv.LOG_FILE.exists() else 0
    _conn({"status": "error", "error": "boom", "traceback": tb}).send_command(
        "call_api", {"args": []}
    )
    for h in srv.logger.handlers:
        h.flush()
    with open(srv.LOG_FILE, "r", encoding="utf-8") as f:
        f.seek(before)
        appended = f.read()
    assert marker in appended and "boom" in appended
