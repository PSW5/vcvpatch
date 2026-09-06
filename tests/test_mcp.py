import asyncio
from pathlib import Path

import pytest

from vcvpatch.archive import read_vcv, write_vcv
from vcvpatch.mcp_server import (
    CableSpec,
    ModuleSpec,
    ParamSpec,
    server,
    vcv_create,
    vcv_library_search,
    vcv_read,
    vcv_validate,
    vcv_write,
)
from vcvpatch.model import Patch


@pytest.fixture
def vcv_file(tmp_path: Path, raw) -> Path:
    return write_vcv(Patch(raw=raw, assets={"modules/2/IR.wav": b"wav"}), tmp_path / "in.vcv")


def test_server_registers_five_tools():
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"vcv_read", "vcv_write", "vcv_create", "vcv_validate", "vcv_library_search"}


def test_read(vcv_file: Path, raw, fake_rack_env):
    result = vcv_read(str(vcv_file))
    assert result["ok"] is True
    assert result["rack_version"] == "2.5.2"
    assert result["modules"] == raw["modules"]
    assert result["cables"] == raw["cables"]
    assert result["master_module_id"] == 3
    assert result["assets"] == ["modules/2/IR.wav"]
    assert "3 modules, 2 cables" in result["summary"]


def test_read_error_is_structured(tmp_path: Path):
    result = vcv_read(str(tmp_path / "missing.vcv"))
    assert result["ok"] is False and "no such file" in result["error"]


def test_write_validates_and_keeps_assets(tmp_path: Path, vcv_file: Path, raw, fake_rack_env):
    target = tmp_path / "out.vcv"
    result = vcv_write(str(target), raw, keep_assets_from=str(vcv_file))
    assert result["ok"] is True and result["issues"] == []
    back = read_vcv(target)
    assert back.raw == raw and back.assets == {"modules/2/IR.wav": b"wav"}

    again = vcv_write(str(target), raw)
    assert again["ok"] is False and "exists" in again["error"]

    raw["modules"].append({"id": 9, "plugin": "Nope", "model": "X"})
    bad = vcv_write(str(tmp_path / "bad.vcv"), raw)
    assert bad["ok"] is False and bad["error"] == "validation failed"
    assert any("Nope" in i["message"] for i in bad["issues"])
    assert not (tmp_path / "bad.vcv").exists()


def test_create_assigns_ids_versions_positions(tmp_path: Path, fake_rack_env):
    target = tmp_path / "new.vcv"
    result = vcv_create(
        str(target),
        modules=[
            ModuleSpec(plugin="Fundamental", model="VCO", params=[ParamSpec(id=1, value=0.5)]),
            ModuleSpec(plugin="Fundamental", model="VCF"),
            ModuleSpec(plugin="Core", model="AudioInterface2", pos=[40, 0]),
        ],
        cables=[
            CableSpec(from_module=0, output_id=0, to_module=1, input_id=0),
            CableSpec(from_module=1, output_id=0, to_module=2, input_id=0, color="#123456"),
        ],
    )
    assert result["ok"] is True, result
    assert len(result["module_ids"]) == 3
    patch = read_vcv(target)
    vco, vcf, audio = patch.modules
    assert vco["version"] == "2.6.4" and vco["params"] == [{"id": 1, "value": 0.5}] and vco["pos"] == [0, 0]
    assert vcf["pos"] == [16, 0]
    assert audio["version"] == "2.5.2" and audio["pos"] == [40, 0]
    assert patch.cables[1]["color"] == "#123456"
    assert patch.cables[0]["outputModuleId"] == vco["id"] and patch.cables[0]["inputModuleId"] == vcf["id"]


def test_create_rejects_bad_index_and_unknown_module(tmp_path: Path, fake_rack_env):
    bad_index = vcv_create(
        str(tmp_path / "a.vcv"),
        modules=[ModuleSpec(plugin="Fundamental", model="VCO")],
        cables=[CableSpec(from_module=0, output_id=0, to_module=5, input_id=0)],
    )
    assert bad_index["ok"] is False and "index" in bad_index["error"]
    unknown = vcv_create(str(tmp_path / "b.vcv"), modules=[ModuleSpec(plugin="Fundamental", model="Nope")])
    assert unknown["ok"] is False and unknown["error"] == "validation failed"
    assert not (tmp_path / "b.vcv").exists()


def test_validate_tool(tmp_path: Path, vcv_file: Path, raw, fake_rack_env):
    good = vcv_validate(str(vcv_file))
    assert good == {"ok": True, "valid": True, "issues": []}
    raw["masterModuleId"] = 777
    warn_file = write_vcv(Patch(raw=raw), tmp_path / "warn.vcv")
    result = vcv_validate(str(warn_file))
    assert result["ok"] is True and result["valid"] is True
    assert result["issues"][0]["severity"] == "warning"


def test_library_search_tool(fake_rack_env):
    result = vcv_library_search("oscillator")
    assert result["ok"] is True and result["count"] == 2
    assert {r["model"] for r in result["results"]} == {"VCO", "LFO"}
    assert result["results"][0]["plugin_version"] == "2.6.4"
    limited = vcv_library_search(limit=1)
    assert limited["count"] == 1


def test_library_search_without_rack(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RACK_USER_DIR", str(tmp_path / "nowhere"))
    result = vcv_library_search("vco")
    assert result["ok"] is False and "Rack user directory not found" in result["error"]
