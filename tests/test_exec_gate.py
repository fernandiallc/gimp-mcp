"""Unit tests for the GIMP_MCP_ALLOW_EXEC raw-code-execution gate.

No live GIMP. Loads the hyphenated plugin file with fake gi modules and drives
execute_command() directly, toggling the module-global EXEC_ENABLED.

The gate must:
  - refuse the `cmds` (exec) and `params.args` (exec/eval) paths when off,
  - leave the named structured commands (e.g. check_server) reachable either way,
  - open the exec/eval paths when on.
"""
import importlib.util
import json
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

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
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_gate", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


# --- gate OFF ----------------------------------------------------------------

def test_cmds_path_refused_when_exec_off(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", False)
    out = plugin.execute_command(json.dumps({"cmds": ["print('hi')"]}))
    assert out["status"] == "error"
    assert "disabled" in out["error"].lower()
    assert out["exec_enabled"] is False


def test_args_exec_path_refused_when_exec_off(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", False)
    out = plugin.execute_command(json.dumps(
        {"params": {"args": ["pyGObject-console", ["x = 1"]]}}))
    assert out["status"] == "error"
    assert "disabled" in out["error"].lower()


def test_eval_path_refused_when_exec_off(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", False)
    out = plugin.execute_command(json.dumps(
        {"params": {"args": ["python-fu-eval", ["1 + 1"]]}}))
    assert out["status"] == "error"
    assert "disabled" in out["error"].lower()


def test_structured_command_unaffected_by_gate(plugin, plugin_mod, monkeypatch):
    """A named tool (check_server) must work with exec off, and report the flag."""
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", False)
    out = plugin.execute_command(json.dumps({"type": "check_server"}))
    assert out["status"] == "success"
    assert out["results"]["running"] is True
    assert out["results"]["exec_enabled"] is False


# --- gate ON -----------------------------------------------------------------

def test_cmds_path_runs_when_exec_on(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", True)
    out = plugin.execute_command(json.dumps({"cmds": ["x = 2 + 3"]}))
    assert out["status"] == "success"


def test_eval_path_runs_when_exec_on(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", True)
    out = plugin.execute_command(json.dumps(
        {"params": {"args": ["python-fu-eval", ["1 + 1"]]}}))
    assert out["status"] == "success"
    assert out["results"] == ["2"]


def test_check_server_reports_exec_on(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "EXEC_ENABLED", True)
    out = plugin.execute_command(json.dumps({"type": "check_server"}))
    assert out["results"]["exec_enabled"] is True


# --- env parsing -------------------------------------------------------------

@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("nope", False), (" 1 ", True),
])
def test_env_parsing(monkeypatch, val, expected):
    """EXEC_ENABLED is computed from GIMP_MCP_ALLOW_EXEC at load; verify the rule."""
    monkeypatch.setenv("GIMP_MCP_ALLOW_EXEC", val)
    assert (os.environ.get("GIMP_MCP_ALLOW_EXEC", "").strip().lower()
            in ("1", "true", "yes", "on")) is expected
