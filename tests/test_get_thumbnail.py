"""Unit tests for the in-memory get_thumbnail tool (server layer only).

No GIMP: get_gimp_connection is monkeypatched with the recording FakeConn fixture
(conftest.py). Asserts the SERVER contract — wire params, base64 decode, error
propagation, the 1024 clamp, and that nothing leaks to stdout (stdio JSON-RPC must
stay clean). The plugin path (Gimp.Image.get_thumbnail + GdkPixbuf.save_to_bufferv)
needs live GIMP 3.2 to verify.
"""
import base64

import gimp_mcp_server as s


def _reply(fmt="jpeg"):
    results = {"image_data": base64.b64encode(b"x").decode(), "width": 10, "height": 10}
    if fmt is not None:
        results["format"] = fmt
    return {"status": "success", "results": results}


def test_sends_type_and_params(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    s.get_thumbnail(ctx=None, image_index=2, max_size=256, format="jpeg", quality=70)
    name, params = fake.sent[0]
    assert name == "get_thumbnail"
    assert params == {"image_index": 2, "max_size": 256, "format": "jpeg", "quality": 70}


def test_default_format_is_jpeg(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    s.get_thumbnail(ctx=None)
    _, params = fake.sent[0]
    assert params["format"] == "jpeg"
    assert params["max_size"] == 512


def test_decodes_image_jpeg(fake_conn_factory):
    fake_conn_factory(_reply("jpeg"))
    out = s.get_thumbnail(ctx=None, format="jpeg")
    assert out._format == "jpeg"


def test_decodes_image_png(fake_conn_factory):
    fake_conn_factory(_reply("png"))
    out = s.get_thumbnail(ctx=None, format="png")
    assert out._format == "png"


def test_missing_format_key_defaults_png(fake_conn_factory):
    fake_conn_factory(_reply(None))      # plugin omitted format
    out = s.get_thumbnail(ctx=None)
    assert out._format == "png"


def test_max_size_clamped_to_1024(fake_conn_factory):
    fake = fake_conn_factory(_reply("jpeg"))
    s.get_thumbnail(ctx=None, max_size=4096)
    _, params = fake.sent[0]
    assert params["max_size"] == 1024    # API hard cap enforced at server layer


def test_error_reply_raises(fake_conn_factory):
    fake_conn_factory({"status": "error", "error": "No images are currently open in GIMP"})
    try:
        s.get_thumbnail(ctx=None)
        assert False, "expected get_thumbnail to raise on status:error"
    except Exception as e:
        assert "No images are currently open" in str(e)


def test_stdout_stays_clean(fake_conn_factory, capsys):
    # stdio JSON-RPC channel == server STDOUT; the tool must never print there.
    fake_conn_factory(_reply("jpeg"))
    s.get_thumbnail(ctx=None)
    assert capsys.readouterr().out == ""
