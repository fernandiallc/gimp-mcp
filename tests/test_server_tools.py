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
    }
    assert out == {"operation": "gegl:gaussian-blur"}


def test_apply_filter_merge_true_propagates(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {"mode": "merged"}})
    s.apply_filter(ctx=None, operation="gegl:pixelize", merge=True)
    assert fake.sent[0][1]["merge"] is True


def test_apply_filter_params_default_none(fake_conn_factory):
    fake = fake_conn_factory({"status": "success", "results": {}})
    s.apply_filter(ctx=None, operation="gegl:invert-linear")
    assert fake.sent[0][1]["params"] is None


def test_apply_filter_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "Invalid property 'foo'. Valid properties: ['std-dev-x']"})
    with pytest.raises(Exception, match="foo"):
        s.apply_filter(ctx=None, operation="gegl:gaussian-blur", params={"foo": 1})
