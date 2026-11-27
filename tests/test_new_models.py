import os

import pytest

from model_checks import new_models
from model_checks.common import sha256

from .conftest import VALIDATE, git


def run(repo, monkeypatch, *args, cwd=None):
    monkeypatch.chdir(cwd or repo.path)
    monkeypatch.setattr("sys.argv", ["new-models", *args])
    with pytest.raises(SystemExit) as e:
        new_models.main()
    return e.value.code


def errors(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("ERROR")]


LOCAL = ("--base", "main")


def test_untracked_and_committed_models(repo, monkeypatch, capsys):
    committed = repo.add_model("committed", with_sha=False)
    repo.commit()
    staged = repo.add_model("staged", with_sha=False)
    git(repo.path, "add", "-A")
    untracked = repo.add_model("untracked", with_sha=False)

    assert run(repo, monkeypatch, *LOCAL) == 0, errors(capsys)
    for m in (committed, staged, untracked):
        entry = repo.read_json(m)["files"][0]
        assert entry["sha256"] == sha256(repo.path / os.path.dirname(m) / entry["path"])


def test_existing_meta_untouched(repo, monkeypatch, capsys):
    before = (repo.path / "models/faultModels/existing.meta.json").read_bytes()
    assert run(repo, monkeypatch, *LOCAL) == 0
    assert "(none)" in capsys.readouterr().out
    assert (repo.path / "models/faultModels/existing.meta.json").read_bytes() == before


def test_ignored_files_skipped(repo, monkeypatch, capsys):
    repo.write(".gitignore", "*.tmp\n")
    repo.write("models/faultModels/scratch.tmp", "x")
    assert run(repo, monkeypatch, *LOCAL) == 0, errors(capsys)


def test_check_mode(repo, monkeypatch, capsys):
    m = repo.add_model("new", with_sha=False)
    before = (repo.path / m).read_bytes()
    assert run(repo, monkeypatch, *LOCAL, "--check") == 1
    assert (repo.path / m).read_bytes() == before
    assert any("sha256 missing" in e for e in errors(capsys))


def test_check_and_strip_bom_exclusive(repo, monkeypatch):
    assert run(repo, monkeypatch, *LOCAL, "--check", "--strip-bom") == 2


@pytest.mark.parametrize("action, detail", [
    ("modify", "content changed"),
    ("delete", "deleted"),
    ("chmod", "file mode changed"),
])
def test_existing_files_immutable(repo, monkeypatch, capsys, action, detail):
    f = repo.path / "models/faultModels/existing.csv"
    if action == "modify":
        f.write_text("changed\n")
    elif action == "delete":
        f.unlink()
    else:
        os.chmod(f, 0o755)
    assert run(repo, monkeypatch, *LOCAL) == 1
    assert errors(capsys) == [
        f"ERROR: models/faultModels/existing.csv: existing files under models/ are immutable ({detail})"
    ]


def test_meta_change_rules(repo, monkeypatch, capsys):
    m = "models/faultModels/existing.meta.json"
    data = repo.read_json(m)
    data["owner"] = "new owner"
    repo.write_json(m, data)
    assert run(repo, monkeypatch, *LOCAL) == 0, errors(capsys)

    data["name"] = "renamed"
    repo.write_json(m, data)
    assert run(repo, monkeypatch, *LOCAL) == 1
    assert any("field 'name' is immutable" in e for e in errors(capsys))


def test_unlisted_new_file(repo, monkeypatch, capsys):
    repo.write("models/deformationModels/stray.csv", "s\n")
    assert run(repo, monkeypatch, *LOCAL) == 1
    assert errors(capsys) == ["ERROR: models/deformationModels/stray.csv: not listed in any new meta file"]


def test_bom(repo, monkeypatch, capsys):
    repo.add_model("new", files={"new.csv": b"\xef\xbb\xbfa\n"}, with_sha=False)
    assert run(repo, monkeypatch, *LOCAL) == 1
    assert any("BOM" in e for e in errors(capsys))

    assert run(repo, monkeypatch, *LOCAL, "--strip-bom") == 0, errors(capsys)
    assert (repo.path / "models/faultModels/new.csv").read_bytes() == b"a\n"
    assert run(repo, monkeypatch, *LOCAL, "--check") == 0, errors(capsys)


def test_validation(repo, monkeypatch, capsys, jar):
    repo.set_validation("faultModels", VALIDATE)
    repo.add_model("ok", with_sha=False)
    assert run(repo, monkeypatch, *LOCAL, "--jar", jar) == 0, errors(capsys)

    repo.add_model("bad", crustal=False, with_sha=False)
    assert run(repo, monkeypatch, *LOCAL, "--jar", jar) == 1
    assert errors(capsys) == ["ERROR: models/faultModels/bad.meta.json: validation failed"]


def test_no_jar_warns(repo, monkeypatch, capsys):
    assert run(repo, monkeypatch, *LOCAL) == 0
    assert "no --jar given" in capsys.readouterr().out


def test_runs_from_subdirectory(repo, monkeypatch, capsys):
    repo.add_model("new", with_sha=False)
    assert run(repo, monkeypatch, *LOCAL, cwd=repo.path / "models/faultModels") == 0, errors(capsys)


@pytest.fixture
def clone(repo, tmp_path):
    """Clone of repo (as origin, HEAD on main); origin then gets a new model the clone hasn't fetched."""
    git(repo.path, "checkout", "-q", "main")
    path = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(repo.path), str(path))
    repo.add_model("upstream")
    repo.commit("upstream model")
    return path


def test_default_base_fetches_origin(repo, clone, monkeypatch, capsys):
    from .conftest import Repo
    c = Repo(clone)
    # same file as the upstream model: once origin/main is fetched it's an existing file, not a new one
    c.add_model("upstream")
    assert run(c, monkeypatch, cwd=clone) == 0, errors(capsys)
    out = capsys.readouterr().out
    assert "fetching origin main" in out and "comparing against origin/main" in out
    assert "(none)" in out


def test_no_fetch_uses_stale_origin(repo, clone, monkeypatch, capsys):
    from .conftest import Repo
    c = Repo(clone)
    c.add_model("upstream")
    assert run(c, monkeypatch, "--no-fetch", cwd=clone) == 0, errors(capsys)
    out = capsys.readouterr().out
    assert "fetching" not in out
    assert "models/faultModels/upstream.meta.json" in out  # still new compared to the stale origin/main


def test_fetch_failure_warns(repo, clone, monkeypatch, capsys):
    git(clone, "remote", "set-url", "origin", str(clone.parent / "gone"))
    from .conftest import Repo
    assert run(Repo(clone), monkeypatch, cwd=clone) == 0
    assert "git fetch failed" in capsys.readouterr().out


def test_default_base_without_origin_head(repo, clone, monkeypatch, capsys):
    git(clone, "remote", "set-head", "origin", "--delete")
    from .conftest import Repo
    assert run(Repo(clone), monkeypatch, "--no-fetch", cwd=clone) == 0
    assert "comparing against origin/main" in capsys.readouterr().out
