"""Fill in sha256 checksums of a meta file's listed files and validate it.

Example: model-meta models/faultModels/cfm_1_1_all.xml.meta.json

Each entry in "files" needs a "path" (relative to the meta file); "sha256" is computed and
written. Then the meta file is validated against the common and type-specific schemas and,
with --jar, the type's validation command is run.
"""
import argparse
import json
import sys
from pathlib import Path

from .common import (
    META_SUFFIX,
    Report,
    check_bom,
    check_replaced_by,
    file_entries,
    file_path,
    load_configs,
    model_type,
    run_validation,
    sha256,
    strip_bom,
    validate_meta,
)


def find_repo(start):
    for d in [start, *start.parents]:
        if (d / "config" / "models").is_dir() and (d / "models").is_dir():
            return d
    return None


def process(r, metas, check=False, jar=None, remove_bom=False):
    """Fill in checksums (unless check) and validate each meta file; problems go to report r.

    remove_bom: strip UTF-8 BOMs from the meta file and its listed files first (ignored with check).
    """
    configs = {}
    for arg in metas:
        meta_file = Path(arg).resolve()
        repo = find_repo(meta_file.parent)
        if repo is None:
            r.err(f"{arg}: not inside the model repo (no config/models and models/ found above it)")
            continue
        configs.setdefault(repo, load_configs(repo))
        path = meta_file.relative_to(repo).as_posix()
        if not path.endswith(META_SUFFIX):
            r.err(f"{path}: meta file name must end with {META_SUFFIX}")
            continue
        cfg = configs[repo].get(model_type(path))
        if cfg is None:
            r.err(f"{path}: not inside a configured model folder (models/<type>/ with config/models/<type>.json)")
            continue
        if not meta_file.is_file():
            r.err(f"{path}: not found")
            continue
        n_errors = len(r.errors)
        (strip_bom if remove_bom and not check else check_bom)(r, path, repo)
        if len(r.errors) > n_errors:
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            r.err(f"{path}: invalid JSON: {e}")
            continue
        except OSError as e:
            r.err(f"{path}: {e}")
            continue

        n_errors = len(r.errors)
        changed = False
        for entry in file_entries(meta):
            fp = file_path(path, entry["path"])
            if not fp.startswith("models/") or not Path(repo, fp).is_file():
                r.err(f"{path}: listed file {fp} not found")
                continue
            (strip_bom if remove_bom and not check else check_bom)(r, fp, repo)
            digest = sha256(Path(repo, fp))
            if entry.get("sha256") == digest:
                continue
            if check:
                r.err(f"{path}: sha256 {'missing' if 'sha256' not in entry else 'mismatch'} for {fp}")
            else:
                entry["sha256"] = digest
                changed = True
                print(f"{path}: sha256 set for {fp}")

        validate_meta(r, path, meta, cfg)
        check_replaced_by(r, repo, path, meta)

        # only rewrite when a checksum changed, so formatting of untouched files is kept
        if changed:
            meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{path}: written")

        if len(r.errors) == n_errors and jar:
            run_validation(r, str(repo), path, cfg, jar)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("meta", nargs="+", help="meta file(s), *.meta.json")
    ap.add_argument("--check", action="store_true", help="don't write; fail if a checksum is missing or wrong")
    ap.add_argument("--jar", help="nzshm-opensha jar; runs the type's validation command")
    a = ap.parse_args()
    r = Report()
    process(r, a.meta, check=a.check, jar=a.jar)
    sys.exit(r.finish())


if __name__ == "__main__":
    main()
