"""Unit tests for the adjust_levels / bucket_fill / layer_from_visible batch.

Server tools are exercised via the recording FakeConn fixture; plugin handlers
are loaded with fake gi modules (mirrors test_transform_layer.py) and a Gimp
stub augmented with the PDB / context / fill helpers each handler touches.
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

import gimp_mcp_server as s


# --- Server tool tests -------------------------------------------------------

def test_adjust_levels_sends_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.adjust_levels(ctx=None, low_input=20, high_input=240, gamma=1.2, channel="red")
    name, params = fake.sent[0]
    assert name == "adjust_levels"
    assert params["low_input"] == 20
    assert params["high_input"] == 240
    assert params["gamma"] == 1.2
    assert params["channel"] == "red"
    assert params["image_index"] == 0


def test_adjust_levels_raises_on_error(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "bad channel"})
    with pytest.raises(Exception, match="adjust_levels failed.*bad channel"):
        s.adjust_levels(ctx=None, channel="bogus")


def test_bucket_fill_sends_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success", "x": 10, "y": 20}})
    s.bucket_fill(ctx=None, x=10, y=20, color="#ff0000", threshold=30)
    name, params = fake.sent[0]
    assert name == "bucket_fill"
    assert params["x"] == 10 and params["y"] == 20
    assert params["color"] == "#ff0000"
    assert params["threshold"] == 30


def test_layer_from_visible_sends_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"layer_name": "Visible", "layer_id": 7}})
    out = s.layer_from_visible(ctx=None, name="Stamp")
    name, params = fake.sent[0]
    assert name == "layer_from_visible"
    assert params["name"] == "Stamp"
    assert out == {"layer_name": "Visible", "layer_id": 7}


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
        get_pdb=MagicMock(name="get_pdb"),
        HistogramChannel=types.SimpleNamespace(
            VALUE="value", RED="red", GREEN="green", BLUE="blue", ALPHA="alpha"),
        FillType=types.SimpleNamespace(FOREGROUND="FG"),
        context_push=MagicMock(name="context_push"),
        context_pop=MagicMock(name="context_pop"),
        context_set_sample_threshold_int=MagicMock(name="thr_int"),
        context_set_opacity=MagicMock(name="set_opacity"),
        context_set_foreground=MagicMock(name="set_fg"),
        Drawable=types.SimpleNamespace(edit_bucket_fill=MagicMock(name="edit_bucket_fill")),
        Layer=types.SimpleNamespace(new_from_visible=MagicMock(name="new_from_visible")),
    )
    repo_stub.Gimp = Gimp
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    repo_stub.Gegl = types.SimpleNamespace(Color=types.SimpleNamespace(new=MagicMock(name="color_new")))
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_batch", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load_plugin_module()


@pytest.fixture
def plugin(plugin_mod):
    return plugin_mod.MCPPlugin()


def _stub_image_drawable(plugin, monkeypatch, drawable, image=None):
    image = image or MagicMock(name="image")
    monkeypatch.setattr(plugin, "_get_image", lambda idx: image)
    monkeypatch.setattr(plugin, "_resolve_layer", lambda img, name, idx: drawable)
    return image


# adjust_levels

def test_adjust_levels_unknown_channel_fails_loud(plugin):
    out = plugin._adjust_levels({"channel": "bogus"})
    assert out["status"] == "error"
    assert "channel" in out["error"].lower()


def test_adjust_levels_bad_input_range_fails_loud(plugin):
    out = plugin._adjust_levels({"low_input": 200, "high_input": 100})
    assert out["status"] == "error"
    assert "high_input" in out["error"]


def test_adjust_levels_bad_gamma_fails_loud(plugin):
    out = plugin._adjust_levels({"gamma": 0})
    assert out["status"] == "error"
    assert "gamma" in out["error"]


def test_adjust_levels_happy_path_normalizes(plugin, plugin_mod, monkeypatch):
    Gimp = plugin_mod.Gimp
    drawable = MagicMock(name="drawable")
    image = _stub_image_drawable(plugin, monkeypatch, drawable)
    proc = MagicMock(name="proc")
    cfg = MagicMock(name="cfg")
    proc.create_config.return_value = cfg
    Gimp.get_pdb.return_value.lookup_procedure.return_value = proc

    out = plugin._adjust_levels({"low_input": 51, "high_input": 255, "gamma": 1.5})
    assert out["status"] == "success"
    proc.run.assert_called_once_with(cfg)
    # 51/255 == 0.2 normalized; undo group balanced.
    cfg.set_property.assert_any_call("low-input", pytest.approx(0.2))
    cfg.set_property.assert_any_call("high-input", 1.0)
    image.undo_group_start.assert_called_once()
    image.undo_group_end.assert_called_once()


def test_adjust_levels_missing_proc_fails_loud(plugin, plugin_mod, monkeypatch):
    Gimp = plugin_mod.Gimp
    drawable = MagicMock(name="drawable")
    _stub_image_drawable(plugin, monkeypatch, drawable)
    Gimp.get_pdb.return_value.lookup_procedure.return_value = None
    out = plugin._adjust_levels({})
    assert out["status"] == "error"
    assert "gimp-drawable-levels" in out["error"]


# bucket_fill

def test_bucket_fill_missing_coords_fails_loud(plugin):
    out = plugin._bucket_fill({"color": "red"})
    assert out["status"] == "error"
    assert "x and y" in out["error"]


def test_bucket_fill_out_of_bounds_fails_loud(plugin, monkeypatch):
    drawable = MagicMock(name="drawable")
    drawable.get_width.return_value = 100
    drawable.get_height.return_value = 80
    _stub_image_drawable(plugin, monkeypatch, drawable)
    out = plugin._bucket_fill({"x": 200, "y": 10})
    assert out["status"] == "error"
    assert "outside layer bounds" in out["error"]


def test_bucket_fill_happy_path(plugin, plugin_mod, monkeypatch):
    Gimp = plugin_mod.Gimp
    drawable = MagicMock(name="drawable")
    drawable.get_width.return_value = 100
    drawable.get_height.return_value = 80
    image = _stub_image_drawable(plugin, monkeypatch, drawable)
    Gimp.Drawable.edit_bucket_fill.reset_mock()

    out = plugin._bucket_fill({"x": 50, "y": 40, "color": "#00ff00", "threshold": 25})
    assert out["status"] == "success"
    Gimp.context_set_sample_threshold_int.assert_called_with(25)
    Gimp.Drawable.edit_bucket_fill.assert_called_once_with(drawable, Gimp.FillType.FOREGROUND, 50, 40)
    image.undo_group_end.assert_called_once()


# layer_from_visible

def test_layer_from_visible_happy_path(plugin, plugin_mod, monkeypatch):
    Gimp = plugin_mod.Gimp
    image = MagicMock(name="image")
    monkeypatch.setattr(plugin, "_get_image", lambda idx: image)
    new_layer = MagicMock(name="new_layer")
    new_layer.get_name.return_value = "Stamp"
    new_layer.get_id.return_value = 42
    Gimp.Layer.new_from_visible.reset_mock()
    Gimp.Layer.new_from_visible.return_value = new_layer

    out = plugin._layer_from_visible({"name": "Stamp"})
    assert out["status"] == "success"
    assert out["results"] == {"layer_name": "Stamp", "layer_id": 42}
    Gimp.Layer.new_from_visible.assert_called_once_with(image, image, "Stamp")
    image.insert_layer.assert_called_once_with(new_layer, None, 0)
