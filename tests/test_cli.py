import json
from pathlib import Path

import pytest

from vcvpatch.archive import read_vcv, write_vcv
from vcvpatch.cli import main
from vcvpatch.model import Patch


@pytest.fixture
def vcv_file(tmp_path: Path, raw) -> Path:
    return write_vcv(Patch(raw=raw, assets={"modules/2/IR.wav": b"wav"}), tmp_path / "in.vcv")


def test_unpack_pack_cycle(tmp_path: Path, vcv_file: Path, raw, capsys):
    out_dir = tmp_path / "out"
    assert main(["unpack", str(vcv_file), "-o", str(out_dir)]) == 0
    assert json.loads((out_dir / "patch.json").read_text()) == raw
    assert "unpacked" in capsys.readouterr().out
    target = tmp_path / "re.vcv"
    assert main(["pack", str(out_dir), "-o", str(target)]) == 0
    assert read_vcv(target).assets == {"modules/2/IR.wav": b"wav"}
    assert main(["pack", str(out_dir), "-o", str(target)]) == 2
    assert "exists" in capsys.readouterr().err
    assert main(["pack", str(out_dir), "-o", str(target), "--force"]) == 0


def test_unpack_default_output_dir(tmp_path: Path, vcv_file: Path):
    assert main(["unpack", str(vcv_file)]) == 0
    assert (tmp_path / "in" / "patch.json").is_file()


def test_info_text_json_markdown(vcv_file: Path, raw, capsys, fake_rack_env):
    assert main(["info", str(vcv_file)]) == 0
    out = capsys.readouterr().out
    assert "3 modules, 2 cables" in out and "Audio 2" in out
    assert main(["info", str(vcv_file), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == raw
    assert main(["info", str(vcv_file), "--markdown"]) == 0
    assert capsys.readouterr().out.startswith("# Rack 2.5.2")


def test_validate_exit_codes(tmp_path: Path, vcv_file: Path, raw, capsys, fake_rack_env):
    assert main(["validate", str(vcv_file)]) == 0
    assert "no issues" in capsys.readouterr().out
    raw["modules"].append({"id": 9, "plugin": "Nope", "model": "X"})
    bad = write_vcv(Patch(raw=raw), tmp_path / "bad.vcv")
    assert main(["validate", str(bad)]) == 1
    assert "plugin 'Nope' is not installed" in capsys.readouterr().out
    assert main(["validate", str(bad), "--no-library"]) == 0


def test_validate_without_rack_warns_but_runs(tmp_path: Path, vcv_file: Path, capsys, monkeypatch):
    monkeypatch.setenv("RACK_USER_DIR", str(tmp_path / "nowhere"))
    assert main(["validate", str(vcv_file)]) == 0
    assert "Rack user directory not found" in capsys.readouterr().err


def test_library_command(capsys, fake_rack_env):
    assert main(["library", "oscillator"]) == 0
    out = capsys.readouterr().out
    assert "Fundamental/VCO" in out and "Fundamental/LFO" in out and "VCF" not in out
    assert main(["library", "--tags", "Polyphonic", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {d["model"] for d in data} == {"VCO", "VCF", "VCA"}


def test_errors_go_to_stderr_with_code_2(tmp_path: Path, capsys):
    assert main(["info", str(tmp_path / "missing.vcv")]) == 2
    assert "error:" in capsys.readouterr().err


def test_no_command_prints_usage(capsys):
    assert main([]) == 2
    captured = capsys.readouterr()
    assert "usage" in (captured.err + captured.out).lower()
