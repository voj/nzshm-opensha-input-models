"""Shared helpers: configs, schemas, checksums, validation command."""
import hashlib
import json
import os
import posixpath
import subprocess
from pathlib import Path

import jsonschema

META_SUFFIX = ".meta.json"
MUTABLE_META_FIELDS = {"owner", "deprecated"}


class Report:
    def __init__(self):
        self.errors = []

    def err(self, msg):
        if msg in self.errors:  # several checks may find the same problem
            return
        self.errors.append(msg)
        print(f"ERROR: {msg}")

    def warn(self, msg):
        print(f"WARNING: {msg}")

    def finish(self):
        print(f"\n{len(self.errors)} error(s)" if self.errors else "\nOK")
        return 1 if self.errors else 0


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_configs(rules):
    """Model type configs keyed by folder name, with their schemas attached."""
    common = load_json(Path(rules, "config", "schema", "meta.schema.json"))
    configs = {}
    for p in sorted(Path(rules, "config", "models").glob("*.json")):
        cfg = load_json(p)
        cfg["_common"] = common
        cfg["_specific"] = load_json(Path(rules, cfg["metaSchema"]))
        configs[cfg["path"]] = cfg
    return configs


def model_type(path):
    """'models/<child>/...' -> '<child>', else None. `path` is repo-relative posix."""
    parts = path.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "models" else None


def file_path(meta_path, entry_path):
    """Repo-relative path of a file listed in a meta file."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(meta_path), entry_path))


def file_entries(meta):
    files = meta.get("files")
    if not isinstance(files, list):
        return []
    return [e for e in files if isinstance(e, dict) and isinstance(e.get("path"), str)]


def validate_meta(report, path, meta, cfg):
    for schema in (cfg["_common"], cfg["_specific"]):
        for e in jsonschema.Draft202012Validator(schema).iter_errors(meta):
            report.err(f"{path}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
    allowed = set(cfg["_common"]["properties"]) | set(cfg["_specific"].get("properties", {}))
    for k in sorted(set(meta) - allowed):
        report.err(f"{path}: unknown field '{k}'")


def check_replaced_by(report, repo, path, meta):
    dep = meta.get("deprecated")
    rb = dep.get("replacedBy") if isinstance(dep, dict) else None
    if rb and not (rb.endswith(META_SUFFIX) and Path(repo, rb).is_file()):
        report.err(f"{path}: replacedBy '{rb}' is not an existing meta file")


UTF8_BOM = b"\xef\xbb\xbf"
# longest first: the UTF-32 LE BOM starts with the UTF-16 LE BOM
BOMS = [
    (b"\x00\x00\xfe\xff", "UTF-32 BE"),
    (b"\xff\xfe\x00\x00", "UTF-32 LE"),
    (UTF8_BOM, "UTF-8"),
    (b"\xfe\xff", "UTF-16 BE"),
    (b"\xff\xfe", "UTF-16 LE"),
]


def bom(path):
    """Name of the byte order mark the file starts with, or None."""
    with open(path, "rb") as f:
        head = f.read(4)
    return next((name for b, name in BOMS if head.startswith(b)), None)


def check_bom(report, path, repo="."):
    """Error if the repo-relative file starts with a BOM."""
    name = bom(Path(repo, path))
    if name:
        report.err(f"{path}: starts with a {name} byte order mark (BOM); remove it")


def strip_bom(report, path, repo="."):
    """Remove a UTF-8 BOM in place. Other BOMs can't be stripped safely (the file isn't UTF-8)."""
    full = Path(repo, path)
    name = bom(full)
    if name == "UTF-8":
        full.write_bytes(full.read_bytes()[len(UTF8_BOM):])
        print(f"{path}: UTF-8 BOM removed")
    elif name:
        report.err(f"{path}: starts with a {name} BOM; convert the file to UTF-8 without BOM")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_validation(report, repo, path, cfg, jar):
    """Run the type's validation command for one meta file. Returns False if it couldn't run."""
    cmd = cfg.get("validation")
    if not cmd:
        report.warn(f"{path}: no validation configured for {cfg['path']}")
        return True
    if not jar:
        report.err("validation configured but no --jar given")
        return False
    argv = [c.format(jar=os.path.abspath(jar), meta=path, repo=repo) for c in cmd]
    print(f"running: {' '.join(argv)}", flush=True)  # flush before the child writes to stdout
    if subprocess.run(argv, cwd=repo).returncode != 0:
        report.err(f"{path}: validation failed")
    return True
