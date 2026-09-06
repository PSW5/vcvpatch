"""vcvpatch - read, write, inspect and validate VCV Rack 2 .vcv patch files."""

from .archive import pack_path, read_vcv, unpack_vcv, write_vcv
from .catalog import fit_view, parse_name, write_catalog
from .errors import FormatError, RackNotFoundError, ValidationError, VcvPatchError
from .library import Library, ModuleInfo, PluginInfo, plugins_dir, rack_user_dir
from .model import CABLE_COLORS, DEFAULT_RACK_VERSION, Patch
from .summary import summarize
from .validate import Issue, has_errors, validate

__version__ = "0.1.0"

__all__ = [
    "CABLE_COLORS",
    "DEFAULT_RACK_VERSION",
    "FormatError",
    "Issue",
    "Library",
    "ModuleInfo",
    "Patch",
    "PluginInfo",
    "RackNotFoundError",
    "ValidationError",
    "VcvPatchError",
    "__version__",
    "fit_view",
    "has_errors",
    "pack_path",
    "parse_name",
    "plugins_dir",
    "rack_user_dir",
    "read_vcv",
    "summarize",
    "unpack_vcv",
    "validate",
    "write_catalog",
    "write_vcv",
]
