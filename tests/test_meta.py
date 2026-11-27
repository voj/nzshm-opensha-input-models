import pytest

from model_checks import meta as meta_cli
from model_checks.common import sha256
from model_checks.meta import find_repo, process


def run_cli(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["model-meta", *args])
    with pytest.raises(SystemExit) as e:
        meta_cli.main()
    return e.value.code


def test_find_repo(repo, tmp_path):
    assert find_repo(repo.path / "models" / "faultModels") == repo.path
    assert find_repo(tmp_path) is None


def test_fills_checksums(repo, report):
    m = repo.add_model("new", files={"a.csv": "a\n", "sub/b.txt": "b\n"}, with_sha=False)
    process(report, [str(repo.path / m)])
    assert report.errors == []
    files = repo.read_json(m)["files"]
    assert files[0]["sha256"] == sha256(repo.path / "models/faultModels/a.csv")
    assert files[1]["sha256"] == sha256(repo.path / "models/faultModels/sub/b.txt")


def test_check_mode_does_not_write(repo, report):
    m = repo.add_model("new", with_sha=False)
    before = (repo.path / m).read_bytes()
    process(report, [str(repo.path / m)], check=True)
    assert (repo.path / m).read_bytes() == before
    assert any("sha256 missing" in e for e in report.errors)


def test_check_mode_detects_mismatch(repo, report):
    m = repo.add_model("new")
    repo.write("models/faultModels/new.csv", "changed\n")
    process(report, [str(repo.path / m)], check=True)
    assert any("sha256 mismatch" in e for e in report.errors)


def test_untouched_file_keeps_formatting(repo, report):
    m = repo.add_model("new")
    compact = (repo.path / m).read_text().replace("\n", "").replace("  ", "")
    (repo.path / m).write_text(compact)
    process(report, [str(repo.path / m)])
    assert report.errors == []
    assert (repo.path / m).read_text() == compact


def test_missing_listed_file(repo, report):
    m = repo.add_model("new", with_sha=False)
    (repo.path / "models/faultModels/new.csv").unlink()
    process(report, [str(repo.path / m)])
    assert any("not found" in e for e in report.errors)


def test_listed_file_outside_models(repo, report):
    m = repo.add_model("new")
    data = repo.read_json(m)
    data["files"].append({"path": "../../README.md"})
    repo.write_json(m, data)
    process(report, [str(repo.path / m)])
    assert any("README.md not found" in e for e in report.errors)


def test_bad_inputs(repo, report, tmp_path):
    (tmp_path / "x.meta.json").write_text("{}")
    repo.write("models/faultModels/x.json", "{}")
    repo.write("models/unconfigured/x.meta.json", "{}")
    repo.write("models/faultModels/bad.meta.json", "{nope")
    process(report, [
        str(tmp_path / "x.meta.json"),
        str(repo.path / "models/faultModels/x.json"),
        str(repo.path / "models/unconfigured/x.meta.json"),
        str(repo.path / "models/faultModels/bad.meta.json"),
        str(repo.path / "models/faultModels/missing.meta.json"),
    ])
    joined = "\n".join(report.errors)
    assert "not inside the model repo" in joined
    assert "must end with .meta.json" in joined
    assert "not inside a configured model folder" in joined
    assert "invalid JSON" in joined
    assert "missing.meta.json: not found" in joined


def test_schema_errors_reported(repo, report):
    m = repo.add_model("new", date="yesterday")
    process(report, [str(repo.path / m)])
    assert any("date" in e for e in report.errors)


def test_bom_rejected_and_stripped(repo, report):
    m = repo.add_model("new", files={"a.csv": b"\xef\xbb\xbfa\n"}, with_sha=False)
    meta_file = repo.path / m
    meta_file.write_bytes(b"\xef\xbb\xbf" + meta_file.read_bytes())

    process(report, [str(meta_file)])
    assert any("BOM" in e for e in report.errors)

    report.errors.clear()
    process(report, [str(meta_file)], remove_bom=True)
    assert report.errors == []
    assert (repo.path / "models/faultModels/a.csv").read_bytes() == b"a\n"
    assert repo.read_json(m)["files"][0]["sha256"] == sha256(repo.path / "models/faultModels/a.csv")


def test_validation_runs_only_without_errors(repo, report, jar):
    from .conftest import VALIDATE
    repo.set_validation("faultModels", VALIDATE)
    ok = repo.add_model("ok")
    bad = repo.add_model("bad", crustal=False)
    process(report, [str(repo.path / ok), str(repo.path / bad)], jar=jar)
    assert report.errors == [f"{bad}: validation failed"]


def test_cli(repo, monkeypatch):
    m = repo.add_model("new", with_sha=False)
    assert run_cli(monkeypatch, "--check", str(repo.path / m)) == 1
    assert run_cli(monkeypatch, str(repo.path / m)) == 0
    assert run_cli(monkeypatch, "--check", str(repo.path / m)) == 0
