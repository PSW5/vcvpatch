"""Structural and library checks for a patch. Pure functions, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from .library import Library
from .model import Patch

Severity = Literal["error", "warning"]

MODULE_REQUIRED = ("id", "plugin", "model")
CABLE_REQUIRED = ("id", "outputModuleId", "outputId", "inputModuleId", "inputId")


@dataclass(frozen=True)
class Issue:
    severity: Severity
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: {self.where}: {self.message}"

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "where": self.where, "message": self.message}


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def validate(patch: Patch, library: Library | None = None) -> list[Issue]:
    issues: list[Issue] = []

    def error(where: str, message: str) -> None:
        issues.append(Issue("error", where, message))

    def warning(where: str, message: str) -> None:
        issues.append(Issue("warning", where, message))

    raw = patch.raw
    modules = raw.get("modules")
    cables = raw.get("cables")
    if not isinstance(modules, list):
        error("patch", "'modules' must be a list")
        modules = []
    if not isinstance(cables, list):
        error("patch", "'cables' must be a list")
        cables = []

    by_id: dict[Any, dict[str, Any]] = {}
    for index, module in enumerate(modules):
        where = f"modules[{index}]"
        if not isinstance(module, dict):
            error(where, "module must be an object")
            continue
        missing = [k for k in MODULE_REQUIRED if k not in module]
        if missing:
            error(where, f"missing {', '.join(missing)}")
            continue
        module_id = module["id"]
        if module_id in by_id:
            error(where, f"duplicate module id {module_id}")
        else:
            by_id[module_id] = module
        if library is not None:
            _check_installed(module, where, library, error, warning)

    for module in by_id.values():
        where = f"module {module['id']}"
        for key, inverse in (("leftModuleId", "rightModuleId"), ("rightModuleId", "leftModuleId")):
            neighbour_id = module.get(key)
            if neighbour_id is None:
                continue
            neighbour = by_id.get(neighbour_id)
            if neighbour is None:
                warning(where, f"{key} {neighbour_id} does not exist")
            elif neighbour.get(inverse) != module["id"]:
                warning(where, f"{key} {neighbour_id} does not point back via {inverse}")

    master = raw.get("masterModuleId")
    if master is not None and master not in by_id:
        warning("patch", f"masterModuleId {master} does not exist")

    cable_ids: set[Any] = set()
    for index, cable in enumerate(cables):
        where = f"cables[{index}]"
        if not isinstance(cable, dict):
            error(where, "cable must be an object")
            continue
        missing = [k for k in CABLE_REQUIRED if k not in cable]
        if missing:
            error(where, f"missing {', '.join(missing)}")
            continue
        if cable["id"] in cable_ids:
            error(where, f"duplicate cable id {cable['id']}")
        cable_ids.add(cable["id"])
        for key in ("outputModuleId", "inputModuleId"):
            if cable[key] not in by_id:
                error(where, f"{key} {cable[key]} does not exist")
        for key in ("outputId", "inputId"):
            value = cable[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                error(where, f"{key} must be a non-negative integer")
    return issues


def _check_installed(
    module: dict[str, Any],
    where: str,
    library: Library,
    error: Callable[[str, str], None],
    warning: Callable[[str, str], None],
) -> None:
    plugin_slug = module["plugin"]
    plugin = library.plugin(plugin_slug)
    if plugin is None:
        error(where, f"plugin '{plugin_slug}' is not installed")
        return
    if library.find(plugin_slug, module["model"]) is None:
        error(where, f"plugin '{plugin_slug}' has no module '{module['model']}'")
        return
    declared = module.get("version")
    if plugin.version and declared and declared != plugin.version:
        warning(where, f"module version {declared} differs from installed {plugin.version}")
