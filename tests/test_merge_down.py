"""Unit tests for merge_down (item: merge-down).

No live GIMP. Server tool is tested via the recording FakeConn fixture; plugin
handler is tested by loading the hyphenated plugin file with fake gi modules
(mirrors test_layer_masks.py) and augmenting the Gimp stub with the merge enums.
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

import gimp_mcp_server as s


# --- Server tool tests -------------------------------------------------------

def test_merge_down_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"layer_name": "merged", "layer_id": 7}})
    out = s.merge_down(ctx=None, layer_index=0, merge_type="expand", image_index=2)
    name, params = fake.sent[0]
    assert name == "merge_down"
    assert params == {"layer_name": None, "layer_index": 0,
                      "merge_type": "expand", "image_index": 2}
    assert out["layer_id"] == 7


def test_merge_down_default_merge_type(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"layer_name": "merged", "layer_id": 1}})
    s.merge_down(ctx=None)
    params = fake.sent[0][1]
    assert params["merge_type"] == "expand"
    assert params["image_index"] == 0
    assert params["layer_name"] is None
    assert params["layer_index"] is None


def test_merge_down_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "bottom-most layer"})
    with pytest.raises(Exception, match="bottom-most layer"):
        s.merge_down(ctx=None)


# --- Plugin handler tests ----------------------------------------------------

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
        MergeType=types.SimpleNamespace(
            EXPAND_AS_NECESSARY="EXPAND",
            CLIP_TO_IMAGE="CLIP_IMG",
            CLIP_TO_BOTTOM_LAYER="CLIP_BOT"),
    )
    repo_stub.Gimp = Gimp
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_merge", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


def _fake_layer(layer_id, name="L"):
    layer = MagicMock(name=f"layer{layer_id}")
    layer.get_id.return_value = layer_id
    layer.get_name.return_value = name
    return layer


def _stub_image(plugin, monkeypatch, siblings, resolved):
    """Make _get_image return a fake image whose get_layers() == siblings,
    and _resolve_layer return the chosen `resolved` layer."""
    image = MagicMock(name="image")
    image.get_layers.return_value = siblings
    monkeypatch.setattr(plugin, "_get_image", lambda idx: image)
    monkeypatch.setattr(plugin, "_resolve_layer", lambda img, name, idx: resolved)
    return image


def test_merge_type_mapping(plugin, plugin_mod):
    Gimp = plugin_mod.Gimp
    assert plugin._merge_type_from_string("expand") is Gimp.MergeType.EXPAND_AS_NECESSARY
    assert plugin._merge_type_from_string("CLIP_IMAGE") is Gimp.MergeType.CLIP_TO_IMAGE
    assert plugin._merge_type_from_string("clip_bottom") is Gimp.MergeType.CLIP_TO_BOTTOM_LAYER
    with pytest.raises(RuntimeError, match="Unknown merge_type"):
        plugin._merge_type_from_string("bogus")


def test_merge_down_calls_pdb_and_returns_shape(plugin, plugin_mod, monkeypatch):
    upper = _fake_layer(10, "top")
    lower = _fake_layer(20, "bottom")
    image = _stub_image(plugin, monkeypatch, [upper, lower], upper)
    merged = _fake_layer(99, "merged")
    image.merge_down.return_value = merged

    out = plugin._merge_down({"merge_type": "clip_image"})

    image.merge_down.assert_called_once_with(upper, plugin_mod.Gimp.MergeType.CLIP_TO_IMAGE)
    assert out["status"] == "success"
    assert out["results"] == {"layer_name": "merged", "layer_id": 99}


def test_merge_down_guards_bottom_layer(plugin, monkeypatch):
    upper = _fake_layer(10, "top")
    lower = _fake_layer(20, "bottom")
    # Resolve the bottom-most layer -> must be guarded.
    image = _stub_image(plugin, monkeypatch, [upper, lower], lower)

    out = plugin._merge_down({})

    assert out["status"] == "error"
    assert "bottom-most" in out["error"]
    image.merge_down.assert_not_called()


def test_merge_down_unknown_type_no_mutation(plugin, monkeypatch):
    upper = _fake_layer(10, "top")
    lower = _fake_layer(20, "bottom")
    image = _stub_image(plugin, monkeypatch, [upper, lower], upper)

    out = plugin._merge_down({"merge_type": "bogus"})

    assert out["status"] == "error"
    assert "Unknown merge_type" in out["error"]
    image.merge_down.assert_not_called()


def test_merge_down_undo_group_wraps_call(plugin, monkeypatch):
    upper = _fake_layer(10, "top")
    lower = _fake_layer(20, "bottom")
    image = _stub_image(plugin, monkeypatch, [upper, lower], upper)
    image.merge_down.return_value = _fake_layer(99, "merged")

    plugin._merge_down({})

    image.undo_group_start.assert_called_once()
    image.undo_group_end.assert_called_once()
