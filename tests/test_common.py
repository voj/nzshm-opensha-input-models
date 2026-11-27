import hashlib

import pytest

from model_checks import common
from model_checks.common import (
    Report,
    bom,
    check_bom,
    check_replaced_by,
    file_entries,
    file_path,
    load_configs,
    model_type,
    sha256,
    strip_bom,
    validate_meta,
)

from .conftest import PROJECT, fault_meta


@pytest.fixture
def configs():
    return load_configs(PROJECT)


def test_report_dedupes_and_exit_code(capsys):
    r = Report()
    assert r.finish() == 0
    r.err("x")
    r.err("x")
    r.warn("w")
    assert r.errors == ["x"]
    assert r.finish() == 1
    out = capsys.readouterr().out
    assert out.count("ERROR: x") == 1 and "WARNING: w" in out


@pytest.mark.parametrize("path, expected", [
    ("models/faultModels/a.csv", "faultModels"),
    ("models/faultModels/sub/a.csv", "faultModels"),
    ("models/a.csv", None),
    ("README.md", None),
    ("other/faultModels/a.csv", None),
])
def test_model_type(path, expected):
    assert model_type(path) == expected


def test_file_path_relative_to_meta():
    assert file_path("models/fm/sub/x.meta.json", "a.csv") == "models/fm/sub/a.csv"
    assert file_path("models/fm/sub/x.meta.json", "../a.csv") == "models/fm/a.csv"


def test_file_entries_skips_malformed():
    assert file_entries({}) == []
    assert file_entries({"files": "nope"}) == []
    assert file_entries({"files": [{"path": "a"}, "b", {"sha256": "x"}, {"path": 1}]}) == [{"path": "a"}]


def test_sha256(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"hello")
    assert sha256(p) == hashlib.sha256(b"hello").hexdigest()


def test_load_configs_has_all_model_folders(configs):
    assert set(configs) == {p.name for p in (PROJECT / "models").iterdir() if p.is_dir()}
    for cfg in configs.values():
        assert "properties" in cfg["_common"] and "_specific" in cfg


SHA = "0" * 64


def valid_fault():
    return fault_meta("m", [{"path": "m.csv", "sha256": SHA}])


def test_valid_meta(configs, report):
    validate_meta(report, "p", valid_fault(), configs["faultModels"])
    assert report.errors == []


@pytest.mark.parametrize("date", ["2026", "2026-01", "2026-12-31"])
def test_partial_dates_ok(configs, report, date):
    validate_meta(report, "p", {**valid_fault(), "date": date}, configs["faultModels"])
    assert report.errors == []


@pytest.mark.parametrize("date", ["26", "2026-13", "2026-1", "2026-01-32", "2026/01", "Nov 2026"])
def test_bad_dates(configs, report, date):
    validate_meta(report, "p", {**valid_fault(), "date": date}, configs["faultModels"])
    assert any("date" in e for e in report.errors)


@pytest.mark.parametrize("change, fragment", [
    ({"files": []}, "files"),
    ({"files": [{"path": "a.csv"}]}, "sha256"),
    ({"files": [{"path": "a.csv", "sha256": "ABC"}]}, "sha256"),
    ({"files": [{"path": "/abs.csv", "sha256": SHA}]}, "path"),
    ({"files": [{"path": "../up.csv", "sha256": SHA}]}, "path"),
    ({"files": [{"path": "a.csv", "sha256": SHA, "x": 1}]}, "files/0"),
    ({"owner": ""}, "owner"),
    ({"partition": "NOPE"}, "partition"),
    ({"crustal": "yes"}, "crustal"),
    ({"extra": 1}, "unknown field 'extra'"),
    ({"deprecated": {"date": "2026"}}, "reason"),
    ({"deprecated": {"date": "2026", "reason": "r", "x": 1}}, "deprecated"),
])
def test_invalid_meta(configs, report, change, fragment):
    validate_meta(report, "p", {**valid_fault(), **change}, configs["faultModels"])
    assert any(fragment in e for e in report.errors), report.errors


def test_missing_required(configs, report):
    meta = valid_fault()
    del meta["provenance"]
    del meta["modelName"]
    validate_meta(report, "p", meta, configs["faultModels"])
    assert any("provenance" in e for e in report.errors)
    assert any("modelName" in e for e in report.errors)


def test_deformation_specific_field(configs, report):
    meta = {k: v for k, v in valid_fault().items() if k not in ("modelName", "crustal", "partition")}
    validate_meta(report, "p", meta, configs["deformationModels"])
    assert any("compatibility" in e for e in report.errors)


def test_deprecated_valid(configs, report):
    meta = {**valid_fault(), "deprecated": {"date": "2026-11", "reason": "old"}}
    validate_meta(report, "p", meta, configs["faultModels"])
    assert report.errors == []


def test_replaced_by(tmp_path, report):
    (tmp_path / "models").mkdir()
    (tmp_path / "models/new.meta.json").write_text("{}")
    ok = {"deprecated": {"date": "2026", "reason": "r", "replacedBy": "models/new.meta.json"}}
    check_replaced_by(report, tmp_path, "p", ok)
    check_replaced_by(report, tmp_path, "p", {})
    check_replaced_by(report, tmp_path, "p", {"deprecated": "bad"})
    assert report.errors == []
    for rb in ("models/missing.meta.json", "models/new.csv"):
        check_replaced_by(report, tmp_path, "p", {"deprecated": {"replacedBy": rb}})
    assert len(report.errors) == 2


@pytest.mark.parametrize("prefix, name", [
    (b"\xef\xbb\xbf", "UTF-8"),
    (b"\xff\xfe", "UTF-16 LE"),
    (b"\xfe\xff", "UTF-16 BE"),
    (b"\xff\xfe\x00\x00", "UTF-32 LE"),
    (b"\x00\x00\xfe\xff", "UTF-32 BE"),
    (b"", None),
])
def test_bom_detection(tmp_path, prefix, name):
    p = tmp_path / "f"
    p.write_bytes(prefix + b"a,b\n")
    assert bom(p) == name


def test_bom_empty_file(tmp_path):
    (tmp_path / "f").write_bytes(b"")
    assert bom(tmp_path / "f") is None


def test_check_bom(tmp_path, report):
    (tmp_path / "ok").write_bytes(b"a")
    (tmp_path / "bad").write_bytes(b"\xef\xbb\xbfa")
    check_bom(report, "ok", tmp_path)
    check_bom(report, "bad", tmp_path)
    assert report.errors == ["bad: starts with a UTF-8 byte order mark (BOM); remove it"]


def test_strip_bom(tmp_path, report):
    (tmp_path / "u8").write_bytes(b"\xef\xbb\xbfa,b\n")
    (tmp_path / "u16").write_bytes(b"\xff\xfea\x00")
    (tmp_path / "plain").write_bytes(b"a")
    for f in ("u8", "u16", "plain"):
        strip_bom(report, f, tmp_path)
    assert (tmp_path / "u8").read_bytes() == b"a,b\n"
    assert (tmp_path / "u16").read_bytes() == b"\xff\xfea\x00"
    assert (tmp_path / "plain").read_bytes() == b"a"
    assert len(report.errors) == 1 and "UTF-16 LE" in report.errors[0]


def test_run_validation(tmp_path, report, jar):
    cfg = {"path": "fm", "validation": None}
    assert common.run_validation(report, str(tmp_path), "m.meta.json", cfg, jar)
    assert report.errors == []

    cfg["validation"] = ["python3", "-c", "print('x')"]
    assert not common.run_validation(report, str(tmp_path), "m.meta.json", cfg, None)
    assert "no --jar" in report.errors[0]


def test_run_validation_substitutes_and_fails(tmp_path, report, jar):
    import sys
    out = tmp_path / "args.txt"
    cmd = [sys.executable, "-c",
           "import sys; open(sys.argv[1], 'w').write(' '.join(sys.argv[2:])); sys.exit(1)",
           str(out), "{meta}", "{jar}", "{repo}"]
    common.run_validation(report, str(tmp_path), "models/m.meta.json", {"path": "fm", "validation": cmd}, jar)
    assert out.read_text() == f"models/m.meta.json {jar} {tmp_path}"
    assert report.errors == ["models/m.meta.json: validation failed"]
