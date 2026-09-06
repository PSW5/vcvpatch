"""vcvpatch - read, write, inspect and validate VCV Rack 2 .vcv patch files."""

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
]
