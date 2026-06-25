"""Static contract test: server command names must have matching plugin dispatch.

Parses both source files as text (CRLF-normalized per CLAUDE.md). The plugin is
read as text, never imported — its filename has hyphens and it imports gi/Gimp,
which are unavailable in CI. No GIMP, no socket.

Fails loud if either parse yields too few names: a zero/near-zero parse means a
CRLF/encoding/path regression, not "all green".
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER = REPO_ROOT / "gimp_mcp_server.py"
PLUGIN = REPO_ROOT / "gimp-mcp-plugin.py"


def _read(path):
    # core.autocrlf=true => working tree is CRLF; normalize so anchors stay safe.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _server_command_names(text):
    return set(re.findall(r'send_command\(\s*["\'](\w+)["\']', text))


def _plugin_branch_names(text):
    return set(re.findall(r'j\["type"\]\s*==\s*"(\w+)"', text))


def _plugin_handler_defs(text):
    return set(re.findall(r'def\s+(_\w+)\s*\(self', text))


def _execute_command_block(text):
    """Slice the execute_command method body to scope dispatch-target extraction."""
    start = text.index("def execute_command(self")
    nxt = re.search(r"\n    def \w", text[start + 1:])
    return text[start:start + 1 + nxt.start()] if nxt else text[start:]


def _dispatched_methods(block):
    return set(re.findall(r"return self\.(_\w+)\(", block))


SERVER_TEXT = _read(SERVER)
PLUGIN_TEXT = _read(PLUGIN)
SERVER_CMDS = _server_command_names(SERVER_TEXT)
PLUGIN_BRANCHES = _plugin_branch_names(PLUGIN_TEXT)
PLUGIN_DEFS = _plugin_handler_defs(PLUGIN_TEXT)
DISPATCH_BLOCK = _execute_command_block(PLUGIN_TEXT)
DISPATCHED = _dispatched_methods(DISPATCH_BLOCK)


def test_parsers_are_not_empty():
    # Fail loud: a small parse means a CRLF/encoding/path regression, not success.
    assert len(SERVER_CMDS) >= 50, f"server parse too small: {len(SERVER_CMDS)}"
    assert len(PLUGIN_BRANCHES) >= 50, f"plugin branch parse too small: {len(PLUGIN_BRANCHES)}"
    assert len(PLUGIN_DEFS) >= 50, f"plugin handler-def parse too small: {len(PLUGIN_DEFS)}"
    assert DISPATCHED, "no dispatch targets parsed from execute_command"


def test_every_server_command_has_a_plugin_branch():
    # call_api is intentionally handled by the exec fallthrough (plugin else-branch), no elif.
    missing = SERVER_CMDS - PLUGIN_BRANCHES - {"call_api"}
    assert missing == set(), f"server commands with no plugin dispatch branch: {sorted(missing)}"


def test_every_dispatch_target_handler_is_defined():
    # Catches a branch wired to a typo'd/removed handler. Tolerates the aliases
    # (_get_current_image_bitmap / _get_current_image_metadata) and inline check_server,
    # because it checks the method each branch actually calls (return self._X(...)).
    undefined = DISPATCHED - PLUGIN_DEFS
    assert undefined == set(), f"dispatch routes to undefined handlers: {sorted(undefined)}"
