"""Generate a browsable catalog (INDEX.md, catalog.json, per-patch pages) for a folder of .vcv files."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .archive import read_vcv
from .library import Library
from .model import Patch

HP_PX = 15  # RACK_GRID_WIDTH
ROW_PX = 380  # RACK_GRID_HEIGHT
CATALOG_DIR = "catalog"
SNAPSHOTS_DIR = "snapshots"
PAGES_DIR = "patches"
ANNOTATIONS_FILE = "annotations.json"
CATALOG_FILE = "catalog.json"
INDEX_FILE = "INDEX.md"

# (regex matched against a lower-cased topic token, title fragment, tags)
TOPIC_KEYWORDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (r"^snh$", "Sample & Hold", ("sample-and-hold", "random", "lfo")),
    (r"^seq$", "Step sequencer", ("sequencer",)),
    (r"^fm$", "FM synthesis", ("fm", "synthesis")),
    (r"^ring$", "Ring modulation", ("ring-modulation", "synthesis")),
    (r"^additive$", "Additive synthesis", ("additive", "synthesis")),
    (r"^phy$", "Physical modelling", ("physical-modelling",)),
    (r"^ks$", "Karplus-Strong", ("karplus-strong", "physical-modelling")),
    (r"^clock$", "Clock & dividers", ("clock", "rhythm")),
    (r"^tm$", "Turing Machine", ("turing-machine", "random", "sequencer")),
    (r"^euc(lidean)?$", "Euclidean rhythm", ("euclidean", "rhythm", "sequencer")),
    (r"^(rnd|random)$", "Randomness", ("random",)),
    (r"^oct$", "Octave", ("pitch",)),
    (r"^mix$", "Mixing", ("mixer",)),
    (r"^eno$", "Generative ambient (Eno)", ("generative", "ambient")),
    (r"^drone$", "Drone", ("drone", "ambient")),
    (r"^ocean$", "Ocean soundscape", ("soundscape", "noise")),
    (r"^final$", "Final project", ("final-project",)),
    (r"^preset$", "Preset", ("preset",)),
    (r"^mod$", "", ("variant",)),
    (r"^v\d+$", "", ("variant",)),
    (r"^(example|project)$", "", ()),
)


# -- naming and geometry --------------------------------------------------------


def parse_name(filename: str) -> dict[str, Any]:
    """Split 'ICMP_w10_ex_clock_mod_251103.vcv' into stem/week/topic/date."""
    stem = Path(filename).stem
    week: int | None = None
    date: str | None = None
    rest: list[str] = []
    for token in stem.split("_"):
        if token.upper() == "ICMP" or token.lower() == "ex":
            continue
        week_match = re.fullmatch(r"[wW](\d+)", token)
        if week_match and week is None:
            week = int(week_match.group(1))
            continue
        if re.fullmatch(r"\d{6}", token) and date is None:
            date = f"20{token[:2]}-{token[2:4]}-{token[4:6]}"
            continue
        rest.append(token)
    return {"stem": stem, "week": week, "topic": "_".join(rest), "date": date}


def fit_view(
    bbox: tuple[int, int, int, int],
    view_w: float,
    view_h: float,
    *,
    margin_hp: float = 3.0,
    margin_rows: float = 0.15,
    last_module_hp: int = 20,
    zoom_min: float = 0.25,
    zoom_max: float = 1.5,
) -> tuple[float, list[float]]:
    """Return (zoom, gridOffset) so the bbox is centred inside a view_w x view_h pixel viewport."""
    min_x, min_y, max_x, max_y = bbox
    content_w_hp = (max_x - min_x) + last_module_hp
    content_h_rows = (max_y - min_y) + 1
    zoom = min(
        view_w / ((content_w_hp + 2 * margin_hp) * HP_PX),
        view_h / ((content_h_rows + 2 * margin_rows) * ROW_PX),
    )
    zoom = max(zoom_min, min(zoom_max, zoom))
    view_w_hp = view_w / zoom / HP_PX
    view_h_rows = view_h / zoom / ROW_PX
    offset = [min_x - (view_w_hp - content_w_hp) / 2, min_y - (view_h_rows - content_h_rows) / 2]
    return zoom, offset


# -- records ----------------------------------------------------------------------


def _notes(patch: Patch) -> list[str]:
    out = []
    for m in patch.modules:
        if m.get("plugin") == "Core" and m.get("model") == "Notes":
            text = (m.get("data") or {}).get("text", "")
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
    return out


def build_record(path: Path, library: Library | None, snapshots_dir: Path, base_dir: Path) -> dict[str, Any]:
    patch = read_vcv(path)
    meta = parse_name(path.name)
    stat = path.stat()
    modules = []
    for m in patch.modules:
        plugin, model = str(m.get("plugin", "?")), str(m.get("model", "?"))
        info = library.find(plugin, model) if library else None
        modules.append(
            {
                "id": m.get("id"),
                "plugin": plugin,
                "model": model,
                "name": info.name if info else model,
                "pos": m.get("pos"),
                "params": len(m.get("params") or []),
            }
        )
    refs = {m["id"]: f"{m['plugin']}/{m['model']}#{m['id']}" for m in modules}
    cables = [
        {
            "from": refs.get(c.get("outputModuleId"), f"?#{c.get('outputModuleId')}"),
            "out": c.get("outputId"),
            "to": refs.get(c.get("inputModuleId"), f"?#{c.get('inputModuleId')}"),
            "in": c.get("inputId"),
            "color": c.get("color"),
        }
        for c in patch.cables
    ]
    bbox = patch.bbox()
    bbox_d = None
    if bbox is not None:
        min_x, min_y, max_x, max_y = bbox
        bbox_d = {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width_hp": max_x - min_x,
            "rows": max_y - min_y + 1,
        }
    snapshot = snapshots_dir / f"{meta['stem']}.png"
    # macOS may add AppleDouble metadata entries (._patch.json) to the tar; they are not real assets.
    assets = [a for a in sorted(patch.assets) if not Path(a).name.startswith("._")]
    return {
        "file": path.name,
        **meta,
        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "size_bytes": stat.st_size,
        "sha1": hashlib.sha1(path.read_bytes()).hexdigest()[:12],
        "rack_version": patch.rack_version,
        "module_count": len(modules),
        "cable_count": len(cables),
        "asset_count": len(assets),
        "assets": assets,
        "plugins": dict(sorted(Counter(m["plugin"] for m in modules).items())),
        "modules": modules,
        "cables": cables,
        "notes": _notes(patch),
        "bbox": bbox_d,
        "snapshot": snapshot.relative_to(base_dir).as_posix() if snapshot.is_file() else None,
    }


def infer_annotation(record: dict[str, Any]) -> dict[str, Any]:
    tokens = [t for t in re.split(r"[_\-]+", record["topic"].lower()) if t]
    titles: list[str] = []
    tags: list[str] = []
    for token in tokens:
        for pattern, title, token_tags in TOPIC_KEYWORDS:
            if re.fullmatch(pattern, token):
                if title and title not in titles:
                    titles.append(title)
                for tag in token_tags:
                    if tag not in tags:
                        tags.append(tag)
                break
    module_slugs = {(m["plugin"], m["model"]) for m in record["modules"]}
    if ("AudibleInstruments", "Resonator") in module_slugs:
        tags.append("rings")
        titles = ["Mutable Rings resonator" if t == "Ring modulation" else t for t in titles]
    if not titles:
        titles = [f"Week {record['week']} example" if record["week"] else (record["topic"] or record["stem"])]
    plugin_list = ", ".join(record["plugins"]) or "none"
    summary = f"{record['module_count']} modules, {record['cable_count']} cables; plugins: {plugin_list}."
    if record["notes"]:
        summary += " Embedded notes: " + " | ".join(n.replace("\n", " ")[:80] for n in record["notes"])
    return {
        "title": " / ".join(titles),
        "summary": summary,
        "tags": tags,
        "teaching_points": [],
        "inferred": True,
    }


def _sort_key(record: dict[str, Any]) -> tuple:
    return (record["week"] is None, record["week"] or 0, record["topic"], record["date"] or "", record["stem"])


# -- rendering --------------------------------------------------------------------


def _date_cell(record: dict[str, Any]) -> str:
    return record["date"] or record["modified"][:10]


def render_index(records: list[dict[str, Any]], annotations: dict[str, Any], dir_name: str, generated: str) -> str:
    out = [
        f"# {dir_name} - VCV Rack patch catalog",
        "",
        f"Generated {generated} by `vcvpatch catalog`. {len(records)} patches.",
        "",
        "## How to use this folder (handoff notes)",
        "",
        "- `*.vcv` are VCV Rack 2 patches: zstd-compressed tar archives (`patch.json` + `modules/`), not plain JSON. "
        "Read them with the `vcvpatch` Python API or `vcvpatch unpack`, never with `json.load`.",
        f"- `{CATALOG_DIR}/{CATALOG_FILE}` is the machine-readable catalog: one record per patch with `week`, `topic`, `date`, "
        "`modules` (plugin/model/name/pos), `cables`, `notes` (text from Core Notes modules), `plugins`, `bbox`, "
        "`snapshot` and the curated `annotation`.",
        f"- `{CATALOG_DIR}/{PAGES_DIR}/<stem>.md` is a one-page summary per patch (snapshot, modules, cables, notes).",
        f"- `{CATALOG_DIR}/{SNAPSHOTS_DIR}/<stem>.png` are screenshots taken in Rack with the whole patch fitted to the window.",
        f"- `{CATALOG_DIR}/{ANNOTATIONS_FILE}` holds curated `title`, `summary`, `tags`, `teaching_points` per patch. "
        "Edit it freely; regeneration never overwrites existing entries. Entries with `\"inferred\": true` were guessed "
        "from the file name and module list and should be checked.",
        "- Regenerate this catalog: `vcvpatch catalog \"<this folder>\"`. "
        "Regenerate screenshots (macOS + Rack): `python scripts/snapshot_rack_macos.py \"<this folder>\"` from the vcvpatch repo.",
        "- File naming: `ICMP_w{week}_ex_{topic}[_{yymmdd}].vcv`; a trailing date marks a revised version of the same example.",
        "",
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        key = f"Week {r['week']}" if r["week"] is not None else "Other (no week in file name)"
        groups.setdefault(key, []).append(r)
    for heading, items in groups.items():
        out += [f"## {heading}", "", "| File | Date | Title | Modules | Cables | Plugins | Snapshot | Details |", "|---|---|---|---|---|---|---|---|"]
        for r in items:
            ann = annotations.get(r["stem"], {})
            title = ann.get("title", "")
            if ann.get("inferred"):
                title += " *(inferred)*"
            snap = f'<img src="{r["snapshot"]}" width="240">' if r["snapshot"] else "-"
            page = f"[page]({CATALOG_DIR}/{PAGES_DIR}/{r['stem']}.md)"
            plugins = ", ".join(r["plugins"])
            out.append(
                f"| `{r['file']}` | {_date_cell(r)} | {title} | {r['module_count']} | {r['cable_count']} | {plugins} | {snap} | {page} |"
            )
        out.append("")
    return "\n".join(out)


def render_patch_page(record: dict[str, Any], annotation: dict[str, Any], generated: str) -> str:
    r = record
    out = [f"# {r['stem']}", "", f"**{annotation.get('title', '')}**" + (" *(title inferred, please verify)*" if annotation.get("inferred") else ""), ""]
    facts = [
        f"File: `{r['file']}`",
        f"Week: {r['week'] if r['week'] is not None else '-'}",
        f"Date in name: {r['date'] or '-'}; last modified: {r['modified']}",
        f"Rack version: {r['rack_version']}; size: {r['size_bytes']} bytes; sha1: {r['sha1']}",
        f"Modules: {r['module_count']}; cables: {r['cable_count']}; assets: {r['asset_count']}",
    ]
    if r["bbox"]:
        b = r["bbox"]
        facts.append(f"Layout: x {b['min_x']}..{b['max_x']} HP, rows {b['min_y']}..{b['max_y']} ({b['width_hp']} HP wide, {b['rows']} rows)")
    out += [f"- {f}" for f in facts] + [""]
    if r["snapshot"]:
        out += [f"![snapshot](../{SNAPSHOTS_DIR}/{r['stem']}.png)", ""]
    if annotation.get("summary"):
        out += ["## Summary", "", annotation["summary"], ""]
    if annotation.get("tags"):
        out += ["Tags: " + ", ".join(f"`{t}`" for t in annotation["tags"]), ""]
    if annotation.get("teaching_points"):
        out += ["## Teaching points", ""] + [f"- {p}" for p in annotation["teaching_points"]] + [""]
    if r["notes"]:
        out += ["## Notes embedded in the patch", ""]
        for note in r["notes"]:
            out += ["> " + line for line in note.splitlines()] + [""]
    out += ["## Modules", "", "| id | plugin/model | name | pos (HP, row) | params |", "|---|---|---|---|---|"]
    for m in sorted(r["modules"], key=lambda m: ((m["pos"] or [0, 0])[1], (m["pos"] or [0, 0])[0])):
        pos = f"{m['pos'][0]}, {m['pos'][1]}" if m["pos"] else "-"
        out.append(f"| {m['id']} | {m['plugin']}/{m['model']} | {m['name']} | {pos} | {m['params']} |")
    out += ["", "## Cables", ""]
    if r["cables"]:
        out += ["| from | out | to | in |", "|---|---|---|---|"]
        out += [f"| {c['from']} | {c['out']} | {c['to']} | {c['in']} |" for c in r["cables"]]
    else:
        out.append("(none)")
    if r["assets"]:
        out += ["", "## Assets", ""] + [f"- `{a}`" for a in r["assets"]]
    out += ["", f"_Generated {generated} by `vcvpatch catalog`._", ""]
    return "\n".join(out)


# -- driver -----------------------------------------------------------------------


def write_catalog(directory: str | os.PathLike[str], library: Library | None = None) -> dict[str, Any]:
    directory = Path(directory)
    cat_dir = directory / CATALOG_DIR
    pages_dir = cat_dir / PAGES_DIR
    snaps_dir = cat_dir / SNAPSHOTS_DIR
    pages_dir.mkdir(parents=True, exist_ok=True)
    snaps_dir.mkdir(exist_ok=True)

    records = [build_record(p, library, snaps_dir, directory) for p in sorted(directory.glob("*.vcv"))]
    records.sort(key=_sort_key)

    ann_path = cat_dir / ANNOTATIONS_FILE
    annotations: dict[str, Any] = json.loads(ann_path.read_text(encoding="utf-8")) if ann_path.is_file() else {}
    added: list[str] = []
    for r in records:
        if r["stem"] not in annotations:
            annotations[r["stem"]] = infer_annotation(r)
            added.append(r["stem"])
    ann_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    catalog = {
        "generated": generated,
        "source_dir": str(directory),
        "count": len(records),
        "patches": [{**r, "annotation": annotations[r["stem"]]} for r in records],
    }
    catalog_path = cat_dir / CATALOG_FILE
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pages = []
    for r in records:
        page = pages_dir / f"{r['stem']}.md"
        page.write_text(render_patch_page(r, annotations[r["stem"]], generated), encoding="utf-8")
        pages.append(page)
    index_path = directory / INDEX_FILE
    index_path.write_text(render_index(records, annotations, directory.name, generated), encoding="utf-8")
    return {
        "count": len(records),
        "index": index_path,
        "catalog": catalog_path,
        "annotations": ann_path,
        "pages": pages,
        "added_annotations": added,
    }
