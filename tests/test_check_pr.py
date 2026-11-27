import os

import pytest

from model_checks import check_pr

from .conftest import VALIDATE, git


def run(repo, monkeypatch, *, base="main", rules=None, jar=None):
    """Commit the working tree and run check-pr against base; returns (exit code, output)."""
    repo.commit("pr")
    args = ["check-pr", "--rules", str(rules or repo.path), "--repo", str(repo.path), "--base", base]
    if jar:
        args += ["--jar", jar]
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit) as e:
        check_pr.main()
    return e.value.code


def errors(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("ERROR")]


def test_new_model_passes(repo, monkeypatch, capsys):
    repo.add_model("new", files={"new.xml": "<x/>", "new.xml.FaultsByNameAlt.txt": "t"})
    assert run(repo, monkeypatch) == 0, errors(capsys)


def test_several_models_and_subfolders(repo, monkeypatch, capsys):
    repo.add_model("a")
    repo.add_model("b", folder="models/faultModels/sub/deeper")
    repo.add_model("c", folder="models/deformationModels")
    assert run(repo, monkeypatch) == 0, errors(capsys)


def test_no_changes_passes(repo, monkeypatch):
    assert run(repo, monkeypatch) == 0


@pytest.mark.parametrize("action", ["modify", "delete", "rename", "chmod"])
def test_existing_data_is_immutable(repo, monkeypatch, capsys, action):
    f = repo.path / "models/faultModels/existing.csv"
    if action == "modify":
        f.write_text("changed\n")
    elif action == "delete":
        f.unlink()
    elif action == "rename":
        f.rename(f.with_name("renamed.csv"))
    elif action == "chmod":
        os.chmod(f, 0o755)
    assert run(repo, monkeypatch) == 1
    assert any("existing.csv: existing files under models/ are immutable" in e for e in errors(capsys))


def test_override_turns_immutability_into_warnings(repo, monkeypatch, capsys):
    monkeypatch.setenv("ALLOW_MODEL_CHANGES", "true")
    (repo.path / "models/faultModels/existing.csv").write_text("changed\n")
    (repo.path / "models/deformationModels/existing_dm.csv").unlink()
    assert run(repo, monkeypatch) == 0
    assert capsys.readouterr().out.count("(allowed by modify_models)") == 2


def test_changes_outside_models_need_label(repo, monkeypatch, capsys):
    repo.write("README.md", "changed\n")
    assert run(repo, monkeypatch) == 1
    assert any("allow-non-model-changes" in e for e in errors(capsys))

    monkeypatch.setenv("ALLOW_NON_MODEL_CHANGES", "true")
    assert run(repo, monkeypatch) == 0


def test_meta_mutable_fields(repo, monkeypatch, capsys):
    m = "models/faultModels/existing.meta.json"
    data = repo.read_json(m)
    data["owner"] = "someone"
    data["deprecated"] = {"date": "2026-11", "reason": "old"}
    repo.write_json(m, data)
    assert run(repo, monkeypatch) == 0, errors(capsys)

    data["deprecated"]["reason"] = "older"
    repo.write_json(m, data)
    assert run(repo, monkeypatch, base="HEAD~1") == 0, errors(capsys)


@pytest.mark.parametrize("field, value", [("description", "new"), ("files", []), ("crustal", False)])
def test_meta_immutable_fields(repo, monkeypatch, capsys, field, value):
    m = "models/faultModels/existing.meta.json"
    data = repo.read_json(m)
    data[field] = value
    repo.write_json(m, data)
    assert run(repo, monkeypatch) == 1
    assert any(f"field '{field}' is immutable" in e for e in errors(capsys))


def test_meta_formatting_change_is_ok(repo, monkeypatch, capsys):
    m = repo.path / "models/faultModels/existing.meta.json"
    m.write_text(m.read_text().replace("\n", "").replace("  ", ""))
    assert run(repo, monkeypatch) == 0, errors(capsys)


def test_modified_meta_schema_checked(repo, monkeypatch, capsys):
    m = "models/faultModels/existing.meta.json"
    data = repo.read_json(m)
    data["deprecated"] = {"date": "soon", "reason": "r", "replacedBy": "models/x.meta.json"}
    repo.write_json(m, data)
    assert run(repo, monkeypatch) == 1
    errs = errors(capsys)
    assert any("deprecated/date" in e for e in errs)
    assert any("replacedBy" in e for e in errs)


def test_unlisted_file(repo, monkeypatch, capsys):
    repo.add_model("new")
    repo.write("models/faultModels/stray.csv", "s\n")
    assert run(repo, monkeypatch) == 1
    assert errors(capsys) == ["ERROR: models/faultModels/stray.csv: not listed in any new meta file"]


def test_new_meta_must_not_claim_existing_file(repo, monkeypatch, capsys):
    m = repo.add_model("new")
    data = repo.read_json(m)
    data["files"].append({"path": "existing.csv", "sha256": data["files"][0]["sha256"]})
    repo.write_json(m, data)
    assert run(repo, monkeypatch) == 1
    assert any("existing.csv is not new" in e for e in errors(capsys))


def test_file_claimed_twice(repo, monkeypatch, capsys):
    a = repo.add_model("a")
    b = repo.add_model("b")
    data = repo.read_json(b)
    data["files"] = repo.read_json(a)["files"]
    repo.write_json(b, data)
    assert run(repo, monkeypatch) == 1
    errs = errors(capsys)
    assert any("a.csv already listed by" in e for e in errs)
    assert any("b.csv: not listed" in e for e in errs)


def test_sha_mismatch(repo, monkeypatch, capsys):
    repo.add_model("new")
    repo.write("models/faultModels/new.csv", "tampered\n")
    assert run(repo, monkeypatch) == 1
    assert any("sha256 mismatch" in e for e in errors(capsys))


def test_invalid_json(repo, monkeypatch, capsys):
    repo.write("models/faultModels/bad.meta.json", "{nope")
    assert run(repo, monkeypatch) == 1
    assert any("invalid JSON" in e for e in errors(capsys))


def test_bom_rejected(repo, monkeypatch, capsys):
    repo.add_model("new", files={"new.csv": b"\xef\xbb\xbfa\n"})
    assert run(repo, monkeypatch) == 1
    assert any("new.csv: starts with a UTF-8 byte order mark" in e for e in errors(capsys))


def test_case_collision(repo, monkeypatch, capsys):
    repo.add_model("new", files={"Existing.csv": "x\n"})
    assert run(repo, monkeypatch) == 1
    assert any("collides with" in e for e in errors(capsys))


def test_unconfigured_model_folder(repo, monkeypatch, capsys):
    repo.write("models/newType/x.csv", "x\n")
    assert run(repo, monkeypatch) == 1
    errs = errors(capsys)
    assert any("models/newType: no config" in e for e in errs)
    assert any("not inside a configured model folder" in e for e in errs)


def test_file_directly_in_models(repo, monkeypatch, capsys):
    repo.write("models/loose.csv", "x\n")
    assert run(repo, monkeypatch) == 1
    assert any("loose.csv: not inside a configured model folder" in e for e in errors(capsys))


def test_validation_command(repo, monkeypatch, capsys, jar):
    repo.set_validation("faultModels", VALIDATE)
    monkeypatch.setenv("ALLOW_NON_MODEL_CHANGES", "true")
    repo.commit("config")
    base = git(repo.path, "rev-parse", "HEAD").strip()

    repo.add_model("ok")
    assert run(repo, monkeypatch, base=base, jar=jar) == 0, errors(capsys)
    assert "running:" in capsys.readouterr().out

    repo.add_model("bad", crustal=False)
    assert run(repo, monkeypatch, base=base, jar=jar) == 1
    assert errors(capsys) == ["ERROR: models/faultModels/bad.meta.json: validation failed"]


def test_validation_needs_jar(repo, monkeypatch, capsys):
    repo.set_validation("faultModels", VALIDATE)
    monkeypatch.setenv("ALLOW_NON_MODEL_CHANGES", "true")
    repo.add_model("ok")
    assert run(repo, monkeypatch) == 1
    assert any("no --jar" in e for e in errors(capsys))


def test_validation_skipped_when_other_errors(repo, monkeypatch, capsys, jar):
    repo.set_validation("faultModels", VALIDATE)
    monkeypatch.setenv("ALLOW_NON_MODEL_CHANGES", "true")
    repo.add_model("bad", crustal=False)
    repo.write("models/faultModels/stray.csv", "s\n")
    assert run(repo, monkeypatch, jar=jar) == 1
    assert "running:" not in capsys.readouterr().out


def test_rules_come_from_rules_dir(repo, monkeypatch, capsys, tmp_path):
    """A PR that loosens its own schema is still checked against the rules checkout."""
    import shutil
    rules = tmp_path / "rules"
    shutil.copytree(repo.path / "config", rules / "config")
    monkeypatch.setenv("ALLOW_NON_MODEL_CHANGES", "true")
    p = "config/schema/meta.schema.json"
    schema = repo.read_json(p)
    schema["required"] = []
    repo.write_json(p, schema)
    m = repo.add_model("new")
    data = repo.read_json(m)
    del data["provenance"]
    repo.write_json(m, data)
    assert run(repo, monkeypatch, rules=rules) == 1
    assert any("provenance" in e for e in errors(capsys))
