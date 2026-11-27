"""Check a PR against the immutability and validation rules for models/.

--rules: checkout holding config/ (should be the BASE branch, so a PR can't relax its own checks)
--repo:  checkout of the PR head (data under test)
Env ALLOW_NON_MODEL_CHANGES=true allows changes outside models/ (set from a PR label).
Env ALLOW_MODEL_CHANGES=true turns changes to existing files under models/ into warnings
(set from the workflow_dispatch input modify_models).
"""
import argparse
import os
import sys

from .common import Report, load_configs, model_type, run_validation
from .rules import check_changes, git


def changes(repo, base):
    """[(status, path, detail)] of committed changes, renames disabled."""
    out = git(repo, "diff", "--raw", "--no-renames", "-z", f"{base}...HEAD").decode()
    parts = out.split("\0")
    result = []
    for meta, path in zip(parts[0:-1:2], parts[1::2]):
        old_mode, new_mode, _, _, status = meta.lstrip(":").split()
        if status == "M" and old_mode != new_mode:
            status = "mode"
        result.append((status, path, f"status {status}, mode {old_mode}->{new_mode}"))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--jar")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    allow_model = os.environ.get("ALLOW_MODEL_CHANGES") == "true"
    r = Report()

    def immutable(msg):
        if allow_model:
            r.warn(f"{msg} (allowed by modify_models)")
        else:
            r.err(msg)

    configs = load_configs(a.rules)
    all_paths = [p for p in git(repo, "ls-files", "-z", "models").decode().split("\0") if p]
    new_metas = check_changes(
        r, repo, a.base, configs, changes(repo, a.base), all_paths, immutable,
        allow_non_model=os.environ.get("ALLOW_NON_MODEL_CHANGES") == "true",
    )

    # run validation only if everything else passed
    if not r.errors:
        for path in new_metas:
            if not run_validation(r, repo, path, configs[model_type(path)], a.jar):
                break

    sys.exit(r.finish())


if __name__ == "__main__":
    main()
