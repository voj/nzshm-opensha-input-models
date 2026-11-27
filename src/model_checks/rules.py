"""The repo rules, applied to a list of changes against a base ref.

Shared by check-pr (committed changes of a PR) and new-models (working tree).
"""
import json
import subprocess
from pathlib import Path

from .common import (
    META_SUFFIX,
    MUTABLE_META_FIELDS,
    check_bom,
    check_replaced_by,
    file_entries,
    file_path,
    load_json,
    model_type,
    sha256,
    validate_meta,
)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def check_changes(r, repo, base, configs, changes, all_paths, immutable, allow_non_model=False):
    """Apply all rules except the jar validation. Returns the new meta files.

    changes:   [(status, path, detail)], status "A" (added), "M" (content modified),
               anything else is a disallowed change (deleted, mode change, ...); detail for messages
    all_paths: every file under models/ in the checked tree (for case collisions)
    immutable: callback for changes to existing data (error, or warning when overridden)
    """
    # every direct child of models/ needs a config
    for child in sorted(p.name for p in Path(repo, "models").iterdir() if p.is_dir()):
        if child not in configs:
            r.err(f"models/{child}: no config in config/models/")

    added, modified_meta = [], []
    for status, path, detail in changes:
        if not path.startswith("models/"):
            if not allow_non_model:
                r.err(f"{path}: change outside models/ needs the 'allow-non-model-changes' label")
            continue
        if model_type(path) not in configs:
            r.err(f"{path}: not inside a configured model folder")
            continue
        if status == "A":
            added.append(path)
        elif status == "M" and path.endswith(META_SUFFIX):
            modified_meta.append(path)
        else:
            immutable(f"{path}: existing files under models/ are immutable ({detail})")

    # case-insensitive collisions
    added_set = set(added)
    seen = {}
    for p in sorted(all_paths):
        other = seen.setdefault(p.lower(), p)
        if other != p and (p in added_set or other in added_set):
            r.err(f"{p}: collides with {other} on case-insensitive filesystems")

    # no byte order marks in new files or changed meta files
    for path in added + modified_meta:
        check_bom(r, path, repo)

    # modified meta: only mutable fields may change
    for path in modified_meta:
        try:
            old = json.loads(git(repo, "show", f"{base}:{path}"))
            new = load_json(Path(repo, path))
        except json.JSONDecodeError as e:
            r.err(f"{path}: invalid JSON: {e}")
            continue
        for k in sorted((set(old) | set(new)) - MUTABLE_META_FIELDS):
            if old.get(k) != new.get(k):
                immutable(f"{path}: field '{k}' is immutable")
        validate_meta(r, path, new, configs[model_type(path)])
        check_replaced_by(r, repo, path, new)

    # new models
    new_metas = [p for p in added if p.endswith(META_SUFFIX)]
    claimed = {}
    for path in new_metas:
        try:
            meta = load_json(Path(repo, path))
        except json.JSONDecodeError as e:
            r.err(f"{path}: invalid JSON: {e}")
            continue
        validate_meta(r, path, meta, configs[model_type(path)])
        check_replaced_by(r, repo, path, meta)
        for entry in file_entries(meta):
            fp = file_path(path, entry["path"])
            if fp in claimed:
                r.err(f"{path}: {fp} already listed by {claimed[fp]}")
            claimed[fp] = path
            if fp not in added_set:
                r.err(f"{path}: listed file {fp} is not new (exists in {base}) or not found")
            elif sha256(Path(repo, fp)) != entry.get("sha256"):
                r.err(f"{path}: sha256 mismatch for {fp}")

    for path in added:
        if not path.endswith(META_SUFFIX) and path not in claimed:
            r.err(f"{path}: not listed in any new meta file")

    return new_metas
