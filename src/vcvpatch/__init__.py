"""vcvpatch - read, write, inspect and validate VCV Rack 2 .vcv patch files."""

from .archive import pack_path, read_vcv, unpack_vcv, write_vcv
from .errors import FormatError, RackNotFoundError, ValidationError, VcvPatchError
from .model import CABLE_COLORS, DEFAULT_RACK_VERSION, Patch

__version__ = "0.1.0"

__all__ = [
    "CABLE_COLORS",
    "DEFAULT_RACK_VERSION",
    "FormatError",
    "Patch",
    "RackNotFoundError",
    "ValidationError",
    "VcvPatchError",
    "__version__",
    "pack_path",
    "read_vcv",
    "unpack_vcv",
    "write_vcv",
]
