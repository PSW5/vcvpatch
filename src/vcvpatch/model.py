"""In-memory representation of a VCV Rack patch (the contents of patch.json)."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from .errors import FormatError, ValidationError

DEFAULT_RACK_VERSION = "2.5.2"
CABLE_COLORS = ("#f3374b", "#ffb437", "#00b56e", "#3695ef", "#8b4ade")
DEFAULT_MODULE_WIDTH_HP = 16
ID_BITS = 53  # Rack keeps ids < 2^53 so they survive JSON doubles


@dataclass
class Patch:
    """A patch is the raw patch.json dict plus any module asset files.

    ``raw`` is never re-shaped: unknown keys are preserved so that reading a
    patch and writing it back yields identical JSON content.
    ``assets`` maps archive-relative paths (``modules/<id>/<file>``) to bytes.
    """

    raw: dict[str, Any]
    assets: dict[str, bytes] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def new(cls, rack_version: str = DEFAULT_RACK_VERSION) -> Patch:
        return cls(raw={"version": rack_version, "modules": [], "cables": []})

    @classmethod
    def from_json(cls, text: str, assets: dict[str, bytes] | None = None) -> Patch:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FormatError(f"patch.json is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise FormatError("patch.json must be a JSON object")
        return cls(raw=raw, assets=dict(assets or {}))

    # -- read access --------------------------------------------------------

    @property
    def rack_version(self) -> str | None:
        return self.raw.get("version")

    @property
    def modules(self) -> list[dict[str, Any]]:
        return self._list("modules")

    @property
    def cables(self) -> list[dict[str, Any]]:
        return self._list("cables")

    @property
    def master_module_id(self) -> int | None:
        return self.raw.get("masterModuleId")

    def _list(self, key: str) -> list[dict[str, Any]]:
        value = self.raw.get(key)
        if not isinstance(value, list):
            raise ValidationError(f"patch has no '{key}' list")
        return value

    def get_module(self, module_id: int) -> dict[str, Any] | None:
        return next((m for m in self.modules if m.get("id") == module_id), None)

    def get_cable(self, cable_id: int) -> dict[str, Any] | None:
        return next((c for c in self.cables if c.get("id") == cable_id), None)

    def next_id(self) -> int:
        used = {m.get("id") for m in self.modules} | {c.get("id") for c in self.cables}
        while True:
            candidate = secrets.randbits(ID_BITS)
            if candidate > 0 and candidate not in used:
                return candidate

    # -- editing ------------------------------------------------------------

    def add_module(
        self,
        plugin: str,
        model: str,
        *,
        version: str | None = None,
        pos: list[float] | tuple[float, float] | None = None,
        params: list[dict[str, Any]] | None = None,
        module_id: int | None = None,
    ) -> dict[str, Any]:
        if module_id is None:
            module_id = self.next_id()
        elif self.get_module(module_id) is not None:
            raise ValidationError(f"module id {module_id} already exists")
        if pos is None:
            pos = self._next_free_pos()
        module: dict[str, Any] = {"id": module_id, "plugin": plugin, "model": model}
        if version is not None:
            module["version"] = version
        module["params"] = [dict(p) for p in (params or [])]
        module["pos"] = [int(pos[0]), int(pos[1])]
        self.modules.append(module)
        return module

    def _next_free_pos(self) -> list[int]:
        row0 = [
            m["pos"][0]
            for m in self.modules
            if isinstance(m.get("pos"), list) and len(m["pos"]) == 2 and m["pos"][1] == 0
        ]
        if not row0:
            return [0, 0]
        return [int(max(row0)) + DEFAULT_MODULE_WIDTH_HP, 0]

    def add_cable(
        self,
        output_module_id: int,
        output_id: int,
        input_module_id: int,
        input_id: int,
        *,
        color: str | None = None,
        cable_id: int | None = None,
    ) -> dict[str, Any]:
        for mid in (output_module_id, input_module_id):
            if self.get_module(mid) is None:
                raise ValidationError(f"cable references missing module id {mid}")
        if cable_id is None:
            cable_id = self.next_id()
        elif self.get_cable(cable_id) is not None:
            raise ValidationError(f"cable id {cable_id} already exists")
        if color is None:
            color = CABLE_COLORS[len(self.cables) % len(CABLE_COLORS)]
        cable = {
            "id": cable_id,
            "outputModuleId": output_module_id,
            "outputId": int(output_id),
            "inputModuleId": input_module_id,
            "inputId": int(input_id),
            "color": color,
        }
        self.cables.append(cable)
        return cable

    def remove_module(self, module_id: int) -> None:
        if self.get_module(module_id) is None:
            raise ValidationError(f"module id {module_id} does not exist")
        self.raw["modules"] = [m for m in self.modules if m.get("id") != module_id]
        self.raw["cables"] = [
            c
            for c in self.cables
            if c.get("outputModuleId") != module_id and c.get("inputModuleId") != module_id
        ]
        for m in self.modules:
            for key in ("leftModuleId", "rightModuleId"):
                if m.get(key) == module_id:
                    del m[key]
        if self.raw.get("masterModuleId") == module_id:
            del self.raw["masterModuleId"]
        prefix = f"modules/{module_id}/"
        self.assets = {k: v for k, v in self.assets.items() if not k.startswith(prefix)}

    def remove_cable(self, cable_id: int) -> None:
        if self.get_cable(cable_id) is None:
            raise ValidationError(f"cable id {cable_id} does not exist")
        self.raw["cables"] = [c for c in self.cables if c.get("id") != cable_id]

    def set_param(self, module_id: int, param_id: int, value: float) -> dict[str, Any]:
        module = self.get_module(module_id)
        if module is None:
            raise ValidationError(f"module id {module_id} does not exist")
        params = module.setdefault("params", [])
        for p in params:
            if p.get("id") == param_id:
                p["value"] = value
                return p
        entry = {"id": param_id, "value": value}
        params.append(entry)
        return entry

    def bbox(self) -> tuple[int, int, int, int] | None:
        """(min_x, min_y, max_x, max_y) of module origins in HP/rows, or None if empty."""
        positions = [
            m["pos"]
            for m in self.modules
            if isinstance(m.get("pos"), list) and len(m["pos"]) == 2
        ]
        if not positions:
            return None
        xs = [int(p[0]) for p in positions]
        ys = [int(p[1]) for p in positions]
        return (min(xs), min(ys), max(xs), max(ys))

    # -- serialisation ------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(self.raw, indent=2) + "\n"
