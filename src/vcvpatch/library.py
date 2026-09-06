"""Locate the Rack user directory and index the installed plugin library."""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .errors import RackNotFoundError


@dataclass(frozen=True)
class ModuleInfo:
    plugin: str
    slug: str
    name: str
    description: str
    tags: tuple[str, ...]
    plugin_version: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin,
            "model": self.slug,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "plugin_version": self.plugin_version,
        }


@dataclass
class PluginInfo:
    slug: str
    name: str
    version: str | None
    brand: str
    modules: list[ModuleInfo] = field(default_factory=list)


# Slugs from Core.json shipped inside the Rack application bundle.
CORE_MODULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("AudioInterface2", "Audio 2", "Audio interface with 2 inputs and 2 outputs", ("External",)),
    ("AudioInterface", "Audio 8", "Audio interface with 8 inputs and 8 outputs", ("External",)),
    ("AudioInterface16", "Audio 16", "Audio interface with 16 inputs and 16 outputs", ("External",)),
    ("MIDIToCVInterface", "MIDI to CV", "Converts MIDI notes to V/oct, gate and velocity", ("External", "MIDI")),
    ("MIDICCToCVInterface", "MIDI CC to CV", "Converts MIDI CC messages to CV", ("External", "MIDI")),
    ("MIDITriggerToCVInterface", "MIDI Gate to CV", "Converts MIDI notes to gates", ("External", "MIDI")),
    ("MIDI-Map", "MIDI Map", "Maps MIDI CC to module parameters", ("External", "MIDI")),
    ("CV-MIDI", "CV to MIDI", "Converts V/oct and gate to MIDI notes", ("External", "MIDI")),
    ("CV-CC", "CV to MIDI CC", "Converts CV to MIDI CC messages", ("External", "MIDI")),
    ("CV-Gate", "CV to MIDI Gate", "Converts gates to MIDI notes", ("External", "MIDI")),
    ("Blank", "Blank", "Resizable blank panel", ("Blank",)),
    ("Notes", "Notes", "Text notes", ("Utility",)),
)


def core_plugin() -> PluginInfo:
    modules = [
        ModuleInfo("Core", slug, name, description, tags, None)
        for slug, name, description, tags in CORE_MODULES
    ]
    return PluginInfo(slug="Core", name="VCV Core", version=None, brand="VCV", modules=modules)


def rack_user_dir() -> Path:
    env = os.environ.get("RACK_USER_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Rack2"
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "Rack2"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "Rack2"


def _platform_suffix() -> str:
    if sys.platform == "darwin":
        os_name = "mac"
    elif sys.platform.startswith("win"):
        os_name = "win"
    else:
        os_name = "lin"
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return f"{os_name}-{arch}"


def plugins_dir(user_dir: str | os.PathLike[str] | None = None) -> Path:
    base = Path(user_dir) if user_dir is not None else rack_user_dir()
    if not base.is_dir():
        raise RackNotFoundError(f"Rack user directory not found: {base} (set RACK_USER_DIR to override)")
    preferred = base / f"plugins-{_platform_suffix()}"
    if preferred.is_dir():
        return preferred
    for candidate in sorted(base.glob("plugins-*")):
        if candidate.is_dir():
            return candidate
    raise RackNotFoundError(f"no plugins-* directory inside {base}")


def _plugin_from_json(data: dict[str, Any], fallback_slug: str) -> PluginInfo:
    slug = str(data.get("slug") or fallback_slug)
    version = data.get("version")
    plugin = PluginInfo(
        slug=slug,
        name=str(data.get("name") or slug),
        version=str(version) if version is not None else None,
        brand=str(data.get("brand") or data.get("author") or ""),
    )
    for entry in data.get("modules") or []:
        if not isinstance(entry, dict) or "slug" not in entry:
            continue
        tags = entry.get("tags") or []
        plugin.modules.append(
            ModuleInfo(
                plugin=slug,
                slug=str(entry["slug"]),
                name=str(entry.get("name") or entry["slug"]),
                description=str(entry.get("description") or ""),
                tags=tuple(str(t) for t in tags),
                plugin_version=plugin.version,
            )
        )
    return plugin


class Library:
    """An index of installed plugins and their modules."""

    def __init__(self, plugins: list[PluginInfo], warnings: list[str] | None = None) -> None:
        self._plugins = {p.slug: p for p in plugins}
        self.warnings = list(warnings or [])

    @classmethod
    def scan(
        cls,
        plugins_directory: str | os.PathLike[str] | None = None,
        *,
        include_core: bool = True,
    ) -> Library:
        directory = Path(plugins_directory) if plugins_directory is not None else plugins_dir()
        plugins: list[PluginInfo] = [core_plugin()] if include_core else []
        warnings: list[str] = []
        for manifest in sorted(directory.glob("*/plugin.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("plugin.json is not an object")
                plugins.append(_plugin_from_json(data, fallback_slug=manifest.parent.name))
            except (OSError, ValueError) as exc:
                warnings.append(f"{manifest}: {exc}")
        return cls(plugins, warnings)

    @property
    def plugins(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    def modules(self) -> Iterator[ModuleInfo]:
        for plugin in self._plugins.values():
            yield from plugin.modules

    def plugin(self, slug: str) -> PluginInfo | None:
        return self._plugins.get(slug)

    def plugin_version(self, slug: str) -> str | None:
        plugin = self._plugins.get(slug)
        return plugin.version if plugin else None

    def find(self, plugin_slug: str, model_slug: str) -> ModuleInfo | None:
        plugin = self._plugins.get(plugin_slug)
        if plugin is None:
            return None
        return next((m for m in plugin.modules if m.slug == model_slug), None)

    def search(
        self,
        query: str = "",
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[ModuleInfo]:
        tokens = [t for t in query.lower().split() if t]
        wanted_tags = {t.lower() for t in (tags or [])}
        results: list[ModuleInfo] = []
        for module in self.modules():
            haystack = f"{module.plugin} {module.slug} {module.name} {module.description}".lower()
            if not all(token in haystack for token in tokens):
                continue
            if wanted_tags and not wanted_tags <= {t.lower() for t in module.tags}:
                continue
            results.append(module)
            if limit is not None and len(results) >= limit:
                break
        return results
