"""Shared fixtures for the no-GIMP unit/contract test layer."""
import sys
from pathlib import Path

import pytest

# pyproject sets pythonpath=["."], but insert REPO_ROOT here too so the import
# works regardless of how pytest resolves rootdir / install mode.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeConn:
    """Stand-in for GimpConnection: records (type, params), returns a canned envelope.

    Mirrors GimpConnection.send_command(command_type, params=None) (server.py:55).
    """

    def __init__(self, reply):
        self.reply = reply
        self.sent = []          # list[tuple[str, dict | None]]

    def send_command(self, command_type, params=None):
        self.sent.append((command_type, params))
        return self.reply


@pytest.fixture
def fake_conn_factory(monkeypatch):
    """Return a builder that patches get_gimp_connection to yield a FakeConn(reply)."""
    import gimp_mcp_server as s

    def _build(reply):
        fake = FakeConn(reply)
        monkeypatch.setattr(s, "get_gimp_connection", lambda: fake)
        return fake

    return _build
