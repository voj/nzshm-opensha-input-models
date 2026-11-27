"""Fixtures: a throwaway git repo with the real config/ and a few existing models on main."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from model_checks.common import Report, sha256

PROJECT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class Repo:
    def __init__(self, path):
        self.path = path

    def write(self, rel, content):
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        return p

    def write_json(self, rel, data):
        return self.write(rel, json.dumps(data, indent=2) + "\n")

    def read_json(self, rel):
        return json.loads((self.path / rel).read_text(encoding="utf-8"))

    def add_model(self, name, folder="models/faultModels", files=None, with_sha=True, **extra):
        """Write data files and a meta file; returns the meta file's repo-relative path."""
        files = files if files is not None else {f"{name}.csv": f"{name},data\n"}
        entries = []
        for fname, content in files.items():
            p = self.write(f"{folder}/{fname}", content)
            entry = {"path": fname}
            if with_sha:
                entry["sha256"] = sha256(p)
            entries.append(entry)
        meta = fault_meta(name, entries) if folder.startswith("models/faultModels") else deformation_meta(name, entries)
        meta.update(extra)
        meta_path = f"{folder}/{name}.meta.json"
        self.write_json(meta_path, meta)
        return meta_path

    def commit(self, msg="commit"):
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "--allow-empty", "-m", msg)

    def set_validation(self, folder, cmd):
        p = f"config/models/{folder}.json"
        cfg = self.read_json(p)
        cfg["validation"] = cmd
        self.write_json(p, cfg)


def common_meta(name, entries):
    return {
        "name": name,
        "description": "test model",
        "date": "2026-11",
        "provenance": "unknown",
        "owner": "unknown",
        "files": entries,
    }


def fault_meta(name, entries):
    return {**common_meta(name, entries), "modelName": name, "crustal": True, "partition": "CRUSTAL"}


def deformation_meta(name, entries):
    return {**common_meta(name, entries), "compatibility": "FaultModel X"}


# validation command that passes iff the meta file's "crustal" is true (deformation: always passes)
VALIDATE = [
    sys.executable,
    "-c",
    "import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get('crustal', True) else 3)",
    "{meta}",
    "{jar}",
]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repo with config/ and two existing models committed on main, checked out on branch 'work'."""
    for k, v in {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("ALLOW_MODEL_CHANGES", "ALLOW_NON_MODEL_CHANGES"):
        monkeypatch.delenv(k, raising=False)

    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    shutil.copytree(PROJECT / "config", path / "config")
    r = Repo(path)
    r.write(".gitattributes", "* -text\n")
    r.write("README.md", "readme\n")
    r.add_model("existing")
    r.add_model("existing_dm", folder="models/deformationModels")
    r.commit("base")
    git(path, "checkout", "-q", "-b", "work")
    return r


@pytest.fixture
def report():
    return Report()


@pytest.fixture
def jar(tmp_path):
    p = tmp_path / "fake.jar"
    p.write_bytes(b"jar")
    return str(p)
