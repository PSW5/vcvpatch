import sys
from pathlib import Path

import pytest

from vcvpatch.errors import RackNotFoundError
from vcvpatch.library import CORE_MODULES, Library, plugins_dir, rack_user_dir


def test_rack_user_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RACK_USER_DIR", str(tmp_path))
    assert rack_user_dir() == tmp_path


def test_rack_user_dir_platform_default(monkeypatch):
    monkeypatch.delenv("RACK_USER_DIR", raising=False)
    d = rack_user_dir()
    assert d.name == "Rack2"
    if sys.platform == "darwin":
        assert "Application Support" in str(d)


def test_plugins_dir_falls_back_to_any_plugins_folder(fake_rack_env, fake_plugins_dir):
    assert plugins_dir() == fake_plugins_dir


def test_plugins_dir_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("RACK_USER_DIR", str(tmp_path / "nope"))
    with pytest.raises(RackNotFoundError):
        plugins_dir()
    empty = tmp_path / "Rack2"
    empty.mkdir()
    monkeypatch.setenv("RACK_USER_DIR", str(empty))
    with pytest.raises(RackNotFoundError):
        plugins_dir()


def test_scan_reads_plugins_and_skips_broken(fake_plugins_dir: Path):
    lib = Library.scan(fake_plugins_dir)
    slugs = sorted(p.slug for p in lib.plugins)
    assert slugs == ["Bogaudio", "Core", "Fundamental"]
    assert any("Broken" in w for w in lib.warnings)
    assert lib.plugin_version("Fundamental") == "2.6.4"
    assert lib.plugin_version("Core") is None
    assert lib.plugin_version("Nope") is None


def test_scan_uses_env_when_no_dir_given(fake_rack_env):
    lib = Library.scan()
    assert lib.plugin("Fundamental") is not None


def test_core_is_builtin(fake_plugins_dir: Path):
    lib = Library.scan(fake_plugins_dir)
    assert lib.find("Core", "AudioInterface2") is not None
    assert lib.find("Core", "Notes").plugin == "Core"
    assert len(CORE_MODULES) == 12
    assert Library.scan(fake_plugins_dir, include_core=False).plugin("Core") is None


def test_find(fake_plugins_dir: Path):
    lib = Library.scan(fake_plugins_dir)
    vco = lib.find("Fundamental", "VCO")
    assert vco.name == "VCO" and vco.plugin_version == "2.6.4" and "VCO" in vco.tags
    assert lib.find("Fundamental", "Nope") is None
    assert lib.find("Nope", "VCO") is None


def test_search_query_tags_and_limit(fake_plugins_dir: Path):
    lib = Library.scan(fake_plugins_dir)
    assert [m.slug for m in lib.search("oscillator")] == ["VCO", "LFO"]
    assert [m.slug for m in lib.search("fundamental filter")] == ["VCF"]
    assert [m.slug for m in lib.search(tags=["polyphonic", "vco"])] == ["VCO"]
    assert [m.slug for m in lib.search("noise")] == ["Bogaudio-Noise"]
    assert len(lib.search(limit=2)) == 2
    assert lib.search("zzz-nothing") == []
