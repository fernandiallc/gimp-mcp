#!/usr/bin/env python3
"""Unit tests for call_api raise-behavior and mutable-default removal.

No live GIMP required — mocks at the connection boundary by monkeypatching
gimp_mcp_server.get_gimp_connection. The @mcp.tool() decorator returns the
original function object, so call_api is directly callable with ctx=None.
"""
import inspect
import json

import pytest

import gimp_mcp_server as srv


class FakeConn:
    def __init__(self, response):
        self.response = response
        self.sent = None

    def send_command(self, cmd_type, params):
        self.sent = (cmd_type, params)
        return self.response


def _patch(monkeypatch, response):
    fake = FakeConn(response)
    monkeypatch.setattr(srv, "get_gimp_connection", lambda: fake)
    return fake


def test_success_returns_unchanged_json(monkeypatch):
    fake = _patch(monkeypatch, {"status": "success", "results": {"value": 42}})
    out = srv.call_api(None, "exec", ["a"])
    assert out == json.dumps({"value": 42})
    # wire params preserved; kwargs coerced to {}
    assert fake.sent == ("call_api", {"api_path": "exec", "args": ["a"], "kwargs": {}})


def test_args_none_coerced_to_empty_list(monkeypatch):
    fake = _patch(monkeypatch, {"status": "success", "results": None})
    srv.call_api(None, "exec")
    assert fake.sent[1]["args"] == []
    assert fake.sent[1]["kwargs"] == {}


def test_error_envelope_raises_with_plugin_error_and_traceback(monkeypatch):
    _patch(monkeypatch, {
        "status": "error",
        "error": "boom-from-plugin",
        "traceback": "Traceback (most recent call last):\nLine X",
    })
    with pytest.raises(Exception) as ei:
        srv.call_api(None, "exec", ["a"])
    msg = str(ei.value)
    assert "boom-from-plugin" in msg
    assert "Traceback" in msg
    assert not msg.startswith("Error:")


def test_error_without_traceback_no_trailing_newline(monkeypatch):
    _patch(monkeypatch, {"status": "error", "error": "boom"})
    with pytest.raises(Exception) as ei:
        srv.call_api(None, "exec")
    msg = str(ei.value)
    assert "boom" in msg
    assert not msg.endswith("\n")


def test_error_missing_error_key_uses_unknown(monkeypatch):
    _patch(monkeypatch, {"status": "error"})
    with pytest.raises(Exception) as ei:
        srv.call_api(None, "exec")
    assert "Unknown error" in str(ei.value)


def test_default_args_are_none_sentinels():
    sig = inspect.signature(srv.call_api)
    assert sig.parameters["args"].default is None
    assert sig.parameters["kwargs"].default is None


def test_no_function_has_mutable_default():
    for _name, fn in inspect.getmembers(srv, inspect.isfunction):
        for pname, p in inspect.signature(fn).parameters.items():
            assert not isinstance(p.default, (list, dict)), (
                f"{_name}() param {pname!r} has mutable default {p.default!r}"
            )
