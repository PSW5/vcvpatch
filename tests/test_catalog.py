import json
from pathlib import Path

from vcvpatch.archive import write_vcv
from vcvpatch.catalog import HP_PX, ROW_PX, fit_view, parse_name, write_catalog
from vcvpatch.cli import main
from vcvpatch.library import Library
from vcvpatch.model import Patch


def test_parse_name():
    assert parse_name("ICMP_w5_ex_FM.vcv") == {"stem": "ICMP_w5_ex_FM", "week": 5, "topic": "FM", "date": None}
    assert parse_name("ICMP_w10_ex_clock_mod_251103.vcv") == {
        "stem": "ICMP_w10_ex_clock_mod_251103", "week": 10, "topic": "clock-mod", "date": "2025-11-03"
    }
    assert parse_name("w1_ex.vcv") == {"stem": "w1_ex", "week": 1, "topic": "", "date": None}
    assert parse_name("ICMP_final-project-preset-example.vcv") == {
        "stem": "ICMP_final-project-preset-example", "week": None, "topic": "final-project-preset-example", "date": None
    }
    r = parse_name("ICMP_251020_ex_snh.vcv")
    assert r["week"] is None and r["topic"] == "snh" and r["date"] == "2025-10-20"
    assert parse_name("icmp115-w02-sampling-aliasing.vcv") == {
        "stem": "icmp115-w02-sampling-aliasing", "week": 2, "topic": "sampling-aliasing", "date": None
    }
    assert parse_name("icmp115-w09-sample-hold-class.vcv")["topic"] == "sample-hold-class"


def test_infer_annotation_new_scheme(tmp_path: Path):
    from vcvpatch.catalog import infer_annotation

    rec = {"topic": "sample-hold-class", "week": 9, "stem": "x", "modules": [], "plugins": {}, "module_count": 0,
           "cable_count": 0, "notes": []}
    ann = infer_annotation(rec)
    assert ann["title"] == "Sample & Hold" and "in-class" in ann["tags"]
    rec["topic"] = "sampling-aliasing"
    assert infer_annotation(rec)["title"] == "Sampling & aliasing"


def test_fit_view_small_patch_is_capped_and_centred():
    zoom, offset = fit_view((0, 0, 10, 0), 1500, 800)
    assert zoom == 1.5
    view_w_hp = 1500 / zoom / HP_PX
    content_w_hp = 10 + 20
    assert abs(offset[0] - (0 - (view_w_hp - content_w_hp) / 2)) < 1e-6
    assert offset[1] < 0  # centred vertically around row 0


def test_fit_view_wide_patch_shrinks_to_fit():
    bbox = (-3, -1, 177, 2)
    zoom, offset = fit_view(bbox, 1700, 1000)
    assert 0.25 <= zoom < 1.0
    right_px = (177 + 20 - offset[0]) * HP_PX * zoom
    bottom_px = (2 + 1 - offset[1]) * ROW_PX * zoom
    assert right_px <= 1700 + 1e-6 and bottom_px <= 1000 + 1e-6
    assert offset[0] <= -3 and offset[1] <= -1


def test_fit_view_respects_zoom_min():
    zoom, _ = fit_view((0, 0, 5000, 0), 800, 600)
    assert zoom == 0.25


def test_patch_bbox(raw):
    assert Patch(raw=raw).bbox() == (0, 0, 20, 0)
    assert Patch.new().bbox() is None


def _make_course_dir(tmp_path: Path) -> Path:
    course = tmp_path / "vcv_files"
    course.mkdir()
    p = Patch.new("2.5.2")
    vco = p.add_module("Fundamental", "VCO", version="2.6.4", pos=[0, 0])
    vcf = p.add_module("Fundamental", "VCF", version="2.6.4", pos=[10, 0])
    notes = p.add_module("Core", "Notes", version="2.5.2", pos=[30, 1])
    notes["data"] = {"text": "DX7 = LFM"}
    p.add_cable(vco["id"], 2, vcf["id"], 0)
    p.assets["modules/%d/IR.wav" % vco["id"]] = b"wav"
    p.assets["._patch.json"] = b"apple double junk"
    write_vcv(p, course / "ICMP_w5_ex_FM.vcv")
    q = Patch.new("2.5.2")
    q.add_module("Fundamental", "LFO", version="2.6.4", pos=[0, 0])
    write_vcv(q, course / "w1_ex.vcv")
    snaps = course / "catalog" / "snapshots"
    snaps.mkdir(parents=True)
    (snaps / "ICMP_w5_ex_FM.png").write_bytes(b"\x89PNG fake")
    return course


def test_write_catalog_generates_everything(tmp_path: Path, fake_plugins_dir: Path):
    course = _make_course_dir(tmp_path)
    lib = Library.scan(fake_plugins_dir)
    result = write_catalog(course, lib)
    assert result["count"] == 2

    index = (course / "INDEX.md").read_text(encoding="utf-8")
    assert "## Week 1" in index and "## Week 5" in index
    assert index.index("## Week 1") < index.index("## Week 5")
    assert "catalog/snapshots/ICMP_w5_ex_FM.png" in index
    assert "catalog/patches/ICMP_w5_ex_FM.md" in index
    assert "vcvpatch catalog" in index  # handoff instructions

    catalog = json.loads((course / "catalog" / "catalog.json").read_text(encoding="utf-8"))
    assert [r["file"] for r in catalog["patches"]] == ["w1_ex.vcv", "ICMP_w5_ex_FM.vcv"]
    fm = catalog["patches"][1]
    assert fm["week"] == 5 and fm["topic"] == "FM"
    assert fm["module_count"] == 3 and fm["cable_count"] == 1 and fm["asset_count"] == 1
    assert fm["assets"] == ["modules/%d/IR.wav" % fm["modules"][0]["id"]]
    assert fm["plugins"] == {"Core": 1, "Fundamental": 2}
    assert fm["notes"] == ["DX7 = LFM"]
    assert fm["snapshot"] == "catalog/snapshots/ICMP_w5_ex_FM.png"
    assert catalog["patches"][0]["snapshot"] is None
    assert any(m["name"] == "VCO" for m in fm["modules"])
    assert fm["bbox"]["width_hp"] == 30 and fm["bbox"]["rows"] == 2
    assert fm["cables"][0]["out"] == 2

    page = (course / "catalog" / "patches" / "ICMP_w5_ex_FM.md").read_text(encoding="utf-8")
    assert "DX7 = LFM" in page and "Fundamental/VCO" in page and "../snapshots/ICMP_w5_ex_FM.png" in page

    ann = json.loads((course / "catalog" / "annotations.json").read_text(encoding="utf-8"))
    assert ann["ICMP_w5_ex_FM"]["inferred"] is True
    assert "FM" in ann["ICMP_w5_ex_FM"]["title"]
    assert "fm" in ann["ICMP_w5_ex_FM"]["tags"]
    assert set(result["added_annotations"]) == {"ICMP_w5_ex_FM", "w1_ex"}


def test_rerun_preserves_manual_annotations_and_adds_new(tmp_path: Path, fake_plugins_dir: Path):
    course = _make_course_dir(tmp_path)
    lib = Library.scan(fake_plugins_dir)
    write_catalog(course, lib)
    ann_path = course / "catalog" / "annotations.json"
    ann = json.loads(ann_path.read_text(encoding="utf-8"))
    ann["ICMP_w5_ex_FM"] = {"title": "My FM lesson", "summary": "edited", "tags": ["fm"], "teaching_points": ["x"], "inferred": False}
    ann_path.write_text(json.dumps(ann), encoding="utf-8")
    write_vcv(Patch.new("2.5.2"), course / "ICMP_w9_ex_KS.vcv")

    result = write_catalog(course, lib)
    ann2 = json.loads(ann_path.read_text(encoding="utf-8"))
    assert ann2["ICMP_w5_ex_FM"]["title"] == "My FM lesson"
    assert "karplus" in " ".join(ann2["ICMP_w9_ex_KS"]["tags"]).lower()
    assert result["added_annotations"] == ["ICMP_w9_ex_KS"]
    index = (course / "INDEX.md").read_text(encoding="utf-8")
    assert "My FM lesson" in index and "## Week 9" in index


def test_cli_catalog_command(tmp_path: Path, capsys):
    course = _make_course_dir(tmp_path)
    assert main(["catalog", str(course), "--no-library"]) == 0
    assert (course / "INDEX.md").is_file()
    assert "2 patches" in capsys.readouterr().out
