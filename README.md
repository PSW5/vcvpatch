# vcvpatch

Read, write, inspect and validate **VCV Rack 2** `.vcv` patch files.
Python library, command-line tool, and an [MCP](https://modelcontextprotocol.io) server so
Claude Desktop (or any MCP client) can create and edit patches on disk.

## Why

Rack 2 does not save patches as plain JSON. A `.vcv` file is a **Zstandard-compressed tar
archive** containing `patch.json` plus a `modules/<id>/` folder for module assets (impulse
responses, samples, ...). Tools that treat `.vcv` as JSON cannot read Rack 2 files and
produce files Rack 2 cannot open. `vcvpatch` handles the real format, round-trips every
field losslessly, and keeps the assets.

`vcvpatch` works on files. It does not talk to a running Rack. For live control of a running
patch, see [Neural-Harmonics/vcv-rack-plugin](https://github.com/Neural-Harmonics/vcv-rack-plugin).

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# as a tool
uv tool install git+https://github.com/PSW5/vcvpatch

# or for development
git clone https://github.com/PSW5/vcvpatch
cd vcvpatch
uv sync --group dev
uv run pytest -q
```

## CLI

```bash
vcvpatch unpack my_patch.vcv                 # -> my_patch/patch.json + my_patch/modules/
vcvpatch pack my_patch -o my_patch_v2.vcv    # directory or a bare patch.json
vcvpatch info my_patch.vcv                   # module/cable summary (--json, --markdown)
vcvpatch validate my_patch.vcv               # exit 1 on errors (missing plugins, bad cables, ...)
vcvpatch library oscillator --tags Polyphonic  # search installed modules
vcvpatch catalog ~/my_patches                # INDEX.md + catalog/ for a folder of patches (see below)
vcvpatch mcp                                 # run the MCP server over stdio
```

`validate`, `info` and `library` look at the plugins installed in your Rack user directory
(`~/Library/Application Support/Rack2` on macOS, `%LOCALAPPDATA%\Rack2` on Windows,
`~/.local/share/Rack2` on Linux). Override with `RACK_USER_DIR`.

## Python API

```python
from vcvpatch import Library, Patch, read_vcv, validate, write_vcv

patch = read_vcv("drone.vcv")            # Patch(raw=<patch.json dict>, assets={...})
lib = Library.scan()                     # installed plugins, Core included

vco = patch.add_module("Fundamental", "VCO", version=lib.plugin_version("Fundamental"))
vcf = patch.add_module("Fundamental", "VCF", version=lib.plugin_version("Fundamental"))
patch.add_cable(vco["id"], 2, vcf["id"], 0)   # VCO SAW out -> VCF in
patch.set_param(vcf["id"], 0, 0.6)

for issue in validate(patch, lib):
    print(issue)
write_vcv(patch, "drone_v2.vcv")         # refuses to overwrite unless overwrite=True
```

`Patch.raw` is the untouched `patch.json` dict. Unknown keys are preserved, so
`read_vcv -> write_vcv -> read_vcv` yields identical content.

## MCP server

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`):

```json
{
  "mcpServers": {
    "vcvpatch": {
      "command": "uv",
      "args": ["--directory", "/path/to/vcvpatch", "run", "vcvpatch", "mcp"]
    }
  }
}
```

If installed with `uv tool install`, use `"command": "vcvpatch", "args": ["mcp"]` instead.

| Tool | What it does |
|---|---|
| `vcv_library_search` | Find exact `plugin` / `model` slugs among installed modules (query, tags) |
| `vcv_create` | Write a new `.vcv` from a module list and cables; ids, plugin versions and positions are filled in |
| `vcv_read` | Return `patch.json` contents, asset list and a text summary |
| `vcv_write` | Write a full `patch.json` dict; validates first; `keep_assets_from` preserves assets of the original |
| `vcv_validate` | Structural checks plus "is this plugin/module installed?" |

Suggested prompt flow: *search the library -> create the patch -> open the file in Rack*.
Every tool returns `{"ok": false, "error": "..."}` instead of raising, so the client can recover.

## Catalog a folder of patches

`vcvpatch catalog <dir>` turns a folder of `.vcv` files into something people and agents can browse:

```
<dir>/INDEX.md                    overview grouped by week (from names like ICMP_w5_ex_FM.vcv), with thumbnails
<dir>/catalog/catalog.json        one record per patch: week, topic, date, modules (with names), cables,
                                  embedded Notes text, plugins, bounding box, snapshot path, annotation
<dir>/catalog/patches/<stem>.md   one page per patch
<dir>/catalog/annotations.json    curated title / summary / tags / teaching_points; regeneration only adds
                                  missing entries (marked "inferred": true), it never overwrites yours
<dir>/catalog/snapshots/<stem>.png screenshots (see below)
```

Screenshots are taken by `scripts/snapshot_rack_macos.py` (macOS only). For every patch it writes a
temporary copy whose `zoom` and `gridOffset` fit the whole patch into the Rack window, relaunches Rack
with that file, waits for the log to report the modules, and captures the window:

```bash
uv run python scripts/snapshot_rack_macos.py ~/my_patches --size 1700x1050   # add --force to retake
```

It needs Screen Recording + Accessibility permission for your terminal, mutes the system volume while
running, and restores Rack's window settings afterwards.

## File format notes (Rack 2.5.x, observed)

- `.vcv` = `zstd(tar)` with entries `./`, `./patch.json`, `./modules/`, `./modules/<moduleId>/<asset>`.
- `patch.json` top level: `version`, `path`, `zoom`, `gridOffset`, `modules`, `cables`, `masterModuleId`.
- module: `id`, `plugin`, `model`, `version`, `params: [{id, value}]`, `pos: [x_hp, row]`,
  optional `leftModuleId`, `rightModuleId`, `data`.
- cable: `id`, `outputModuleId`, `outputId`, `inputModuleId`, `inputId`, `color`.
- `zoom` is linear; `gridOffset` is the viewport's top-left corner in grid units (HP, rows).
- ids are random 53-bit integers. Rack 1 files (plain JSON) are also readable.

## Limitations

- Offline tools cannot know a module's width or port count: auto-placement assumes 16 HP per
  module, and port indices are not range-checked. Pass `pos` explicitly for tight layouts.
- Parameter values are raw knob values, not Hz or dB.
- Windows paths follow the Rack manual but are untested.

## 繁體中文簡介

Rack 2 的 `.vcv` 不是純 JSON，而是 zstd 壓縮的 tar（內含 `patch.json` 與 `modules/` 附檔）。
`vcvpatch` 提供 Python 函式庫、CLI 與 MCP server，讓你（或 Claude）可以正確解包、打包、
檢視、驗證與產生 Rack 2 patch，並保證 round-trip 無損。它只處理檔案，不連線正在執行的 Rack。

## License

MIT
