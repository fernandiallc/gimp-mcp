"""Unit tests for transform_layer (per-layer rotate/scale/flip/offset).

No live GIMP. The server tool is tested via the recording FakeConn fixture; the
plugin handler is tested by loading the hyphenated plugin file with fake gi
modules (mirrors test_layer_masks.py) and augmenting the Gimp stub with the
transform enums + context functions.
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

import gimp_mcp_server as s


# --- Server tool tests -------------------------------------------------------

_OK = {"status": "success",
       "results": {"status": "success", "operation": "rotate", "layer": "L1",
                   "offsets": [0, 0], "width": 50, "height": 100}}


def test_transform_layer_rotate_request(fake_conn_factory):
    fake = fake_conn_factory(_OK)
    out = s.transform_layer(ctx=None, operation="rotate", angle=90, layer_name="L1")
    name, params = fake.sent[0]
    assert name == "transform_layer"
    # All wire keys present (None where unset) so the plugin sees a stable shape.
    assert params == {
        "operation": "rotate", "layer_name": "L1", "layer_index": None,
        "angle": 90, "scale_width": None, "scale_height": None,
        "flip_axis": None, "offset_x": None, "offset_y": None,
        "interpolation": "cubic", "image_index": 0,
    }
    # Tool unwraps the inner results envelope.
    assert out == _OK["results"]


def test_transform_layer_offset_request_preserves_zero(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.transform_layer(ctx=None, operation="offset", offset_x=0, offset_y=20)
    params = fake.sent[0][1]
    assert params["operation"] == "offset"
    assert params["offset_x"] == 0   # zero must not be dropped
    assert params["offset_y"] == 20


def test_transform_layer_scale_request(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.transform_layer(ctx=None, operation="scale", scale_width=200, scale_height=120)
    params = fake.sent[0][1]
    assert params["scale_width"] == 200
    assert params["scale_height"] == 120


def test_transform_layer_flip_request(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.transform_layer(ctx=None, operation="flip", flip_axis="vertical")
    params = fake.sent[0][1]
    assert params["operation"] == "flip"
    assert params["flip_axis"] == "vertical"


def test_transform_layer_error_propagates(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "boom"})
    with pytest.raises(Exception, match="transform_layer failed.*boom"):
        s.transform_layer(ctx=None, operation="rotate", angle=45)


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
        context_push=MagicMock(name="context_push"),
        context_pop=MagicMock(name="context_pop"),
        context_set_transform_resize=MagicMock(name="ctx_transform_resize"),
        context_set_interpolation=MagicMock(name="ctx_interpolation"),
        TransformResize=types.SimpleNamespace(ADJUST="ADJUST", CLIP="CLIP"),
        RotationType=types.SimpleNamespace(
            DEGREES90="D90", DEGREES180="D180", DEGREES270="D270"),
        OrientationType=types.SimpleNamespace(
            HORIZONTAL="H", VERTICAL="V"),
        InterpolationType=types.SimpleNamespace(
            CUBIC="CUBIC", LINEAR="LINEAR", NONE="NONE"),
    )
    repo_stub.Gimp = Gimp
    repo_stub.GLib = MagicMock()
    repo_stub.GObject = MagicMock()
    gi_stub.repository = repo_stub
    sys.modules["gi"] = gi_stub
    sys.modules["gi.repository"] = repo_stub


def _load_plugin_module():
    _install_gi_stubs()
    spec = importlib.util.spec_from_file_location("gimp_mcp_plugin_mod_xform", PLUGIN_PATH)
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
    image = MagicMock(name="image")
    monkeypatch.setattr(plugin, "_get_image", lambda idx: image)
    monkeypatch.setattr(plugin, "_resolve_layer", lambda img, name, idx: layer)
    return image


def _make_layer(name="L1", offsets=(0, 0), width=50, height=100):
    layer = MagicMock(name="layer")
    layer.get_name.return_value = name
    layer.get_offsets.return_value = offsets
    layer.get_width.return_value = width
    layer.get_height.return_value = height
    # transform_* return the (possibly new) item; return the same mock so geometry
    # getters keep working and the reassignment path is exercised.
    layer.transform_rotate_simple.return_value = layer
    layer.transform_rotate.return_value = layer
    layer.transform_scale.return_value = layer
    layer.transform_flip_simple.return_value = layer
    return layer


def test_rotate_90_uses_simple_path(plugin, plugin_mod, monkeypatch):
    Gimp = plugin_mod.Gimp
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)

    out = plugin._transform_layer({"operation": "rotate", "angle": 90})

    layer.transform_rotate_simple.assert_called_once_with(Gimp.RotationType.DEGREES90, True, 0, 0)
    layer.transform_rotate.assert_not_called()
    assert out["status"] == "success"
    assert out["results"]["operation"] == "rotate"


def test_rotate_arbitrary_uses_radians(plugin, plugin_mod, monkeypatch):
    import math
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)

    plugin._transform_layer({"operation": "rotate", "angle": 30, "interpolation": "none"})

    layer.transform_rotate_simple.assert_not_called()
    args = layer.transform_rotate.call_args[0]
    assert args[0] == pytest.approx(math.radians(30))
    # ADJUST + interpolation applied within the context block.
    plugin_mod.Gimp.context_set_transform_resize.assert_called_with(
        plugin_mod.Gimp.TransformResize.ADJUST)
    plugin_mod.Gimp.context_set_interpolation.assert_called_with(
        plugin_mod.Gimp.InterpolationType.NONE)


def test_rotate_missing_angle_fails_loud(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    out = plugin._transform_layer({"operation": "rotate"})
    assert out["status"] == "error"
    assert "angle" in out["error"]
    layer.transform_rotate_simple.assert_not_called()


def test_scale_computes_bbox_from_offset(plugin, monkeypatch):
    layer = _make_layer(offsets=(10, 20))
    _stub_image_layer(plugin, monkeypatch, layer)

    plugin._transform_layer({"operation": "scale", "scale_width": 200, "scale_height": 120})

    layer.transform_scale.assert_called_once_with(10, 20, 210, 140)


def test_scale_missing_dim_fails_loud(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    out = plugin._transform_layer({"operation": "scale", "scale_width": 100})
    assert out["status"] == "error"
    layer.transform_scale.assert_not_called()


def test_scale_nonpositive_fails_loud(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    out = plugin._transform_layer({"operation": "scale", "scale_width": 0, "scale_height": 50})
    assert out["status"] == "error"
    layer.transform_scale.assert_not_called()


def test_flip_horizontal(plugin, plugin_mod, monkeypatch):
    Gimp = plugin_mod.Gimp
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)

    plugin._transform_layer({"operation": "flip", "flip_axis": "horizontal"})

    layer.transform_flip_simple.assert_called_once_with(Gimp.OrientationType.HORIZONTAL, True, 0.0)


def test_flip_missing_axis_fails_loud(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    out = plugin._transform_layer({"operation": "flip"})
    assert out["status"] == "error"
    layer.transform_flip_simple.assert_not_called()


def test_offset_calls_set_offsets_zero_preserved(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)

    plugin._transform_layer({"operation": "offset", "offset_x": 0, "offset_y": 25})

    layer.set_offsets.assert_called_once_with(0, 25)


def test_offset_missing_coord_fails_loud(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    out = plugin._transform_layer({"operation": "offset", "offset_x": 10})
    assert out["status"] == "error"
    layer.set_offsets.assert_not_called()


def test_unknown_operation_fails_loud(plugin, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    out = plugin._transform_layer({"operation": "bogus"})
    assert out["status"] == "error"
    assert "Unknown operation" in out["error"]


def test_context_pushed_and_popped_on_success(plugin, plugin_mod, monkeypatch):
    layer = _make_layer()
    _stub_image_layer(plugin, monkeypatch, layer)
    plugin_mod.Gimp.context_push.reset_mock()
    plugin_mod.Gimp.context_pop.reset_mock()

    plugin._transform_layer({"operation": "offset", "offset_x": 1, "offset_y": 2})

    plugin_mod.Gimp.context_push.assert_called_once()
    plugin_mod.Gimp.context_pop.assert_called_once()


def test_context_popped_even_on_error(plugin, plugin_mod, monkeypatch):
    layer = _make_layer()
    image = _stub_image_layer(plugin, monkeypatch, layer)
    plugin_mod.Gimp.context_pop.reset_mock()

    out = plugin._transform_layer({"operation": "bogus"})

    assert out["status"] == "error"
    # finally block restores context + closes undo group even when op is invalid.
    plugin_mod.Gimp.context_pop.assert_called_once()
    image.undo_group_end.assert_called_once()
