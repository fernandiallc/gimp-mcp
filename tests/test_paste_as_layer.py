"""Unit tests for the paste_as_layer @mcp.tool wrapper — mock socket, assert wire + envelope.

No GIMP required: get_gimp_connection is monkeypatched with a recording FakeConn.
"""
import pytest

import gimp_mcp_server as s


def test_paste_as_layer_sends_correct_command(fake_conn_factory):
    fake = fake_conn_factory({
        "status": "success",
        "results": {"layer_name": "Logo", "layer_id": 42, "width": 100, "height": 50},
    })
    out = s.paste_as_layer(
        ctx=None, file_path="/abs/logo.png",
        position=2, offset_x=10, offset_y=20, name="Logo", image_index=1,
    )
    name, params = fake.sent[0]
    assert name == "paste_as_layer"
    assert params == {
        "file_path": "/abs/logo.png",
        "position": 2,
        "offset_x": 10,
        "offset_y": 20,
        "name": "Logo",
        "image_index": 1,
    }
    assert out == {"layer_name": "Logo", "layer_id": 42, "width": 100, "height": 50}


def test_paste_as_layer_defaults(fake_conn_factory):
    fake = fake_conn_factory({
        "status": "success",
        "results": {"layer_name": "logo.png", "layer_id": 7, "width": 8, "height": 8},
    })
    s.paste_as_layer(ctx=None, file_path="/abs/logo.png")
    _, params = fake.sent[0]
    assert params == {
        "file_path": "/abs/logo.png",
        "position": -1,
        "offset_x": 0,
        "offset_y": 0,
        "name": None,
        "image_index": 0,
    }


def test_paste_as_layer_return_shape_exact_keys(fake_conn_factory):
    fake_conn_factory({
        "status": "success",
        "results": {"layer_name": "L", "layer_id": 1, "width": 4, "height": 4},
    })
    out = s.paste_as_layer(ctx=None, file_path="/abs/x.png")
    assert set(out.keys()) == {"layer_name", "layer_id", "width", "height"}


def test_paste_as_layer_raises_on_error_envelope(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "File not found: /x"})
    with pytest.raises(Exception, match="paste_as_layer failed.*File not found"):
        s.paste_as_layer(ctx=None, file_path="/x")
