import pytest

from vcvpatch.library import Library
from vcvpatch.model import Patch
from vcvpatch.summary import summarize


def test_text_summary_lists_modules_and_cables(raw, fake_plugins_dir):
    lib = Library.scan(fake_plugins_dir)
    patch = Patch(raw=raw, assets={"modules/2/IR.wav": b"x"})
    text = summarize(patch, lib)
    assert "Rack 2.5.2" in text
    assert "3 modules, 2 cables" in text
    lines = text.splitlines()
    module_lines = [l for l in lines if l.strip().startswith(("1 ", "2 ", "3 "))]
    assert "Fundamental/VCO" in module_lines[0] and "VCO" in module_lines[0]
    assert "Fundamental/VCF" in module_lines[1] and "1 asset" in module_lines[1]
    assert "Core/AudioInterface2" in module_lines[2] and "Audio 2" in module_lines[2]
    assert "Fundamental/VCO#1 out[0] -> Fundamental/VCF#2 in[0]" in text
    assert "Fundamental/VCF#2 out[0] -> Core/AudioInterface2#3 in[0]" in text


def test_modules_sorted_by_row_then_x(raw):
    raw["modules"][0]["pos"] = [0, 1]  # move VCO to row 1
    text = summarize(Patch(raw=raw))
    assert text.index("Fundamental/VCF") < text.index("Fundamental/VCO")


def test_markdown_summary(raw):
    md = summarize(Patch(raw=raw), fmt="markdown")
    assert md.startswith("# ")
    assert "| id | module |" in md
    assert "| 1 | Fundamental/VCO |" in md
    assert "Fundamental/VCO#1 out[0] -> Fundamental/VCF#2 in[0]" in md


def test_unknown_fmt():
    with pytest.raises(ValueError):
        summarize(Patch.new(), fmt="yaml")


def test_summary_tolerates_missing_pos_and_lists():
    patch = Patch(raw={"version": "2.5.2", "modules": [{"id": 1, "plugin": "A", "model": "B"}], "cables": []})
    text = summarize(patch)
    assert "A/B" in text
