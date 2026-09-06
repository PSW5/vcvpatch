# vcvpatch 設計規格

日期：2026-09-06
狀態：已核准（設計討論見對話），待實作

## 1. 目的

VCV Rack 2 的 `.vcv` 檔案不是純 JSON，而是 Zstandard 壓縮的 tar 檔，裡面放 `patch.json` 與模組附檔。
現有的「離線產生 patch」工具（例如 sandraschi/vcv-rack-mcp）把 `.vcv` 當純 JSON 處理，因此 Rack 2 讀不到它們的輸出，它們也讀不了 Rack 2 存的檔。

`vcvpatch` 提供三層：

1. **Python 函式庫**：正確讀寫 Rack 2 `.vcv`，保留所有欄位與附檔，並提供修改 patch 的 API。
2. **CLI**：終端機直接解包、打包、檢視、驗證。
3. **MCP server**：讓 Claude Desktop 等 MCP client 讀寫、建立、驗證本機的 `.vcv` 檔，並查詢已安裝的模組。

不做的事（YAGNI）：

- 不連線正在執行的 Rack（那是 Neural-Harmonics/vcv-rack-plugin 的工作）。
- 不維護手寫的模組參數目錄；模組資訊一律來自本機安裝的 `plugin.json`。
- 不做 GUI、不做 webapp。

## 2. 已觀察到的檔案格式（來源：使用者的 27 個 Rack 2.5.2 課程檔）

- 檔案開頭為 zstd magic `28 b5 2f fd`。解壓後是 ustar tar，內容：
  - `./` 目錄項
  - `./patch.json`
  - `./modules/` 目錄項；若模組有附檔，放在 `./modules/<moduleId>/<檔名>`（例如 `IR.wav`）
- `patch.json` 頂層鍵：`version`（Rack 版本字串）、`path`、`zoom`、`gridOffset`、`modules`、`cables`、`masterModuleId`。
- 每個 module：`id`、`plugin`、`model`、`version`（plugin 版本）、`params`（`[{id, value}]`）、`pos`（`[x, y]`，單位為 HP 與 row）、可選 `leftModuleId`、`rightModuleId`、`data`（模組自訂狀態）。
- 每條 cable：`id`、`outputModuleId`、`outputId`、`inputModuleId`、`inputId`、`color`。
- id 為 64 位元整數，Rack 隨機產生；小整數也合法。
- Rack 1 的 `.vcv` 是純 JSON 文字（開頭 `{`）。
- Rack autosave 是資料夾（`<user dir>/autosave/patch.json`），結構同解包後的 tar。

## 3. 架構

```
.vcv 檔 ──zstd 解壓──▶ tar ──▶ patch.json + assets ──▶ Patch 物件
                                                          │  修改（add_module / add_cable / set_param …）
.vcv 檔 ◀──zstd 壓縮── tar ◀── patch.json + assets ◀──────┘
```

套件採 src layout，Python ≥ 3.11，以 uv 管理。相依：`zstandard`（壓縮）、`mcp`（官方 SDK，提供 FastMCP）。測試相依：`pytest`。

```
vcvpatch/
├── pyproject.toml
├── README.md
├── LICENSE            (MIT)
├── CLAUDE.md
├── src/vcvpatch/
│   ├── __init__.py    公開 API 匯出
│   ├── errors.py      例外階層
│   ├── archive.py     .vcv 讀寫
│   ├── model.py       Patch 物件與修改 API
│   ├── library.py     掃描已安裝 plugin
│   ├── validate.py    檢查 patch
│   ├── summary.py     人看的摘要
│   ├── cli.py         argparse CLI
│   └── mcp_server.py  FastMCP server
└── tests/
```

## 4. 元件

### 4.1 `errors.py`

```
VcvPatchError(Exception)
├── FormatError        不是 zstd 也不是 JSON、tar 裡沒有 patch.json、JSON 解析失敗
├── RackNotFoundError  找不到 Rack 使用者目錄或 plugins 資料夾
└── ValidationError    寫入前的結構檢查失敗（例如 modules 不是 list）
```

### 4.2 `archive.py`

- `read_vcv(path: Path) -> Patch`
  - `path` 是檔案：讀前 4 bytes。zstd magic → 解壓、`tarfile` 讀取；`{` 開頭 → 視為 Rack 1 純 JSON，assets 為空。其他 → `FormatError`。
  - `path` 是目錄：讀 `path/patch.json`，assets 從 `path/modules/**` 收集。
  - tar 內的 `./modules/<id>/<file>` 全部以 `{相對路徑: bytes}` 放進 `Patch.assets`，相對路徑統一為 `modules/<id>/<file>`（去掉 `./`）。
- `write_vcv(patch: Patch, path: Path, *, overwrite: bool = False) -> None`
  - 目標已存在且 `overwrite=False` → `FileExistsError`。
  - 在記憶體組 tar：`./`、`./patch.json`、`./modules/`、每個 asset。tar 格式 ustar，mtime 用現在時間，uid/gid 0。
  - `patch.json` 以 `json.dumps(indent=2)` 序列化，與 Rack 的輸出風格接近。
  - zstd 壓縮後先寫到同目錄的暫存檔，再 `os.replace` 到目標路徑。
- `unpack_vcv(path, out_dir)` 與 `pack_dir(dir, path)`：CLI 用的便利函式，內部呼叫上面兩個。

### 4.3 `model.py`

`Patch` 是薄封裝，內部持有 `raw: dict`（整個 `patch.json`）與 `assets: dict[str, bytes]`。原則：**未知欄位一律保留**，round-trip 後 `raw` 必須與讀入時相等。

屬性與方法：

- `Patch.new(rack_version: str = "2.5.2") -> Patch`：空 patch，`modules=[]`、`cables=[]`、`masterModuleId=None`、`zoom=1.0`、`gridOffset=[0,0]`、`path=""`。
- `modules -> list[dict]`、`cables -> list[dict]`：直接回傳 `raw` 裡的 list（可變）。
- `get_module(id) -> dict | None`
- `add_module(plugin, model, *, version=None, pos=None, params=None, id=None) -> dict`
  - `id` 省略時產生一個未使用的隨機 63 位元正整數。
  - `pos` 省略時放在 row 0、所有既有模組最右邊再往右 1 HP（模組寬度未知，先用固定 12 HP 估算；`library` 沒有寬度資訊，這是已知限制）。
  - `params` 省略時為 `[]`；Rack 載入時會補預設值。
  - `version` 省略時為 `None`，由呼叫端（MCP `vcv_create`）用 `library` 補上；`None` 時不寫入該鍵。
- `add_cable(output_module_id, output_id, input_module_id, input_id, *, color=None, id=None) -> dict`
  - 檢查兩端模組存在，否則 `ValidationError`。
  - `color` 省略時輪流使用 Rack 預設四色 `#f3374b`、`#ffb437`、`#00b56e`、`#3695ef`。
- `remove_module(id)`：刪除模組、刪除連到它的 cable、清除相鄰模組的 `leftModuleId`/`rightModuleId`、若是 `masterModuleId` 則設為 `None`。
- `remove_cable(id)`
- `set_param(module_id, param_id, value)`：存在則更新，否則新增。
- `next_id() -> int`
- `to_json() -> str`

### 4.4 `library.py`

- `rack_user_dir() -> Path`：環境變數 `RACK_USER_DIR` 優先；否則依平台：
  - macOS `~/Library/Application Support/Rack2`
  - Windows `%LOCALAPPDATA%\Rack2`
  - Linux `~/.local/share/Rack2`
- `plugins_dir() -> Path`：`<user dir>/plugins-<os>-<arch>`，`os` ∈ `mac`/`win`/`lin`，`arch` ∈ `arm64`/`x64`（由 `platform.machine()` 判斷）。找不到 → `RackNotFoundError`。
- `Library.scan(plugins_dir=None) -> Library`：讀每個 `<slug>/plugin.json`，收集 `PluginInfo(slug, name, version, brand, modules: list[ModuleInfo])`，`ModuleInfo(slug, name, description, tags)`。損壞的 `plugin.json` 跳過並記錄警告，不中斷。
- `Library.search(query: str = "", tags: list[str] | None = None) -> list[ModuleInfo]`：不分大小寫比對 plugin slug、模組 slug、名稱、描述；tags 為 AND 條件。
- `Library.find(plugin_slug, model_slug) -> ModuleInfo | None`
- `Library.plugin_version(plugin_slug) -> str | None`

### 4.5 `validate.py`

`validate(patch: Patch, library: Library | None = None) -> list[Issue]`，`Issue(severity: "error" | "warning", where: str, message: str)`。

檢查項目：

| 項目 | severity |
|---|---|
| 頂層缺 `modules` 或 `cables`，或型別不對 | error |
| module 缺 `id`/`plugin`/`model` | error |
| module id 重複、cable id 重複 | error |
| cable 兩端 module id 不存在 | error |
| cable 的 outputId / inputId 為負數 | error |
| `leftModuleId`/`rightModuleId` 指到不存在的模組，或 A.right=B 但 B.left≠A | warning |
| `masterModuleId` 不存在於 modules | warning |
| 給了 `library` 時：plugin 未安裝 | error |
| 給了 `library` 時：plugin 有裝但 model 不存在 | error |
| 給了 `library` 時：module.version 與已安裝版本不同 | warning |

port 編號是否超出模組實際 port 數無法離線得知（`plugin.json` 不含），列為已知限制。

### 4.6 `summary.py`

`summarize(patch, library=None, fmt="text" | "markdown") -> str`。內容：Rack 版本、模組數、cable 數；模組表（id、plugin/model、名稱（有 library 才有）、pos、參數數量、附檔數）依 `pos[1]` 再 `pos[0]` 排序；接線表 `plugin/model#id out[n] → plugin/model#id in[n]`。

### 4.7 `cli.py`

進入點 `vcvpatch`，argparse 子命令：

| 命令 | 說明 |
|---|---|
| `unpack FILE [-o DIR]` | 解到資料夾（預設 `FILE` 去掉副檔名） |
| `pack SRC -o FILE [--force]` | `SRC` 為資料夾（含 patch.json）或單一 `.json` |
| `info FILE [--json] [--markdown]` | 摘要；`--json` 直接印 `patch.json` |
| `validate FILE [--no-library]` | 印出問題清單；有 error 回傳碼 1 |
| `library [QUERY] [--tags T ...] [--json]` | 搜尋已安裝模組 |
| `mcp` | 以 stdio 啟動 MCP server |

所有 `VcvPatchError` 於頂層攔截，印 `error: <訊息>` 到 stderr，回傳碼 2。

### 4.8 `mcp_server.py`

用 `mcp.server.fastmcp.FastMCP`，名稱 `vcvpatch`，stdio。工具回傳 dict；錯誤回傳 `{"ok": false, "error": "<訊息>"}` 而不丟例外，避免 client 端斷線。

| 工具 | 參數 | 回傳 |
|---|---|---|
| `vcv_read` | `path` | `{ok, path, rack_version, modules, cables, master_module_id, assets: [相對路徑], summary}` |
| `vcv_write` | `path`, `patch` (dict，即 patch.json 內容), `overwrite=False`, `keep_assets_from=None` | `{ok, path, issues}`；寫前先跑 `validate`，有 error 則不寫並回傳 issues。`keep_assets_from` 指向既有 `.vcv`，其附檔會一併帶入（用於「讀 → 改 → 另存」流程） |
| `vcv_create` | `path`, `modules: [{plugin, model, pos?, params?}]`, `cables: [{from: [模組索引, output_id], to: [模組索引, input_id]}]`, `overwrite=False` | 用 `Patch.new()` 建立，`version` 由 library 補、id 自動、pos 缺就自動排。回傳同 `vcv_write` 加上分配到的 module ids |
| `vcv_validate` | `path` | `{ok, issues}` |
| `vcv_library_search` | `query=""`, `tags=[]`, `limit=50` | `{ok, count, results: [{plugin, model, name, description, tags, plugin_version}]}` |

Claude Desktop 設定範例（寫進 README）：

```json
{ "mcpServers": { "vcvpatch": { "command": "uv", "args": ["--directory", "/path/to/vcvpatch", "run", "vcvpatch", "mcp"] } } }
```

## 5. 錯誤處理原則

- 函式庫層丟 `VcvPatchError` 子類別，訊息包含路徑。
- CLI 層統一攔截、印一行、非零回傳。
- MCP 層永不讓例外逃出工具函式。
- 寫檔一律暫存檔 + `os.replace`。
- `Library.scan` 對單一損壞 plugin 容錯。

## 6. 測試

pytest，不依賴使用者的真實檔案：

- `test_archive.py`：合成 patch（含一個假 asset）→ `write_vcv` → `read_vcv`，`raw` 與 `assets` 相等；Rack 1 純 JSON 讀取；不合法檔案丟 `FormatError`；`overwrite=False` 時拒絕覆蓋；若系統有 `zstd` 與 `tar` 執行檔，用它們解開我們寫出的檔案並比對 `patch.json`（沒有就 skip）。
- `test_model.py`：`add_module` 自動 id 不重複、自動 pos 往右排；`add_cable` 端點檢查；`remove_module` 連帶清理；`set_param` 新增與更新；未知欄位保留。
- `test_library.py`：用 `tmp_path` 造假的 `plugins-mac-arm64/<slug>/plugin.json`，測 scan、search（query、tags）、find、壞掉的 json 被跳過；`RACK_USER_DIR` 覆寫。
- `test_validate.py`：每個檢查項目至少一個案例。
- `test_cli.py`：用 `subprocess` 或直接呼叫 `main(argv)` 跑 unpack→pack→info→validate 流程。
- `test_mcp.py`：直接呼叫工具函式（不開 stdio），測 read/write/create/validate/search 的回傳結構與錯誤格式。

驗收（實作完成後手動執行，結果記錄在 README 或 PR 說明）：

1. 使用者 27 個課程 `.vcv` 全部 `read_vcv` → `write_vcv` → 再 `read_vcv`，`raw` 與 `assets` 完全相等。
2. 用 `vcv_create` 產生一個 `Fundamental VCO → Fundamental VCF → Core AudioInterface2` 的 patch，用 Rack 2 Pro 開啟，無缺模組警告。

## 7. 已知限制

- 離線無法得知模組寬度與 port 數量，自動排版用固定 12 HP 估算，port 編號不檢查上限。
- 不處理 Rack 的 `patch.json` 以外的 tar 內容（目前觀察只有 `modules/`）；若未來 Rack 加入其他目錄，`read_vcv` 會把它們一併放進 `assets` 保留，不會遺失。
- Windows 路徑與 `plugins-win-x64` 只依文件推定，未實測。
