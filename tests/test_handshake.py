#!/usr/bin/env python3
"""Unit tests for the protocol-version handshake (no GIMP required).

check_server() constructs GimpConnection directly (not via get_gimp_connection),
so the conftest fake_conn_factory fixture does NOT intercept it. We patch the
class itself with a fake whose connect() is a no-op and whose send_command()
returns a canned get_gimp_info envelope. We also assert the server constant
matches the plugin's (the lockstep guarantee the feature rests on).
"""
import importlib.util
import io
import os
import sys
import types
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import gimp_mcp_server as s


class _FakeGimpConnection:
    """Stand-in for GimpConnection used only by check_server()."""

    def __init__(self, reply):
        self._reply = reply
        self.sent = []

    def __call__(self, host, port):   # check_server does GimpConnection(HOST, PORT)
        self.host, self.port = host, port
        return self

    def connect(self):
        pass

    def send_command(self, command_type, params=None):
        self.sent.append((command_type, params))
        return self._reply


def _patch_conn(monkeypatch, results):
    fake = _FakeGimpConnection({"status": "success", "results": results})
    monkeypatch.setattr(s, "GimpConnection", fake)
    return fake


def test_matching_version_no_warning(monkeypatch):
    fake = _patch_conn(monkeypatch, {
        "version": {"version_method": "3.2.0"},
        "protocol_version": s.PROTOCOL_VERSION,
    })
    out = s.check_server(ctx=None)
    assert fake.sent[0][0] == "get_gimp_info"
    assert out["connected"] is True
    assert out["protocol_version"] == s.PROTOCOL_VERSION
    assert "protocol_warning" not in out


def test_mismatched_version_warns_non_fatal(monkeypatch):
    _patch_conn(monkeypatch, {
        "version": {"version_method": "3.2.0"},
        "protocol_version": s.PROTOCOL_VERSION + 1,
    })
    out = s.check_server(ctx=None)
    assert out["connected"] is True            # still connected
    assert "protocol_warning" in out
    assert str(s.PROTOCOL_VERSION) in out["protocol_warning"]


def test_absent_version_warns_old_plugin(monkeypatch):
    _patch_conn(monkeypatch, {"version": {"version_method": "3.2.0"}})  # no protocol_version
    out = s.check_server(ctx=None)
    assert out["connected"] is True
    assert out["protocol_version"] is None
    assert "protocol_warning" in out           # None != PROTOCOL_VERSION


def test_check_server_writes_nothing_to_stdout(monkeypatch):
    """STDOUT is the JSON-RPC channel: check_server must not print to it."""
    _patch_conn(monkeypatch, {
        "version": {"version_method": "3.2.0"},
        "protocol_version": s.PROTOCOL_VERSION + 1,   # drift path also exercises the f-string
    })
    buf = io.StringIO()
    with redirect_stdout(buf):
        s.check_server(ctx=None)
    assert buf.getvalue() == ""


def test_constants_match_between_server_and_plugin():
    """Server and plugin MUST declare the same PROTOCOL_VERSION."""
    # Load the hyphen-named plugin file with gi stubs (mirrors test_restart_race).
    gi_stub = types.ModuleType("gi")
    gi_stub.require_version = lambda *a, **k: None
    repo = types.ModuleType("gi.repository")
    repo.Gimp = types.SimpleNamespace(
        PlugIn=type("PlugIn", (), {"__gtype__": None}), main=lambda *a, **k: None)
    repo.GLib = MagicMock()
    repo.GObject = MagicMock()
    gi_stub.repository = repo
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "gimp-mcp-plugin.py")
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.PROTOCOL_VERSION == s.PROTOCOL_VERSION
