#!/usr/bin/env python3
"""Unit tests for the restart_server accept-loop vs socket-rebind race fix.

No live GIMP required. The plugin module top-level does
`import gi; gi.require_version('Gimp','3.0'); from gi.repository import Gimp/...`,
which is unavailable in CI, and the filename has hyphens (not importable by name).
So we (a) inject fake `gi` modules into sys.modules and (b) load the file via
importlib.util.spec_from_file_location.

These tests prove the flag/rebind/loop-survival LOGIC only. True correctness
(accept loop survives rebind under load with a real GLib main loop and GIMP
marshaling) still needs a manual live-GIMP restart test — see PR notes.
"""
import importlib.util
import os
import socket
import sys
import threading
import time
import types
from unittest.mock import MagicMock

import pytest


PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gimp-mcp-plugin.py",
)


def _install_gi_stubs():
    """Inject fake gi / gi.repository so the plugin module imports without GIMP."""
    gi_stub = types.ModuleType("gi")
    gi_stub.require_version = lambda *a, **k: None

    repo_stub = types.ModuleType("gi.repository")
    # class MCPPlugin(Gimp.PlugIn) is evaluated at import time, so PlugIn must be
    # a real class, not a Mock instance. __gtype__ is read at module bottom by
    # Gimp.main(MCPPlugin.__gtype__, ...), so provide it on the base.
    Gimp = types.SimpleNamespace(
        PlugIn=type("PlugIn", (), {"__gtype__": None}),
        main=lambda *a, **k: None,
    )
    repo_stub.Gimp = Gimp
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()

    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    p = plugin_mod.MCPPlugin()
    p.host = "localhost"
    p.port = 9877
    return p


# --- Test A: _restart_server sets flag, no socket ops, correct shape -----------
def test_restart_server_sets_flag_only(plugin):
    plugin._rebind_requested = False
    old_sock = MagicMock(name="old")
    plugin.socket = old_sock

    r = plugin._restart_server()

    assert plugin._rebind_requested is True
    assert plugin.socket is old_sock          # not reassigned
    old_sock.close.assert_not_called()        # no socket ops from handler thread
    assert r == {
        "status": "success",
        "results": {"restarted": True, "host": "localhost", "port": 9877},
    }


def test_rebind_requested_initialized(plugin):
    assert plugin._rebind_requested is False


# --- Test B: _rebind_listen_socket closes old and binds new --------------------
def test_rebind_listen_socket(plugin, plugin_mod, monkeypatch):
    new_sock = MagicMock(name="new")
    monkeypatch.setattr(plugin_mod.socket, "socket", lambda *a, **k: new_sock)
    old_sock = MagicMock(name="old")
    plugin.socket = old_sock

    plugin._rebind_listen_socket()

    old_sock.close.assert_called_once()
    new_sock.setsockopt.assert_called_with(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    new_sock.settimeout.assert_called_with(1.0)
    new_sock.bind.assert_called_with(("localhost", 9877))
    new_sock.listen.assert_called_once()
    assert plugin.socket is new_sock


# --- Test C: accept loop honors the flag then survives -------------------------
def test_accept_loop_rebinds_and_survives(plugin, plugin_mod, monkeypatch):
    # accept() never returns a client; it always times out so the loop keeps
    # spinning deterministically without real I/O.
    fake1 = MagicMock(name="fake1")
    fake1.accept.side_effect = socket.timeout
    fake2 = MagicMock(name="fake2")
    fake2.accept.side_effect = socket.timeout

    # The initial create in _start_server_thread pulls fake1; the rebind (inside
    # _rebind_listen_socket) pulls fake2.
    sockets = iter([fake1, fake2])
    monkeypatch.setattr(plugin_mod.socket, "socket", lambda *a, **k: next(sockets))

    plugin.running = True
    plugin.socket = None
    plugin._rebind_requested = True

    t = threading.Thread(target=plugin._start_server_thread, daemon=True)
    t.start()

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if fake1.close.called and plugin.socket is fake2:
            break
        time.sleep(0.02)

    assert fake1.close.called, "rebind did not close the old listening socket"
    assert plugin.socket is fake2, "rebind did not swap in the new socket"
    assert plugin._rebind_requested is False

    plugin.running = False
    t.join(2.0)
    assert not t.is_alive(), "accept loop did not exit cleanly on running=False"


# --- Test D: OSError arm only breaks on shutdown ------------------------------
def test_oserror_continues_while_running_breaks_on_shutdown(plugin, plugin_mod, monkeypatch):
    fake = MagicMock(name="fake")
    # While running: one OSError must NOT kill the loop -> subsequent accepts run.
    # Block on timeout afterwards so we can observe call count > 1, then trigger
    # shutdown and raise OSError to confirm the break arm.
    fake.accept.side_effect = [OSError("transient")] + [socket.timeout] * 10000
    monkeypatch.setattr(plugin_mod.socket, "socket", lambda *a, **k: fake)

    plugin.running = True
    plugin.socket = None  # initial create pulls `fake`
    plugin._rebind_requested = False

    t = threading.Thread(target=plugin._start_server_thread, daemon=True)
    t.start()

    deadline = time.time() + 3.0
    while time.time() < deadline and fake.accept.call_count < 3:
        time.sleep(0.02)

    assert fake.accept.call_count > 1, "loop died on a transient OSError while running"
    assert t.is_alive(), "loop should still be running after a transient OSError"

    # Now intentional shutdown: running=False then an OSError should break.
    plugin.running = False
    fake.accept.side_effect = OSError("socket closed by shutdown")
    t.join(2.0)
    assert not t.is_alive(), "loop did not break on OSError after running=False"
