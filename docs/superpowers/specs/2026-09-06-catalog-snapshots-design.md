# 課程 patch 目錄與截圖機制 設計規格

日期：2026-09-06
狀態：已核准（對話中），實作中

## 1. 目的

使用者有一個資料夾（Google Drive `115-1_ICMP/vcv_files/`）放課程每週的 VCV Rack 範例 patch。需要：

1. 每個 patch 一張「看得到面板與接線」的截圖。
2. 一套系統性的整理檔，讓不同 session 或其他 agent（做簡報、整理課程內容）可以直接讀到每個 patch 的內容。
3. 可重複執行的管理機制：新增或修改 patch 後重跑指令即可更新，且人工註記不會被蓋掉。

## 2. 產出（放在 patch 資料夾內）

```
<dir>/
  INDEX.md                    總覽（生成）。開頭是 handoff 說明，之後依週次分組列出每個 patch。
  catalog/
    catalog.json              機器可讀（生成）。每個 patch 一筆完整紀錄。
    annotations.json          人工維護。key 為檔名 stem；生成器只「補缺」，不覆寫既有條目。
    patches/<stem>.md         每個 patch 一頁（生成）：截圖、模組表、接線表、內嵌 Notes、幾何範圍。
    snapshots/<stem>.png      截圖（由 macOS 腳本產生）。
```

## 3. 檔名規則（觀察自現有 28 個檔案）

`[ICMP_]w{週}_ex[_{主題}][_{yymmdd}].vcv`，例外：`ICMP_251020_ex_snh.vcv`（日期在前、無週次）、`ICMP_final-project-preset-example.vcv`（無週次）。

`parse_name(filename) -> {stem, week: int|None, topic: str, date: "YYYY-MM-DD"|None}`：
- `week`：第一個 `w(\d+)` token。
- `date`：任一個 6 位數 token `yymmdd`，轉成 `20yy-mm-dd`。
- `topic`：去掉 `ICMP`、`w\d+`、`ex`、日期 token 後，剩餘 token 以 `_` 接回；可為空字串。

## 4. 元件

### 4.1 `model.py` 新增

- `Patch.bbox() -> tuple[int, int, int, int] | None`：所有模組 `pos` 的 `(min_x, min_y, max_x, max_y)`，無模組回 `None`。

### 4.2 `catalog.py`（純函式 + 檔案輸出）

- 常數 `HP_PX = 15`、`ROW_PX = 380`（Rack 的 `RACK_GRID_WIDTH` / `RACK_GRID_HEIGHT`）。
- `fit_view(bbox, view_w, view_h, *, margin_hp=3.0, margin_rows=0.15, last_module_hp=20, zoom_min=0.25, zoom_max=1.5) -> tuple[float, list[float]]`：回傳 `(zoom, gridOffset)`，讓 bbox（右邊多留 `last_module_hp`，因為離線不知最後一個模組的寬度）置中塞進 `view_w × view_h` 像素的視窗。`gridOffset` 是視窗左上角的格線座標（HP、row），與 Rack `patch.json` 的語意相同。
- `parse_name(filename) -> dict`（§3）。
- `infer_annotation(record) -> dict`：依主題關鍵字與模組組成推斷 `title`、`tags`、`summary`，`inferred: true`。關鍵字表：snh=Sample & Hold、seq=Step sequencer、FM=FM synthesis、RING/ring=Ring modulation、additive=Additive synthesis、phy=Physical modelling、KS=Karplus-Strong、clock=Clock / dividers、TM=Turing Machine、euclidean/euc=Euclidean rhythm、rnd=Randomness、oct=Octave、mix=Mixing、eno=Generative ambient（Eno）、drone=Drone、ocean=Soundscape、random=Randomness、final-project=Final project。若模組含 AudibleInstruments `Resonator` 另加 tag `rings`。
- `build_record(path, library, snapshots_dir) -> dict`：一筆紀錄，欄位：`file`、`stem`、`week`、`topic`、`date`、`modified`（mtime ISO）、`size_bytes`、`sha1`（前 12 碼）、`rack_version`、`module_count`、`cable_count`、`asset_count`、`assets`、`plugins: {slug: count}`、`modules: [{id, plugin, model, name, pos, params}]`、`cables: [{from: "plugin/model#id", out, to, in}]`、`notes: [str]`（Core Notes 的 `data.text`）、`bbox: {min_x, min_y, max_x, max_y, width_hp, rows}`、`snapshot`（相對路徑或 `null`）。
- `load_annotations(path)` / `merge_annotations(existing, records) -> (annotations, added: list[str])`：對每筆紀錄，若 `annotations` 缺該 stem，補上 `infer_annotation`。
- `render_index(records, annotations, dir_name) -> str`、`render_patch_page(record, annotation) -> str`。
- `write_catalog(directory, library=None) -> dict`：串起以上，寫出 §2 的所有生成檔，回 `{"count", "index", "catalog", "annotations", "pages", "added_annotations"}`。

### 4.3 `cli.py` 新增

`vcvpatch catalog DIR [--no-library]`：呼叫 `write_catalog`，印出寫了幾筆與 INDEX 路徑。

### 4.4 `scripts/snapshot_rack_macos.py`（macOS 專用，不做單元測試）

```
uv run python scripts/snapshot_rack_macos.py DIR [--app "VCV Rack 2 Pro"] [--size 1700x1050] [--only NAME ...]
```
1. 編譯（或使用快取的）Swift 小工具 `rackwin`，用 `CGWindowListCopyWindowInfo` 找 Rack 主視窗 id 與 bounds。
2. 若 Rack 未執行則 `open -a` 啟動並等待視窗出現。
3. 用 System Events 把 Rack 視窗設成固定位置與大小（預設 1700×1050 點）。
4. 記錄目前系統音量，設為 0。
5. 對每個 `.vcv`：`read_vcv` → `fit_view(bbox, view_w, view_h)`（view 扣掉 Rack 選單列與捲軸）→ 寫入 `/tmp/vcvpatch_snapshots/<原檔名>`（保留 assets）→ `open -a <app> 暫存檔` → 輪詢 Rack `log.txt` 直到出現 `Loading patch <暫存檔>` 之後的 `Creating module widget` 行停止增加（上限 15 秒）→ 再等 1.5 秒讓畫面穩定 → `screencapture -x -o -l <wid> catalog/snapshots/<stem>.png`。
6. 全部完成後恢復音量、印出成功與失敗清單。
7. 已存在的截圖預設跳過，`--force` 才重拍。

## 5. INDEX.md 內容

1. 標題、產生時間、來源資料夾。
2. **Handoff 說明**：檔案結構、`catalog.json` 欄位、如何重新產生（兩個指令）、命名規則、`annotations.json` 的編輯方式。
3. 週次總表：每週一節，表格欄位：檔案、日期、主題（annotations 的 title）、模組數 / 接線數、plugins、截圖縮圖（Markdown 圖片，寬度受限）、詳細頁連結。
4. 無週次的檔案放在最後「其他」節。

## 6. 測試

- `tests/test_catalog.py`：`parse_name` 各種檔名；`fit_view` 小 patch 用 `zoom_max` 並置中、寬 patch 縮小到剛好塞進、`zoom_min` 下限；`Patch.bbox`；`write_catalog` 用合成 patch 與假 library 產生所有檔案、內容含 Notes 與模組名稱與截圖連結；重跑保留人工修改過的 annotation 並為新檔補條目；CLI `catalog` 回傳 0。

## 7. 已知限制

- 最後一列模組的寬度未知，右側固定多留 20 HP，截圖右邊可能有空白。
- 截圖依賴 macOS、Rack 在前景、以及終端機的「輔助使用」與「螢幕錄製」權限。
- Rack 的「最近開啟」與 autosave 會留下暫存檔路徑。
