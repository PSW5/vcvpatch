import json
from pathlib import Path

import pytest

FUNDAMENTAL_PLUGIN_JSON = {
    "slug": "Fundamental",
    "name": "VCV Free",
    "version": "2.6.4",
    "brand": "VCV",
    "modules": [
        {"slug": "VCO", "name": "VCO", "description": "Voltage-controlled oscillator", "tags": ["VCO", "Polyphonic"]},
        {"slug": "VCF", "name": "VCF", "description": "Voltage-controlled filter", "tags": ["VCF", "Polyphonic"]},
        {"slug": "VCA", "name": "VCA", "description": "Voltage-controlled amplifier", "tags": ["VCA", "Polyphonic"]},
        {"slug": "LFO", "name": "LFO", "description": "Low-frequency oscillator", "tags": ["LFO"]},
    ],
}

BOGAUDIO_PLUGIN_JSON = {
    "slug": "Bogaudio",
    "name": "Bogaudio",
    "version": "2.4.42",
    "brand": "Bogaudio",
    "modules": [
        {"slug": "Bogaudio-Noise", "name": "NOISE", "description": "Noise source", "tags": ["Noise"]},
    ],
}


@pytest.fixture
def fake_plugins_dir(tmp_path: Path) -> Path:
    """A fake Rack plugins directory with two plugins and one broken plugin.json."""
    pdir = tmp_path / "Rack2" / "plugins-fake-x64"
    for data in (FUNDAMENTAL_PLUGIN_JSON, BOGAUDIO_PLUGIN_JSON):
        d = pdir / data["slug"]
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
    broken = pdir / "Broken"
    broken.mkdir()
    (broken / "plugin.json").write_text("{not json", encoding="utf-8")
    return pdir


@pytest.fixture
def fake_rack_env(fake_plugins_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point RACK_USER_DIR at the fake Rack user dir; returns the user dir."""
    user_dir = fake_plugins_dir.parent
    monkeypatch.setenv("RACK_USER_DIR", str(user_dir))
    return user_dir


def sample_raw() -> dict:
    """A small patch dict shaped like real Rack 2.5.2 output, with unknown fields."""
    return {
        "version": "2.5.2",
        "path": "/tmp/example.vcv",
        "zoom": 1.0,
        "gridOffset": [0, 0],
        "customTopLevel": {"kept": True},
        "modules": [
            {
                "id": 1,
                "plugin": "Fundamental",
                "model": "VCO",
                "version": "2.6.4",
                "params": [{"id": 0, "value": 0.0}, {"id": 1, "value": 0.5}],
                "rightModuleId": 2,
                "pos": [0, 0],
                "customModuleField": "kept",
            },
            {
                "id": 2,
                "plugin": "Fundamental",
                "model": "VCF",
                "version": "2.6.4",
                "params": [{"id": 0, "value": 0.30000001192092896}],
                "leftModuleId": 1,
                "pos": [10, 0],
                "data": {"nested": [1, 2, 3]},
            },
            {
                "id": 3,
                "plugin": "Core",
                "model": "AudioInterface2",
                "version": "2.5.2",
                "params": [],
                "pos": [20, 0],
            },
        ],
        "cables": [
            {"id": 100, "outputModuleId": 1, "outputId": 0, "inputModuleId": 2, "inputId": 0, "color": "#f3374b"},
            {"id": 101, "outputModuleId": 2, "outputId": 0, "inputModuleId": 3, "inputId": 0, "color": "#ffb437"},
        ],
        "masterModuleId": 3,
    }


@pytest.fixture
def raw() -> dict:
    return sample_raw()
