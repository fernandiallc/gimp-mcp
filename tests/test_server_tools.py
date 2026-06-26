"""Unit tests for @mcp.tool wrappers — mock the socket, assert wire + envelope handling.

No GIMP required: get_gimp_connection is monkeypatched with a recording FakeConn.
The @mcp.tool() decorator returns the original function object, so each tool is
directly callable with ctx=None.
"""
import pytest

import gimp_mcp_server as s


# new_canvas ------------------------------------------------------------------

def test_new_canvas_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"image_id": 1}})
    out = s.new_canvas(ctx=None, width=800, height=600)
    name, params = fake.sent[0]
    assert name == "new_canvas"
    assert params["width"] == 800
    assert params["height"] == 600
    assert out == {"image_id": 1}            # returns result["results"]


def test_new_canvas_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "no image"})
    with pytest.raises(Exception, match="no image"):
        s.new_canvas(ctx=None, width=10, height=10)


# get_image_metadata ----------------------------------------------------------

def test_get_image_metadata_success(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"width": 4}})
    out = s.get_image_metadata(ctx=None)
    assert fake.sent[0][0] == "get_image_metadata"
    assert out == {"width": 4}


def test_get_image_metadata_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "no image"})
    with pytest.raises(Exception, match="no image"):
        s.get_image_metadata(ctx=None)


# call_api (couples to reliability-server: must RAISE on error envelope) -------

def test_call_api_sends_exec_payload(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": ["OK"]})
    s.call_api(ctx=None, api_path="exec", args=["python-fu-exec", ["x=1"]])
    name, params = fake.sent[0]
    assert name == "call_api"
    assert params["api_path"] == "exec"
    assert params["args"] == ["python-fu-exec", ["x=1"]]


def test_call_api_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "boom", "traceback": "tb"})
    with pytest.raises(Exception, match="boom"):
        s.call_api(ctx=None, api_path="exec", args=["python-fu-exec", ["nope"]])


# apply_filter (generic GEGL via Gimp.DrawableFilter) -------------------------

def test_apply_filter_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"operation": "gegl:gaussian-blur"}})
    out = s.apply_filter(
        ctx=None, operation="gegl:gaussian-blur",
        params={"std-dev-x": 5, "std-dev-y": 5},
    )
    name, params = fake.sent[0]
    assert name == "apply_filter"
    assert params == {
        "operation": "gegl:gaussian-blur",
        "params": {"std-dev-x": 5, "std-dev-y": 5},
        "image_index": 0,
        "layer_name": None,
        "merge": False,
        "opacity": 100,
        "blend_mode": None,
    }
    assert out == {"operation": "gegl:gaussian-blur"}


def test_apply_filter_merge_true_propagates(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"mode": "merged"}})
    s.apply_filter(ctx=None, operation="gegl:pixelize", merge=True)
    assert fake.sent[0][1]["merge"] is True


def test_apply_filter_opacity_and_blend_propagate(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {}})
    s.apply_filter(ctx=None, operation="gegl:bloom", opacity=40, blend_mode="screen")
    sent = fake.sent[0][1]
    assert sent["opacity"] == 40
    assert sent["blend_mode"] == "screen"


def test_apply_filter_opacity_blend_default(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {}})
    s.apply_filter(ctx=None, operation="gegl:vibrance")
    sent = fake.sent[0][1]
    assert sent["opacity"] == 100
    assert sent["blend_mode"] is None


def test_apply_filter_params_default_none(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {}})
    s.apply_filter(ctx=None, operation="gegl:invert-linear")
    assert fake.sent[0][1]["params"] is None


def test_apply_filter_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "Invalid property 'foo'. Valid properties: ['std-dev-x']"})
    with pytest.raises(Exception, match="foo"):
        s.apply_filter(ctx=None, operation="gegl:gaussian-blur", params={"foo": 1})


# alpha_to_selection ----------------------------------------------------------

def test_alpha_to_selection_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    out = s.alpha_to_selection(ctx=None, layer_name="Logo")
    name, params = fake.sent[0]
    assert name == "alpha_to_selection"
    assert params == {
        "layer_name": "Logo",
        "layer_index": None,
        "operation": "replace",
        "image_index": 0,
    }
    assert out == {"status": "success"}        # returns result["results"]


def test_alpha_to_selection_index_and_operation_propagate(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.alpha_to_selection(ctx=None, layer_index=2, operation="add", image_index=1)
    _, params = fake.sent[0]
    assert params["layer_index"] == 2
    assert params["operation"] == "add"
    assert params["image_index"] == 1
    assert params["layer_name"] is None


def test_alpha_to_selection_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "Layer 'Nope' not found"})
    with pytest.raises(Exception, match="Layer 'Nope' not found"):
        s.alpha_to_selection(ctx=None, layer_name="Nope")


# selection_to_channel --------------------------------------------------------

def test_selection_to_channel_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"channel_name": "mask1", "channel_id": 42}})
    out = s.selection_to_channel(ctx=None, name="mask1")
    name, params = fake.sent[0]
    assert name == "selection_to_channel"
    assert params == {"name": "mask1", "image_index": 0}
    assert out == {"channel_name": "mask1", "channel_id": 42}   # returns result["results"]


def test_selection_to_channel_image_index_propagates(fake_conn_factory):
    fake = fake_conn_factory({"status": "success",
                              "results": {"channel_name": "m", "channel_id": 7}})
    s.selection_to_channel(ctx=None, name="m", image_index=2)
    _, params = fake.sent[0]
    assert params["name"] == "m"
    assert params["image_index"] == 2


def test_selection_to_channel_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error",
                       "error": "Cannot save channel: the current selection is empty"})
    with pytest.raises(Exception, match="selection_to_channel failed.*selection is empty"):
        s.selection_to_channel(ctx=None, name="mask1")


# channel_to_selection --------------------------------------------------------

def test_channel_to_selection_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    out = s.channel_to_selection(ctx=None, channel_name="saved sel",
                                 operation="add", image_index=2)
    name, params = fake.sent[0]
    assert name == "channel_to_selection"
    assert params == {
        "channel_name": "saved sel",
        "operation": "add",
        "image_index": 2,
    }
    assert out == {"status": "success"}        # returns result["results"]


def test_channel_to_selection_defaults(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.channel_to_selection(ctx=None, channel_name="mask1")
    _, params = fake.sent[0]
    assert params["operation"] == "replace"
    assert params["image_index"] == 0


def test_channel_to_selection_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error",
                       "error": "No channel named 'x'. Available: ['mask1']"})
    with pytest.raises(Exception, match="channel_to_selection failed.*No channel named 'x'"):
        s.channel_to_selection(ctx=None, channel_name="x")


# select_contiguous (magic wand: seed + threshold, distinct from select_by_color) -

def test_select_contiguous_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    out = s.select_contiguous(ctx=None, x=10, y=20)
    name, params = fake.sent[0]
    assert name == "select_contiguous"
    assert params == {
        "x": 10,
        "y": 20,
        "threshold": 15,
        "sample_merged": False,
        "operation": "replace",
        "image_index": 0,
        "layer_name": None,
    }
    assert out == {"status": "success"}        # returns result["results"]


def test_select_contiguous_non_default_args_propagate(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"status": "success"}})
    s.select_contiguous(ctx=None, x=5, y=5, threshold=80, sample_merged=True,
                        operation="add", image_index=2, layer_name="bg")
    _, params = fake.sent[0]
    assert params == {
        "x": 5,
        "y": 5,
        "threshold": 80,
        "sample_merged": True,
        "operation": "add",
        "image_index": 2,
        "layer_name": "bg",
    }


def test_select_contiguous_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error",
                       "error": "Seed point (10,20) is outside image bounds 4x4"})
    with pytest.raises(Exception, match="select_contiguous failed.*outside image bounds"):
        s.select_contiguous(ctx=None, x=10, y=20)
