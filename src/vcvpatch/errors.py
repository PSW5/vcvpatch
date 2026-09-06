"""Exception hierarchy for vcvpatch."""


class VcvPatchError(Exception):
    """Base class for all vcvpatch errors."""


class FormatError(VcvPatchError):
    """The file is not a VCV Rack patch, or its contents are malformed."""


class RackNotFoundError(VcvPatchError):
    """The Rack user directory or plugins directory could not be located."""


class ValidationError(VcvPatchError):
    """A patch edit or write was rejected because the structure is invalid."""
