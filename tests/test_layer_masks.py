"""Unit tests for add_layer_mask / apply_layer_mask (item: layer-masks).

No live GIMP. Server tools are tested via the recording FakeConn fixture; plugin
handlers are tested by loading the hyphenated plugin file with fake gi modules
(mirrors test_restart_race.py) and augmenting the Gimp stub with the mask enums.
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

import gimp_mcp_server as s


# --- Server tool tests -------------------------------------------------------

def test_add_layer_mask_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"status": "success",
                                          "layer_name": "bg", "mask_type": "black"}})
    out = s.add_layer_mask(ctx=None, image_index=2, layer_name="bg", mask_type="black")
    name, params = fake.sent[0]
    assert name == "add_layer_mask"
    assert params == {"image_index": 2, "layer_name": "bg", "mask_type": "black"}
    assert out["mask_type"] == "black"


def test_apply_layer_mask_sends_correct_command_default_apply(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"status": "success",
                                          "layer_name": "bg", "mode": "apply"}})
    s.apply_layer_mask(ctx=None, image_index=1, layer_name="bg")
    name, params = fake.sent[0]
    assert name == "apply_layer_mask"
    assert params == {"image_index": 1, "layer_name": "bg", "mode": "apply"}


def test_apply_layer_mask_forwards_discard(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"status": "success",
                                          "layer_name": "bg", "mode": "discard"}})
    s.apply_layer_mask(ctx=None, mode="discard")
    assert fake.sent[0][1]["mode"] == "discard"


def test_add_layer_mask_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "already has a mask"})
    with pytest.raises(Exception, match="already has a mask"):
        s.add_layer_mask(ctx=None)


def test_apply_layer_mask_raises_when_no_mask(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "has no mask"})
    with pytest.raises(Exception, match="has no mask"):
        s.apply_layer_mask(ctx=None)


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
        AddMaskType=types.SimpleNamespace(
            WHITE="WHITE", BLACK="BLACK", ALPHA="ALPHA", SELECTION="SELECTION"),
        MaskApplyMode=types.SimpleNamespace(APPLY="APPLY", DISCARD="DISCARD"),
    )
    repo_stub.Gimp = Gimp
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_masks", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


def _stub_image_layer(plugin, monkeypatch, layer):
    """Make _get_image/_resolve_layer return a fake image and the given layer."""
    image = MagicMock(name="image")
    monkeypatch.setattr(plugin, "_get_image", lambda idx: image)
    monkeypatch.setattr(plugin, "_resolve_layer", lambda img, name, idx: layer)
    return image


def test_add_mask_type_mapping(plugin, plugin_mod):
    Gimp = plugin_mod.Gimp
    assert plugin._add_mask_type_from_string("white") is Gimp.AddMaskType.WHITE
    assert plugin._add_mask_type_from_string("BLACK") is Gimp.AddMaskType.BLACK
    assert plugin._add_mask_type_from_string("alpha") is Gimp.AddMaskType.ALPHA
    assert plugin._add_mask_type_from_string("selection") is Gimp.AddMaskType.SELECTION
    with pytest.raises(RuntimeError, match="Unknown mask_type"):
        plugin._add_mask_type_from_string("bogus")


def test_add_layer_mask_calls_create_then_add(plugin, plugin_mod, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = None
    layer.get_name.return_value = "L1"
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._add_layer_mask({"mask_type": "black"})

    layer.create_mask.assert_called_once_with(plugin_mod.Gimp.AddMaskType.BLACK)
    layer.add_mask.assert_called_once_with(layer.create_mask.return_value)
    assert out["status"] == "success"
    assert out["results"]["mask_type"] == "black"
    assert out["results"]["layer_name"] == "L1"


def test_add_layer_mask_guards_existing_mask(plugin, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = MagicMock(name="existing_mask")  # truthy
    layer.get_name.return_value = "L1"
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._add_layer_mask({"mask_type": "white"})

    assert out["status"] == "error"
    assert "already has a mask" in out["error"]
    layer.create_mask.assert_not_called()


def test_add_layer_mask_unknown_type_no_gimp_mutation(plugin, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = None
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._add_layer_mask({"mask_type": "bogus"})

    assert out["status"] == "error"
    assert "Unknown mask_type" in out["error"]
    layer.create_mask.assert_not_called()


def test_apply_layer_mask_apply_default(plugin, plugin_mod, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = MagicMock(name="mask")  # truthy
    layer.get_name.return_value = "L1"
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._apply_layer_mask({})

    layer.remove_mask.assert_called_once_with(plugin_mod.Gimp.MaskApplyMode.APPLY)
    assert out["status"] == "success"
    assert out["results"]["mode"] == "apply"


def test_apply_layer_mask_discard(plugin, plugin_mod, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = MagicMock(name="mask")
    layer.get_name.return_value = "L1"
    _stub_image_layer(plugin, monkeypatch, layer)

    plugin._apply_layer_mask({"mode": "discard"})

    layer.remove_mask.assert_called_once_with(plugin_mod.Gimp.MaskApplyMode.DISCARD)


def test_apply_layer_mask_guards_no_mask(plugin, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = None
    layer.get_name.return_value = "L1"
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._apply_layer_mask({"mode": "apply"})

    assert out["status"] == "error"
    assert "has no mask" in out["error"]
    layer.remove_mask.assert_not_called()


def test_apply_layer_mask_unknown_mode(plugin, monkeypatch):
    layer = MagicMock(name="layer")
    layer.get_mask.return_value = MagicMock(name="mask")
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._apply_layer_mask({"mode": "bogus"})

    assert out["status"] == "error"
    assert "Unknown mode" in out["error"]
    layer.remove_mask.assert_not_called()
