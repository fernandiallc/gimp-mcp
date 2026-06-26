"""Unit tests for _parse_color — the rgb()/rgba() integer-scale fix.

Gegl.Color.new("rgb(40,80,160)") mis-parses 0-255 integers as 0-1 floats
(clamping to white). _parse_color detects the integer scale and divides by 255;
named colors / hex / float rgb() pass straight through to Gegl.Color.new.
"""
import importlib.util
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
    )
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    # Color.new returns a fresh mock per call so set_rgba assertions are isolated.
    repo_stub.Gegl = types.SimpleNamespace(
        Color=types.SimpleNamespace(new=MagicMock(side_effect=lambda *a: MagicMock(name="color"))))
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub
    return repo_stub.Gegl


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_color", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


@pytest.fixture
def gegl(plugin_mod):
    # Gegl is imported locally inside handlers, not at plugin module scope;
    # reach the stub through the installed gi.repository module.
    return sys.modules["gi.repository"].Gegl


def test_integer_rgb_is_normalized(plugin, gegl):
    gegl.Color.new.reset_mock()
    c = plugin._parse_color("rgb(40,80,160)")
    # built from a base color + set_rgba with /255 values
    gegl.Color.new.assert_called_once_with("black")
    c.set_rgba.assert_called_once()
    r, g, b, a = c.set_rgba.call_args[0]
    assert r == pytest.approx(40 / 255)
    assert g == pytest.approx(80 / 255)
    assert b == pytest.approx(160 / 255)
    assert a == 1.0


def test_integer_rgba_keeps_fractional_alpha(plugin, gegl):
    gegl.Color.new.reset_mock()
    c = plugin._parse_color("rgba(255, 0, 0, 0.5)")
    r, g, b, a = c.set_rgba.call_args[0]
    assert r == pytest.approx(1.0)
    assert a == pytest.approx(0.5)   # 0-1 alpha must NOT be divided


def test_integer_rgba_normalizes_255_alpha(plugin, gegl):
    gegl.Color.new.reset_mock()
    c = plugin._parse_color("rgba(255,255,255,255)")
    _, _, _, a = c.set_rgba.call_args[0]
    assert a == pytest.approx(1.0)


def test_float_rgb_passes_through(plugin, gegl):
    gegl.Color.new.reset_mock()
    plugin._parse_color("rgb(0.5,0.5,0.5)")
    # all components <= 1 -> native parse, no set_rgba rebuild
    gegl.Color.new.assert_called_once_with("rgb(0.5,0.5,0.5)")


def test_named_color_passes_through(plugin, gegl):
    gegl.Color.new.reset_mock()
    plugin._parse_color("red")
    gegl.Color.new.assert_called_once_with("red")


def test_hex_passes_through(plugin, gegl):
    gegl.Color.new.reset_mock()
    plugin._parse_color("#2850a0")
    gegl.Color.new.assert_called_once_with("#2850a0")


def test_whitespace_tolerated(plugin, gegl):
    gegl.Color.new.reset_mock()
    c = plugin._parse_color("  rgb( 40 , 80 , 160 )  ")
    assert c.set_rgba.called


def test_none_returns_none(plugin):
    assert plugin._parse_color(None) is None
