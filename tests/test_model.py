import copy
import json

import pytest

from vcvpatch.errors import FormatError, ValidationError
from vcvpatch.model import CABLE_COLORS, DEFAULT_MODULE_WIDTH_HP, Patch


def test_new_patch_is_minimal():
    p = Patch.new("2.5.2")
    assert p.raw == {"version": "2.5.2", "modules": [], "cables": []}
    assert p.assets == {}
    assert p.master_module_id is None


def test_from_json_rejects_non_object():
    with pytest.raises(FormatError):
        Patch.from_json("[1, 2]")
    with pytest.raises(FormatError):
        Patch.from_json("{not json")


def test_accessors(raw):
    p = Patch(raw=raw)
    assert p.rack_version == "2.5.2"
    assert [m["id"] for m in p.modules] == [1, 2, 3]
    assert len(p.cables) == 2
    assert p.master_module_id == 3
    assert p.get_module(2)["model"] == "VCF"
    assert p.get_module(99) is None
    assert p.get_cable(100)["inputModuleId"] == 2
    assert p.get_cable(5) is None


def test_modules_property_requires_list():
    p = Patch(raw={"version": "2.5.2", "cables": []})
    with pytest.raises(ValidationError):
        p.modules


def test_next_id_is_unique_53_bit(raw):
    p = Patch(raw=raw)
    seen = {p.next_id() for _ in range(50)}
    assert all(0 < i < 2**53 for i in seen)
    assert not seen & {1, 2, 3, 100, 101}


def test_add_module_auto_id_and_pos(raw):
    p = Patch(raw=raw)
    m = p.add_module("Fundamental", "VCA", version="2.6.4")
    assert m["plugin"] == "Fundamental" and m["model"] == "VCA"
    assert m["version"] == "2.6.4"
    assert m["params"] == []
    assert m["pos"] == [20 + DEFAULT_MODULE_WIDTH_HP, 0]
    assert m["id"] not in {1, 2, 3}
    assert p.modules[-1] is m


def test_add_module_on_empty_patch_starts_at_origin():
    p = Patch.new()
    m = p.add_module("Fundamental", "VCO")
    assert m["pos"] == [0, 0]
    assert "version" not in m


def test_add_module_explicit_pos_params_and_id():
    p = Patch.new()
    m = p.add_module("Fundamental", "VCO", pos=[5.0, 1.0], params=[{"id": 1, "value": 0.25}], module_id=42)
    assert m["pos"] == [5, 1]
    assert m["params"] == [{"id": 1, "value": 0.25}]
    assert m["id"] == 42
    with pytest.raises(ValidationError):
        p.add_module("Fundamental", "VCF", module_id=42)


def test_add_cable_checks_endpoints_and_cycles_colors(raw):
    p = Patch(raw=raw)
    c = p.add_cable(1, 1, 3, 1)
    assert c["outputModuleId"] == 1 and c["inputModuleId"] == 3
    assert c["color"] == CABLE_COLORS[2 % len(CABLE_COLORS)]
    assert p.cables[-1] is c
    with pytest.raises(ValidationError):
        p.add_cable(1, 0, 999, 0)
    with pytest.raises(ValidationError):
        p.add_cable(1, 0, 2, 0, cable_id=100)


def test_remove_module_cleans_up(raw):
    p = Patch(raw=raw, assets={"modules/2/IR.wav": b"x", "modules/1/keep.txt": b"y"})
    p.remove_module(2)
    assert [m["id"] for m in p.modules] == [1, 3]
    assert p.cables == []
    assert "rightModuleId" not in p.get_module(1)
    assert p.assets == {"modules/1/keep.txt": b"y"}
    p.remove_module(3)
    assert "masterModuleId" not in p.raw
    with pytest.raises(ValidationError):
        p.remove_module(3)


def test_remove_cable(raw):
    p = Patch(raw=raw)
    p.remove_cable(100)
    assert [c["id"] for c in p.cables] == [101]
    with pytest.raises(ValidationError):
        p.remove_cable(100)


def test_set_param_updates_or_appends(raw):
    p = Patch(raw=raw)
    p.set_param(1, 1, 0.75)
    assert p.get_module(1)["params"][1] == {"id": 1, "value": 0.75}
    p.set_param(3, 4, 1.0)
    assert p.get_module(3)["params"] == [{"id": 4, "value": 1.0}]
    with pytest.raises(ValidationError):
        p.set_param(99, 0, 0.0)


def test_to_json_round_trips_and_preserves_unknown_fields(raw):
    before = copy.deepcopy(raw)
    text = Patch(raw=raw).to_json()
    assert text.endswith("\n")
    assert json.loads(text) == before
    assert json.loads(text)["modules"][0]["customModuleField"] == "kept"
