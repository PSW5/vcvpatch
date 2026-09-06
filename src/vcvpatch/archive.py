"""Read and write VCV Rack 2 .vcv files (a zstd-compressed ustar archive)."""

from __future__ import annotations

import contextlib
import io
import os
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

import zstandard

from .errors import FormatError, ValidationError
from .model import Patch

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
PATCH_JSON = "patch.json"
MODULES_DIR = "modules"


# -- low level helpers --------------------------------------------------------


def _decompress(data: bytes) -> bytes:
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as reader:
        return reader.read()


def _compress(data: bytes) -> bytes:
    return zstandard.ZstdCompressor(level=3).compress(data)


def _normalize_member_name(name: str) -> str:
    """'./modules/1/a.wav' -> 'modules/1/a.wav'; rejects unsafe names."""
    posix = PurePosixPath(name)
    parts = [p for p in posix.parts if p not in ("", ".", "/")]
    if any(p == ".." for p in parts) or posix.is_absolute():
        raise FormatError(f"unsafe path inside archive: {name!r}")
    return "/".join(parts)


def _read_tar(data: bytes) -> tuple[str, dict[str, bytes]]:
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError as exc:
        raise FormatError(f"decompressed data is not a tar archive: {exc}") from exc
    patch_text: str | None = None
    assets: dict[str, bytes] = {}
    with tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = _normalize_member_name(member.name)
            handle = tar.extractfile(member)
            payload = handle.read() if handle else b""
            if name == PATCH_JSON:
                patch_text = payload.decode("utf-8")
            else:
                assets[name] = payload
    if patch_text is None:
        raise FormatError(f"archive contains no {PATCH_JSON}")
    return patch_text, assets


def _build_tar(patch: Patch) -> bytes:
    buf = io.BytesIO()
    now = int(time.time())

    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:

        def add_dir(name: str) -> None:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.mtime = now
            tar.addfile(info)

        def add_file(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = now
            tar.addfile(info, io.BytesIO(data))

        add_dir("./")
        add_file(f"./{PATCH_JSON}", patch.to_json().encode("utf-8"))
        add_dir(f"./{MODULES_DIR}/")
        seen_dirs = {f"{MODULES_DIR}/"}
        for name in sorted(patch.assets):
            parts = name.split("/")
            for depth in range(1, len(parts)):
                directory = "/".join(parts[:depth]) + "/"
                if directory not in seen_dirs:
                    seen_dirs.add(directory)
                    add_dir(f"./{directory}")
            add_file(f"./{name}", patch.assets[name])
    return buf.getvalue()


# -- public API ---------------------------------------------------------------


def read_vcv(path: str | os.PathLike[str]) -> Patch:
    """Read a .vcv file (Rack 2 archive or Rack 1 JSON) or an unpacked directory."""
    path = Path(path)
    if path.is_dir():
        return _read_dir(path)
    if not path.is_file():
        raise FormatError(f"{path}: no such file")
    data = path.read_bytes()
    if data[:4] == ZSTD_MAGIC:
        try:
            tar_bytes = _decompress(data)
        except zstandard.ZstdError as exc:
            raise FormatError(f"{path}: zstd decompression failed: {exc}") from exc
        text, assets = _read_tar(tar_bytes)
        return Patch.from_json(text, assets)
    if data.lstrip()[:1] == b"{":
        try:
            return Patch.from_json(data.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise FormatError(f"{path}: not UTF-8 JSON: {exc}") from exc
    raise FormatError(f"{path}: not a VCV Rack patch (neither zstd archive nor JSON)")


def _read_dir(directory: Path) -> Patch:
    patch_json = directory / PATCH_JSON
    if not patch_json.is_file():
        raise FormatError(f"{directory}: no {PATCH_JSON} in directory")
    assets: dict[str, bytes] = {}
    for file in sorted(directory.rglob("*")):
        if file.is_file() and file != patch_json:
            assets[file.relative_to(directory).as_posix()] = file.read_bytes()
    return Patch.from_json(patch_json.read_text(encoding="utf-8"), assets)


def write_vcv(patch: Patch, path: str | os.PathLike[str], *, overwrite: bool = False) -> Path:
    """Write ``patch`` as a Rack 2 .vcv archive. Atomic: temp file + rename."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists (pass overwrite=True to replace it)")
    if not isinstance(patch.raw.get("modules"), list) or not isinstance(patch.raw.get("cables"), list):
        raise ValidationError("patch must have 'modules' and 'cables' lists")
    payload = _compress(_build_tar(patch))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return path


def unpack_vcv(path: str | os.PathLike[str], out_dir: str | os.PathLike[str]) -> Path:
    """Extract a .vcv file into ``out_dir`` (patch.json + modules/...)."""
    patch = read_vcv(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PATCH_JSON).write_text(patch.to_json(), encoding="utf-8")
    (out_dir / MODULES_DIR).mkdir(exist_ok=True)
    for name, data in patch.assets.items():
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return out_dir


def pack_path(src: str | os.PathLike[str], dest: str | os.PathLike[str], *, overwrite: bool = False) -> Path:
    """Pack an unpacked directory (or a bare patch .json file) into a .vcv file."""
    src = Path(src)
    if src.is_dir():
        patch = read_vcv(src)
    elif src.is_file() and src.suffix.lower() == ".json":
        patch = Patch.from_json(src.read_text(encoding="utf-8"))
    else:
        raise FormatError(f"{src}: expected a directory containing {PATCH_JSON} or a .json file")
    return write_vcv(patch, dest, overwrite=overwrite)
