import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vcvpatch.archive import ZSTD_MAGIC, pack_path, read_vcv, unpack_vcv, write_vcv
from vcvpatch.errors import FormatError, ValidationError
from vcvpatch.model import Patch


def test_write_then_read_round_trips_raw_and_assets(tmp_path: Path, raw):
    assets = {"modules/2/IR.wav": b"RIFF\x00\x01\x02", "modules/2/notes.txt": b"hello"}
    patch = Patch(raw=copy.deepcopy(raw), assets=assets)
    out = write_vcv(patch, tmp_path / "a.vcv")
    assert out.read_bytes()[:4] == ZSTD_MAGIC
    back = read_vcv(out)
    assert back.raw == raw
    assert back.assets == assets


def test_write_refuses_overwrite_unless_asked(tmp_path: Path, raw):
    target = tmp_path / "a.vcv"
    write_vcv(Patch(raw=raw), target)
    with pytest.raises(FileExistsError):
        write_vcv(Patch(raw=raw), target)
    write_vcv(Patch(raw={"version": "2.5.2", "modules": [], "cables": []}), target, overwrite=True)
    assert read_vcv(target).modules == []
    assert not list(tmp_path.glob("*.tmp"))


def test_write_rejects_patch_without_lists(tmp_path: Path):
    with pytest.raises(ValidationError):
        write_vcv(Patch(raw={"version": "2.5.2"}), tmp_path / "bad.vcv")


def test_read_rack1_plain_json(tmp_path: Path):
    raw = {"version": "1.1.6", "modules": [], "cables": []}
    f = tmp_path / "old.vcv"
    f.write_text(json.dumps(raw), encoding="utf-8")
    p = read_vcv(f)
    assert p.raw == raw
    assert p.assets == {}


def test_read_rejects_garbage_and_missing(tmp_path: Path):
    f = tmp_path / "x.vcv"
    f.write_bytes(b"\x00\x01\x02\x03 not a patch")
    with pytest.raises(FormatError):
        read_vcv(f)
    with pytest.raises(FormatError):
        read_vcv(tmp_path / "missing.vcv")


def test_read_rejects_archive_without_patch_json(tmp_path: Path):
    import io
    import tarfile

    import zstandard

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("./readme.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    f = tmp_path / "nopatch.vcv"
    f.write_bytes(zstandard.ZstdCompressor().compress(buf.getvalue()))
    with pytest.raises(FormatError):
        read_vcv(f)


def test_unpack_and_pack_directory(tmp_path: Path, raw):
    assets = {"modules/2/IR.wav": b"wav"}
    src = write_vcv(Patch(raw=raw, assets=assets), tmp_path / "src.vcv")
    out_dir = unpack_vcv(src, tmp_path / "unpacked")
    assert json.loads((out_dir / "patch.json").read_text()) == raw
    assert (out_dir / "modules" / "2" / "IR.wav").read_bytes() == b"wav"
    repacked = pack_path(out_dir, tmp_path / "repacked.vcv")
    back = read_vcv(repacked)
    assert back.raw == raw and back.assets == assets


def test_pack_single_json_file(tmp_path: Path, raw):
    j = tmp_path / "patch.json"
    j.write_text(json.dumps(raw), encoding="utf-8")
    out = pack_path(j, tmp_path / "from_json.vcv")
    assert read_vcv(out).raw == raw
    with pytest.raises(FormatError):
        pack_path(tmp_path / "nope.bin", tmp_path / "x.vcv")


def test_read_directory_without_patch_json_fails(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FormatError):
        read_vcv(tmp_path / "empty")


@pytest.mark.skipif(not (shutil.which("zstd") and shutil.which("tar")), reason="needs zstd and tar CLIs")
def test_external_tools_can_unpack_our_output(tmp_path: Path, raw):
    assets = {"modules/2/IR.wav": b"wav-bytes"}
    f = write_vcv(Patch(raw=raw, assets=assets), tmp_path / "ext.vcv")
    out = tmp_path / "ext"
    out.mkdir()
    tar_bytes = subprocess.run(["zstd", "-dc", str(f)], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-xf", "-", "-C", str(out)], input=tar_bytes, check=True)
    assert json.loads((out / "patch.json").read_text()) == raw
    assert (out / "modules" / "2" / "IR.wav").read_bytes() == b"wav-bytes"
