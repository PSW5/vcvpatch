"""Human-readable summaries of a patch."""

from __future__ import annotations

from typing import Any

from .library import Library
from .model import Patch


def _safe_list(patch: Patch, key: str) -> list[Any]:
    value = patch.raw.get(key)
    return value if isinstance(value, list) else []


def _module_rows(patch: Patch, library: Library | None) -> list[dict[str, Any]]:
    rows = []
    for m in _safe_list(patch, "modules"):
        if not isinstance(m, dict):
            continue
        raw_pos = m.get("pos")
        pos = raw_pos if isinstance(raw_pos, list) and len(raw_pos) == 2 else [0, 0]
        plugin, model, module_id = m.get("plugin", "?"), m.get("model", "?"), m.get("id", "?")
        info = library.find(plugin, model) if library else None
        prefix = f"modules/{module_id}/"
        rows.append(
            {
                "id": module_id,
                "ref": f"{plugin}/{model}",
                "name": info.name if info else "",
                "pos": pos,
                "params": len(m.get("params") or []),
                "assets": sum(1 for a in patch.assets if a.startswith(prefix)),
            }
        )
    rows.sort(key=lambda r: (r["pos"][1], r["pos"][0]))
    return rows


def _cable_rows(patch: Patch) -> list[str]:
    refs = {
        m.get("id"): f"{m.get('plugin', '?')}/{m.get('model', '?')}#{m.get('id')}"
        for m in _safe_list(patch, "modules")
        if isinstance(m, dict)
    }
    lines = []
    for c in _safe_list(patch, "cables"):
        if not isinstance(c, dict):
            continue
        src = refs.get(c.get("outputModuleId"), f"?#{c.get('outputModuleId')}")
        dst = refs.get(c.get("inputModuleId"), f"?#{c.get('inputModuleId')}")
        lines.append(f"{src} out[{c.get('outputId')}] -> {dst} in[{c.get('inputId')}]")
    return lines


def summarize(patch: Patch, library: Library | None = None, fmt: str = "text") -> str:
    if fmt not in ("text", "markdown"):
        raise ValueError(f"unknown summary format {fmt!r} (use 'text' or 'markdown')")
    rows = _module_rows(patch, library)
    cables = _cable_rows(patch)
    header = f"Rack {patch.rack_version or '?'} patch: {len(rows)} modules, {len(cables)} cables"

    if fmt == "markdown":
        out = [
            f"# {header}",
            "",
            "## Modules",
            "",
            "| id | module | name | pos | params | assets |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            out.append(
                f"| {r['id']} | {r['ref']} | {r['name']} | {r['pos'][0]},{r['pos'][1]} | {r['params']} | {r['assets']} |"
            )
        out += ["", "## Cables", ""]
        out += [f"- {line}" for line in cables] or ["(none)"]
        return "\n".join(out) + "\n"

    out = [header, "", "Modules (row, x):"]
    for r in rows:
        extra = f"  {r['assets']} asset{'s' if r['assets'] != 1 else ''}" if r["assets"] else ""
        name = f"  {r['name']}" if r["name"] else ""
        out.append(f"  {r['id']} {r['ref']}{name}  pos={r['pos'][0]},{r['pos'][1]}  params={r['params']}{extra}")
    out += ["", "Cables:"]
    out += [f"  {line}" for line in cables] or ["  (none)"]
    return "\n".join(out) + "\n"
