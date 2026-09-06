import copy

from vcvpatch.library import Library
from vcvpatch.model import Patch
from vcvpatch.validate import Issue, has_errors, validate


def messages(issues, severity=None):
    return [i.message for i in issues if severity is None or i.severity == severity]


def test_clean_patch_has_no_issues(raw, fake_plugins_dir):
    lib = Library.scan(fake_plugins_dir)
    issues = validate(Patch(raw=raw), lib)
    assert issues == []
    assert has_errors(issues) is False


def test_issue_str_and_dict():
    issue = Issue("error", "modules[0]", "boom")
    assert str(issue) == "error: modules[0]: boom"
    assert issue.as_dict() == {"severity": "error", "where": "modules[0]", "message": "boom"}


def test_missing_top_level_lists():
    issues = validate(Patch(raw={"version": "2.5.2"}))
    assert has_errors(issues)
    assert any("'modules' must be a list" in m for m in messages(issues))
    assert any("'cables' must be a list" in m for m in messages(issues))


def test_module_shape_and_duplicates(raw):
    raw = copy.deepcopy(raw)
    raw["modules"].append({"id": 1, "plugin": "Fundamental", "model": "VCA"})
    raw["modules"].append({"plugin": "Fundamental"})
    raw["modules"].append("not a dict")
    issues = validate(Patch(raw=raw))
    msgs = messages(issues, "error")
    assert any("duplicate module id 1" in m for m in msgs)
    assert any("missing id, model" in m for m in msgs)
    assert any("module must be an object" in m for m in msgs)


def test_cable_checks(raw):
    raw = copy.deepcopy(raw)
    raw["cables"].append({"id": 100, "outputModuleId": 1, "outputId": 0, "inputModuleId": 99, "inputId": -1})
    raw["cables"].append({"id": 7})
    issues = validate(Patch(raw=raw))
    msgs = messages(issues, "error")
    assert any("duplicate cable id 100" in m for m in msgs)
    assert any("inputModuleId 99 does not exist" in m for m in msgs)
    assert any("inputId must be a non-negative integer" in m for m in msgs)
    assert any("missing outputModuleId, outputId, inputModuleId, inputId" in m for m in msgs)


def test_neighbour_and_master_warnings(raw):
    raw = copy.deepcopy(raw)
    raw["modules"][0]["rightModuleId"] = 3       # 3 does not point back
    raw["modules"][1]["leftModuleId"] = 42       # missing
    raw["masterModuleId"] = 777
    issues = validate(Patch(raw=raw))
    assert not has_errors(issues)
    msgs = messages(issues, "warning")
    assert any("rightModuleId 3 does not point back via leftModuleId" in m for m in msgs)
    assert any("leftModuleId 42 does not exist" in m for m in msgs)
    assert any("masterModuleId 777 does not exist" in m for m in msgs)


def test_library_checks(raw, fake_plugins_dir):
    raw = copy.deepcopy(raw)
    raw["modules"][0]["version"] = "1.0.0"
    raw["modules"].append({"id": 9, "plugin": "Nope", "model": "X"})
    raw["modules"].append({"id": 10, "plugin": "Fundamental", "model": "Missing"})
    lib = Library.scan(fake_plugins_dir)
    issues = validate(Patch(raw=raw), lib)
    assert any("plugin 'Nope' is not installed" in m for m in messages(issues, "error"))
    assert any("plugin 'Fundamental' has no module 'Missing'" in m for m in messages(issues, "error"))
    assert any("module version 1.0.0 differs from installed 2.6.4" in m for m in messages(issues, "warning"))


def test_without_library_skips_install_checks(raw):
    raw = copy.deepcopy(raw)
    raw["modules"].append({"id": 9, "plugin": "Nope", "model": "X"})
    assert validate(Patch(raw=raw)) == []
