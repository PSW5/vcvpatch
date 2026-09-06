# vcvpatch

Python library + CLI + MCP server for VCV Rack 2 `.vcv` files (zstd-compressed tar containing `patch.json` and `modules/<id>/*` assets).

## Commands
- `uv sync --group dev` — install
- `uv run pytest -q` — tests (all pure; no Rack needed)
- `uv run vcvpatch --help` — CLI
- `uv run python scripts/roundtrip_check.py <dir>` — round-trip every .vcv in a folder

## Layout
- `src/vcvpatch/archive.py` — zstd/tar read & write (atomic writes)
- `src/vcvpatch/model.py` — `Patch` wraps the raw patch.json dict; unknown keys are preserved
- `src/vcvpatch/library.py` — scans `<Rack user dir>/plugins-*/**/plugin.json`; `Core` is built in
- `src/vcvpatch/validate.py`, `summary.py` — pure functions
- `src/vcvpatch/cli.py`, `mcp_server.py` — thin entry points

## Rules
- Never drop unknown JSON fields; round-trip must be lossless.
- MCP tools return `{"ok": false, "error": ...}` instead of raising.
- Set `RACK_USER_DIR` to point tests/tools at a fake Rack directory.
- Design spec: `docs/superpowers/specs/2026-09-06-vcvpatch-design.md`
