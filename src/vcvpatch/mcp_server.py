"""MCP server exposing .vcv read/write/create/validate and library search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from .archive import read_vcv, write_vcv
from .errors import RackNotFoundError, VcvPatchError
from .library import Library
from .model import DEFAULT_RACK_VERSION, Patch
from .summary import summarize
from .validate import has_errors, validate

INSTRUCTIONS = """\
vcvpatch works on VCV Rack 2 .vcv files on disk (it does not talk to a running Rack).
Typical flow: vcv_library_search to find exact plugin/model slugs -> vcv_create to write a
new patch (ids, plugin versions and positions are filled in) -> open the file in Rack.
To edit an existing patch: vcv_read, modify the returned modules/cables, then vcv_write
with keep_assets_from set to the original path. Positions are [x_in_HP, row]; a typical
module is 8-16 HP wide. Parameter values are raw knob values, not musical units.
"""

server = MCPServer("vcvpatch", instructions=INSTRUCTIONS)

_HANDLED = (VcvPatchError, OSError, ValueError, TypeError, KeyError)


class ParamSpec(BaseModel):
    id: int = Field(description="parameter index within the module")
    value: float = Field(description="raw parameter value")


class ModuleSpec(BaseModel):
    plugin: str = Field(description="plugin slug, e.g. 'Fundamental' or 'Core'")
    model: str = Field(description="module slug, e.g. 'VCO' or 'AudioInterface2'")
    pos: list[int] | None = Field(
        default=None, description="[x in HP, row]; auto-placed left to right on row 0 if omitted"
    )
    params: list[ParamSpec] | None = Field(default=None, description="initial parameter values")


class CableSpec(BaseModel):
    from_module: int = Field(description="index into the modules list (source)")
    output_id: int = Field(description="output port index on the source module")
    to_module: int = Field(description="index into the modules list (destination)")
    input_id: int = Field(description="input port index on the destination module")
    color: str | None = Field(
        default=None, description="hex color like '#f3374b'; cycles Rack defaults if omitted"
    )


def _error(exc: BaseException | str) -> dict[str, Any]:
    return {"ok": False, "error": str(exc)}


def _library_or_none() -> Library | None:
    try:
        return Library.scan()
    except RackNotFoundError:
        return None


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _write_checked(
    patch: Patch, path: Path, overwrite: bool, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    issues = validate(patch, _library_or_none())
    issue_dicts = [i.as_dict() for i in issues]
    if has_errors(issues):
        return {"ok": False, "error": "validation failed", "issues": issue_dicts}
    write_vcv(patch, path, overwrite=overwrite)
    return {"ok": True, "path": str(path), "issues": issue_dicts, **(extra or {})}


@server.tool(
    name="vcv_read",
    description="Read a .vcv file: Rack version, modules, cables, asset list and a text summary.",
)
def vcv_read(path: str) -> dict[str, Any]:
    try:
        patch = read_vcv(_path(path))
        return {
            "ok": True,
            "path": str(_path(path)),
            "rack_version": patch.rack_version,
            "modules": patch.modules,
            "cables": patch.cables,
            "master_module_id": patch.master_module_id,
            "assets": sorted(patch.assets),
            "summary": summarize(patch, _library_or_none()),
        }
    except _HANDLED as exc:
        return _error(exc)


@server.tool(
    name="vcv_write",
    description=(
        "Write a full patch.json dict to a .vcv file. Validates first; refuses to overwrite unless "
        "overwrite=true. Pass keep_assets_from=<original .vcv> when saving an edited copy so module "
        "asset files are preserved."
    ),
)
def vcv_write(
    path: str,
    patch: dict[str, Any],
    overwrite: bool = False,
    keep_assets_from: str | None = None,
) -> dict[str, Any]:
    try:
        obj = Patch(raw=patch)
        if keep_assets_from:
            obj.assets = read_vcv(_path(keep_assets_from)).assets
        return _write_checked(obj, _path(path), overwrite)
    except _HANDLED as exc:
        return _error(exc)


@server.tool(
    name="vcv_create",
    description=(
        "Create a new .vcv file from a list of modules and cables. Module ids, plugin versions and "
        "positions are filled in automatically. Cables reference modules by their index in the "
        "modules list."
    ),
)
def vcv_create(
    path: str,
    modules: list[ModuleSpec],
    cables: list[CableSpec] | None = None,
    overwrite: bool = False,
    rack_version: str = DEFAULT_RACK_VERSION,
) -> dict[str, Any]:
    try:
        library = _library_or_none()
        patch = Patch.new(rack_version)
        ids: list[int] = []
        for spec in modules:
            if spec.plugin == "Core":
                version: str | None = rack_version
            else:
                version = library.plugin_version(spec.plugin) if library else None
            params = [{"id": p.id, "value": p.value} for p in (spec.params or [])]
            module = patch.add_module(
                spec.plugin, spec.model, version=version, pos=spec.pos, params=params
            )
            ids.append(module["id"])
        for cable in cables or []:
            if not (0 <= cable.from_module < len(ids)) or not (0 <= cable.to_module < len(ids)):
                return _error(f"cable module index out of range (0..{len(ids) - 1})")
            patch.add_cable(
                ids[cable.from_module],
                cable.output_id,
                ids[cable.to_module],
                cable.input_id,
                color=cable.color,
            )
        return _write_checked(patch, _path(path), overwrite, {"module_ids": ids})
    except _HANDLED as exc:
        return _error(exc)


@server.tool(
    name="vcv_validate",
    description="Check a .vcv file for structural problems and missing plugins.",
)
def vcv_validate(path: str) -> dict[str, Any]:
    try:
        issues = validate(read_vcv(_path(path)), _library_or_none())
        return {"ok": True, "valid": not has_errors(issues), "issues": [i.as_dict() for i in issues]}
    except _HANDLED as exc:
        return _error(exc)


@server.tool(
    name="vcv_library_search",
    description=(
        "Search modules installed in the local Rack library by free text and/or tags. "
        "Returns exact plugin/model slugs to use in vcv_create."
    ),
)
def vcv_library_search(
    query: str = "", tags: list[str] | None = None, limit: int = 50
) -> dict[str, Any]:
    try:
        library = Library.scan()
        results = library.search(query, tags=tags, limit=limit)
        return {
            "ok": True,
            "count": len(results),
            "results": [m.as_dict() for m in results],
            "warnings": library.warnings,
        }
    except _HANDLED as exc:
        return _error(exc)


def run() -> None:
    server.run(transport="stdio")
