"""Unit tests for undo / redo (item: gui-only-not-supported).

GIMP 3.2's plug-in API has no call to *perform* an undo/redo step (verified live
on 3.2.4 -- neither Gimp.Image nor the PDB exposes one). The handlers therefore
return a fail-loud, actionable error rather than crashing on a non-existent
image.undo(). These tests pin that contract on both ends:
- server tool raises (status:error envelope -> Exception) so the agent's
  "tool failed -> self-correct" reflex fires;
- plugin handler returns the structured not-supported error with guidance, and
  never touches the image (no GIMP calls, so nothing to crash on).

No live GIMP. Server tool tested via the recording FakeConn fixture; plugin
handler tested by loading the hyphenated plugin file with fake gi modules
(mirrors test_merge_down.py).
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

import gimp_mcp_server as s


# --- Server tool tests -------------------------------------------------------

def test_undo_forwards_command(fake_conn_factory):
    # Even though it always errors in practice, the wiring must be correct so
    # the real plugin's error envelope reaches the agent.
    fake = fake_conn_factory({"status": "success", "results": {"ok": True}})
    s.undo(ctx=None, steps=3, image_index=2)
    name, params = fake.sent[0]
    assert name == "undo"
    assert params == {"steps": 3, "image_index": 2}


def test_redo_forwards_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"ok": True}})
    s.redo(ctx=None)
    name, params = fake.sent[0]
    assert name == "redo"
    assert params == {"steps": 1, "image_index": 0}


def test_undo_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error",
                       "error": "Programmatic undo is not supported"})
    with pytest.raises(Exception, match="not supported"):
        s.undo(ctx=None)


def test_redo_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error",
                       "error": "Programmatic redo is not supported"})
    with pytest.raises(Exception, match="not supported"):
        s.redo(ctx=None)


# --- Plugin handler tests ----------------------------------------------------

PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gimp-mcp-plugin.py",
)


def _install_gi_stubs():
    gi_stub = types.ModuleType("gi")
    gi_stub.require_version = lambda *a, **k: None
    repo_stub = types.ModuleType("gi.repository")
    repo_stub.Gimp = types.SimpleNamespace(
        PlugIn=type("PlugIn", (), {"__gtype__": None}),
        main=lambda *a, **k: None,
        displays_flush=lambda: None,
    )
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_undo", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


def test_undo_handler_returns_not_supported(plugin, monkeypatch):
    # Must not call _get_image at all -- there is nothing to act on.
    monkeypatch.setattr(plugin, "_get_image",
                        lambda *a, **k: pytest.fail("_undo must not touch the image"))
    out = plugin._undo({"steps": 5, "image_index": 1})
    assert out["status"] == "error"
    assert "undo" in out["error"]
    assert "not supported" in out["error"].lower()
    assert "Ctrl+Z" in out["error"]
    assert "save_xcf" in out["error"]
    # No misleading traceback -- it's an honest limitation, not a crash.
    assert "traceback" not in out


def test_redo_handler_returns_not_supported(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_get_image",
                        lambda *a, **k: pytest.fail("_redo must not touch the image"))
    out = plugin._redo({})
    assert out["status"] == "error"
    assert "redo" in out["error"]
    assert "not supported" in out["error"].lower()
    assert "Ctrl+Y" in out["error"]
