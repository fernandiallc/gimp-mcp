#!/usr/bin/env python3
"""Unit tests for NDJSON wire framing (no GIMP required).

The plugin module imports gi/Gimp and is not importable in this test layer, so the
receiver is exercised through GimpConnection.send_command, which runs the IDENTICAL
read-until-'\n'-or-EOF algorithm as the plugin's _handle_client recv loop. A fake
chunked socket lets us split the response bytes at any boundary and assert that the
buffer is json.loads-parsed exactly ONCE (the whole point of the O(n) change).
"""
import json

import pytest

import gimp_mcp_server as s


class FakeSocket:
    """recv() returns the pre-seeded chunks in order, then b'' (EOF).

    sendall() captures outgoing bytes so we can assert the request '\n' terminator.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.sent = b''

    def sendall(self, data):
        self.sent += data

    def recv(self, _bufsize):
        return self._chunks.pop(0) if self._chunks else b''

    def settimeout(self, _t):
        pass

    def close(self):
        pass


def _conn_with(chunks):
    c = s.GimpConnection()
    c.sock = FakeSocket(chunks)        # pre-connected: send_command skips connect()
    return c


def _count_loads(monkeypatch):
    """Wrap json.loads with a counter so we can prove a single response parse."""
    real = s.json.loads
    calls = {"n": 0}

    def counted(x, *a, **k):
        calls["n"] += 1
        return real(x, *a, **k)

    monkeypatch.setattr(s.json, "loads", counted)
    return calls


def test_single_chunk_newline_terminated(monkeypatch):
    calls = _count_loads(monkeypatch)
    conn = _conn_with([b'{"status":"success","results":1}\n'])
    sock = conn.sock   # send_command's finally disconnect() nulls conn.sock
    result = conn.send_command("noop")
    assert result == {"status": "success", "results": 1}
    assert calls["n"] == 1
    assert sock.sent.endswith(b'\n')   # request terminator


def test_split_across_terminator(monkeypatch):
    calls = _count_loads(monkeypatch)
    conn = _conn_with([b'{"status":"success"', b',"results":1}', b'\n'])
    result = conn.send_command("noop")
    assert result == {"status": "success", "results": 1}
    assert calls["n"] == 1


def test_terminator_split_from_body_mid_token(monkeypatch):
    calls = _count_loads(monkeypatch)
    conn = _conn_with([b'{"a":1', b'2}\n'])
    result = conn.send_command("noop")
    assert result == {"a": 12}
    assert calls["n"] == 1


def test_old_style_no_newline_eof(monkeypatch):
    calls = _count_loads(monkeypatch)
    # OLD plugin: no trailing '\n', completes on EOF (recv()==b'').
    conn = _conn_with([b'{"status":"success","results":1}'])
    result = conn.send_command("noop")
    assert result == {"status": "success", "results": 1}
    assert calls["n"] == 1


def test_large_multi_mb_payload(monkeypatch):
    calls = _count_loads(monkeypatch)
    payload = {"status": "success", "data": "A" * 5_000_000}
    raw = json.dumps(payload).encode("utf-8") + b'\n'
    chunks = [raw[i:i + 65536] for i in range(0, len(raw), 65536)]
    assert len(chunks) > 50    # genuinely multi-chunk
    conn = _conn_with(chunks)
    result = conn.send_command("noop")
    assert result == payload
    assert calls["n"] == 1     # proves NO O(n^2) re-parse of the growing buffer


def test_empty_connection_raises():
    conn = _conn_with([])      # immediate EOF, recv()==b''
    with pytest.raises(Exception, match="Error communicating with GIMP"):
        conn.send_command("noop")


def test_multibyte_utf8_split_across_chunks(monkeypatch):
    calls = _count_loads(monkeypatch)
    # ensure_ascii=False so the codepoints land on the wire as raw multibyte UTF-8
    # (json's default would escape them to ASCII \uXXXX, defeating the test).
    body = json.dumps({"status": "success", "s": "café—ñ"}, ensure_ascii=False).encode("utf-8")
    raw = body + b'\n'
    # Split mid-multibyte-codepoint: a per-chunk decode would raise UnicodeDecodeError.
    mid = body.find(b'\xc3')   # first byte of a 2-byte UTF-8 sequence (é/ñ)
    assert mid != -1
    chunks = [raw[:mid + 1], raw[mid + 1:]]
    conn = _conn_with(chunks)
    result = conn.send_command("noop")
    assert result == {"status": "success", "s": "café—ñ"}
    assert calls["n"] == 1
