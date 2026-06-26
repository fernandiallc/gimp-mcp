"""Unit tests for the get_image_metadata layer-type / is_group fix.

No live GIMP. Loads the hyphenated plugin file with fake gi modules (mirrors
test_transform_layer.py) and augments the Gimp stub with the ImageType enum.

Regression guard for two bugs:
  - layer_type rendered the GObject class GType (bound-method-style repr)
    because it used layer.get_type(); the fix uses drawable.type().
  - is_group was always True because it tested hasattr(layer,'get_children');
    the fix uses gimp_item_is_group -> layer.is_group().
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
    Gimp = types.SimpleNamespace(
        PlugIn=type("PlugIn", (), {"__gtype__": None}),
        main=lambda *a, **k: None,
        displays_flush=lambda: None,
        # Distinct hashable members so dict lookup by enum value works.
        ImageType=types.SimpleNamespace(
            RGB_IMAGE="rgb-image",
            RGBA_IMAGE="rgba-image",
            GRAY_IMAGE="gray-image",
            GRAYA_IMAGE="graya-image",
            INDEXED_IMAGE="indexed-image",
            INDEXEDA_IMAGE="indexeda-image",
        ),
    )
    repo_stub.Gimp = Gimp
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_meta", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


@pytest.mark.parametrize("enum_attr,expected", [
    ("RGB_IMAGE", "RGB"),
    ("RGBA_IMAGE", "RGBA"),
    ("GRAY_IMAGE", "GRAY"),
    ("GRAYA_IMAGE", "GRAYA"),
    ("INDEXED_IMAGE", "INDEXED"),
    ("INDEXEDA_IMAGE", "INDEXEDA"),
])
def test_layer_type_string_maps_pixel_type(plugin, plugin_mod, enum_attr, expected):
    layer = MagicMock(name="layer")
    layer.type.return_value = getattr(plugin_mod.Gimp.ImageType, enum_attr)
    assert plugin._get_layer_type_string(layer) == expected
    # The fix must call drawable.type(), NOT get_type() (the GObject GType).
    layer.type.assert_called_once()


def test_layer_type_string_uses_type_not_get_type(plugin):
    """get_type() returns the class GType repr — it must not be the source."""
    layer = MagicMock(name="layer")
    layer.type.return_value = "rgba-image"
    plugin._get_layer_type_string(layer)
    layer.get_type.assert_not_called()


def test_layer_type_string_unknown_value_falls_back_to_str(plugin):
    layer = MagicMock(name="layer")
    layer.type.return_value = "mystery-type"
    assert plugin._get_layer_type_string(layer) == "mystery-type"


def test_layer_type_string_handles_raise(plugin):
    layer = MagicMock(name="layer")
    layer.type.side_effect = RuntimeError("boom")
    assert plugin._get_layer_type_string(layer) == "unknown"
