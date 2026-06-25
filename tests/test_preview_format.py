"""Unit tests for JPEG + quality preview support on get_image_bitmap / get_state_snapshot.

No GIMP required: get_gimp_connection is monkeypatched with the recording FakeConn
fixture (conftest.py). These tests assert the SERVER layer only:
  - format/quality are forwarded over the wire ONLY when non-default (back-compat),
  - the returned Image honors results["format"] instead of a hardcoded "png".
The plugin JPEG export path (file-jpeg-export) requires live GIMP 3.2 to verify.
"""
import base64

import gimp_mcp_server as s


def _reply(fmt=None):
    """Canned success envelope; include a format only when fmt is given so we can
    also exercise the missing-key (old-plugin) back-compat path."""
    results = {"image_data": base64.b64encode(b"x").decode(), "width": 10, "height": 10}
    if fmt is not None:
        results["format"] = fmt
    return {"status": "success", "results": results}


# get_image_bitmap -----------------------------------------------------------

def test_bitmap_png_default_omits_format_param(fake_conn_factory):
    fake = fake_conn_factory(_reply("png"))
    s.get_image_bitmap(ctx=None)
    name, params = fake.sent[0]
    assert name == "get_image_bitmap"
    assert "format" not in params     # byte-identical legacy wire params
    assert "quality" not in params


def test_bitmap_jpeg_forwards_format_and_quality(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    s.get_image_bitmap(ctx=None, format="jpeg", quality=70)
    _, params = fake.sent[0]
    assert params["format"] == "jpeg"
    assert params["quality"] == 70


def test_bitmap_returns_server_format_jpeg(fake_conn_factory):
    fake_conn_factory(_reply("jpeg"))
    out = s.get_image_bitmap(ctx=None, format="jpeg")
    assert out._format == "jpeg"      # reads results["format"], not hardcoded


def test_bitmap_returns_server_format_png(fake_conn_factory):
    fake_conn_factory(_reply("png"))
    out = s.get_image_bitmap(ctx=None)
    assert out._format == "png"


def test_bitmap_missing_format_key_defaults_png(fake_conn_factory):
    fake_conn_factory(_reply(None))   # old plugin: no format key in results
    out = s.get_image_bitmap(ctx=None)
    assert out._format == "png"


def test_bitmap_existing_params_still_map(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    region = {"origin_x": 0, "origin_y": 0, "width": 5, "height": 5}
    s.get_image_bitmap(ctx=None, max_width=100, max_height=80, region=region, format="jpeg")
    _, params = fake.sent[0]
    assert params["max_width"] == 100
    assert params["max_height"] == 80
    assert params["region"] == region
    assert params["format"] == "jpeg"


# get_state_snapshot ---------------------------------------------------------

def test_snapshot_png_default_omits_format(fake_conn_factory):
    fake = fake_conn_factory(_reply("png"))
    s.get_state_snapshot(ctx=None)
    name, params = fake.sent[0]
    assert name == "get_image_bitmap"
    assert "format" not in params
    assert "quality" not in params
    # max_size maps onto max_width/max_height (AC #3 at the server layer)
    assert params["max_width"] == 512
    assert params["max_height"] == 512


def test_snapshot_jpeg_forwards(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    out = s.get_state_snapshot(ctx=None, format="jpeg", quality=60)
    _, params = fake.sent[0]
    assert params["format"] == "jpeg"
    assert params["quality"] == 60
    assert out._format == "jpeg"


def test_snapshot_jpeg_with_region(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    s.get_state_snapshot(ctx=None, region={"x": 200, "y": 300, "width": 100, "height": 80}, format="jpeg")
    _, params = fake.sent[0]
    assert params["format"] == "jpeg"
    assert params["region"] == {"origin_x": 200, "origin_y": 300, "width": 100, "height": 80}


def test_snapshot_missing_format_key_defaults_png(fake_conn_factory):
    fake_conn_factory(_reply(None))
    out = s.get_state_snapshot(ctx=None)
    assert out._format == "png"
