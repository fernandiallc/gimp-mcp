# Changelog

This is a fork of [`maorcc/gimp-mcp`](https://github.com/maorcc/gimp-mcp) that
hardens reliability, fixes GIMP 3.2 crashes and bugs, adds tools, and adds a
test/CI safety net. All notable changes from the upstream baseline are listed
below, newest first. Dates are when the work landed on `main`.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com).
`0.1.0` is the first tagged release of the fork; entries are grouped by theme.

## [0.1.0] — 2026-06-26

### Reliability & correctness (the headline work)

- **`undo` / `redo` no longer crash — honest fail instead.** GIMP 3.2's plug-in
  API exposes undo *grouping* but no call to *perform* an undo/redo step (verified
  live against 3.2.4: neither `Gimp.Image` nor the PDB has one — it is a GUI-only
  action). The tools called a non-existent `image.undo()` and always died with
  `AttributeError`. They now return a clear, actionable error: undo manually in
  GIMP (Ctrl+Z; ops are wrapped in undo groups) or use `save_xcf` /
  `duplicate_layer` restore points before risky edits.
- **Layer offset bool leak (`get_offsets`).** GIMP 3.x's `get_offsets()` returns
  a 3-tuple `(success, x, y)`; the success flag leaked through, so `list_layers`
  reported `offsets: [true, 0, 0]` and `transform_layer`'s scale path crashed on a
  2-value unpack. A shared `_layer_offsets()` helper strips the bool at all sites.
- **`restart`/accept-loop busy-spin.** A non-timeout `OSError` in the socket
  accept loop re-looped with no backoff, pegging a CPU core if the error
  persisted. It now backs off briefly and requests a listener rebind to self-heal.

- **Thread-safety crash fix (root cause).** libgimp/PDB is not thread-safe, but
  client requests were handled on worker threads, so heavy ops (scale/flatten/
  export of large multi-layer images) could hard-crash GIMP. All GIMP-touching
  work is now marshalled onto the GIMP main thread via `GLib.idle_add` + a
  blocking `threading.Event`; socket I/O stays on the worker. Exceptions are
  captured and returned as error dicts — the plugin never crashes the process.
- **Bug fixes:** histogram channel indexing; `get_displays` removal +
  image→display tracking (so `close_image` doesn't leave ghost windows); stable
  image ordering; `get_image_bitmap` image-index consistency.
- **`get_image_metadata`:** `layer_type` now uses `drawable.type()` (was the
  inherited GObject `get_type()`, which rendered the class GType repr); `is_group`
  now uses `gimp_item_is_group()` (was `hasattr(layer,'get_children')`, true for
  every layer). Same `get_type()` misuse also fixed in `warp_region`.
- **Color parsing:** `rgb()/rgba()` colors given as 0–255 integers (e.g.
  `rgb(128,128,128)`) were parsed by Gegl as 0–1 floats and clamped to **white**,
  silently breaking color in every color-taking tool. A shared `_parse_color()`
  helper now detects the integer scale and normalizes to 0–1; named colors, hex,
  and float `rgb()` are unaffected.
- **`call_api` error symmetry:** now raises on a GIMP error envelope (like every
  structured tool) instead of returning an `"Error: ..."` success string, and
  surfaces the plugin traceback.
- **`restart_server` race fix:** the accept loop owns socket teardown/rebind
  (the handler thread only sets a flag), so a restart can't leave a dead listener.

### Security

- **`GIMP_MCP_ALLOW_EXEC` gate (default OFF).** Raw code execution via
  `call_api` / `cmds` / `args` (the `eval`/`exec` paths) is disabled unless the
  env var is set. The ~93 named structured tools (image edits) always work. The
  exec state is reported by `check_server` / `get_gimp_info` (`exec_enabled`).
  Shrinks the attack surface for anything that can reach loopback TCP 9877 from
  arbitrary Python to image edits only.

### Performance

- **NDJSON wire framing (both ends).** Replaced the O(n²) parse-until-valid
  framing with O(n) newline-delimited framing (read until `\n` or EOF, `bytearray`
  accumulation, 64 KB chunks). Removes multi-second CPU burn on large bitmap
  round-trips and the latent coalescing-desync risk. Wire-compatible (no
  `PROTOCOL_VERSION` bump).
- **`get_thumbnail`:** in-memory preview that skips the temp-file export pipeline.
- **JPEG previews:** `get_image_bitmap` / `get_state_snapshot` support JPEG +
  quality for ~8–10× smaller payloads (non-destructive — the live image is not
  flattened).

### New tools

- **Non-destructive GEGL:** `apply_filter` (generic, parametric, stacking
  `Gimp.DrawableFilter` over the GEGL catalog; fails loud on an unknown property).
  Now also takes `opacity` (0–100; converted to the filter's 0–1 scale) and
  `blend_mode` (layer-mode vocabulary), so a non-destructive effect can be applied
  partially or composited (e.g. a 40-opacity blur, or a bloom in "screen").
- **Layers/masks:** `add_layer_mask`, `apply_layer_mask`, `merge_down`,
  `layer_from_visible` (non-destructive merged stamp).
- **Transforms:** `transform_layer` (per-layer rotate/scale/flip/offset; fails
  loud on an active selection).
- **Selections/channels:** `alpha_to_selection`, `select_contiguous` (magic wand),
  `selection_to_channel`, `channel_to_selection`.
- **Color/paint:** `adjust_levels` (explicit black/white/gamma + output points),
  `bucket_fill` (paint-bucket flood fill from a seed point).
- **Compositing:** `paste_as_layer` (load an external file as a layer).
- Total named tools: **93** (was 56 upstream).

### Tooling, packaging & docs

- **`PROTOCOL_VERSION` handshake:** server and plugin carry a wire-version
  integer; `check_server` warns (non-fatally) on a repo-vs-installed mismatch.
- **`deploy.ps1`:** one-command Windows install/update with a `-Check` SHA-256
  drift mode (exit `0` in-sync / `10` drift / `20` not-installed).
- **Observability:** rotating file log at `%TEMP%/gimp_mcp_server.log` with
  per-request ids and surfaced plugin tracebacks; stdout kept clean (it is the
  JSON-RPC channel for the stdio transport).
- **Tests & CI:** a no-GIMP test layer (mock-socket unit tests, a static
  dispatch-contract test that fails the build on server/plugin drift, and
  framing round-trip tests) — **172 tests**, run in CI alongside `ruff`. The
  live-GIMP `run_tests.py` remains as a manual integration suite.
- **`print()` guard (ruff T20):** enforced on `gimp_mcp_server.py`, whose stdout
  is the JSON-RPC channel — a stray `print()` there corrupts the protocol, so it
  now fails lint. The plugin (separate process) and console scripts are exempt.
- **Removed the redundant `lint.yml`** workflow (its ruff job duplicated CI).
- **Dependency hygiene:** pinned `mcp>=1.12,<2`, dropped the standalone
  `fastmcp` dependency, committed `uv.lock`.

## Upstream baseline

See [`maorcc/gimp-mcp`](https://github.com/maorcc/gimp-mcp) for the original
project: the GIMP↔MCP bridge, the `get_state_snapshot` visual-feedback loop,
the initial 56-tool set, and GIMP 3.2 API-compatibility groundwork.
