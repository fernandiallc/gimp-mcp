# Changelog

This is a fork of [`maorcc/gimp-mcp`](https://github.com/maorcc/gimp-mcp) that
hardens reliability, fixes GIMP 3.2 crashes and bugs, adds tools, and adds a
test/CI safety net. All notable changes from the upstream baseline are listed
below, newest first. Dates are when the work landed on `main`.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com).
This project is not yet formally versioned; entries are grouped by theme.

## [Unreleased] — fork changes over upstream

### Reliability & correctness (the headline work)

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
  framing round-trip tests) — **162 tests**, run in CI alongside `ruff`. The
  live-GIMP `run_tests.py` remains as a manual integration suite.
- **Dependency hygiene:** pinned `mcp>=1.12,<2`, dropped the standalone
  `fastmcp` dependency, committed `uv.lock`.

## Upstream baseline

See [`maorcc/gimp-mcp`](https://github.com/maorcc/gimp-mcp) for the original
project: the GIMP↔MCP bridge, the `get_state_snapshot` visual-feedback loop,
the initial 56-tool set, and GIMP 3.2 API-compatibility groundwork.
