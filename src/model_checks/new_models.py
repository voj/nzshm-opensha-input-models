"""Check the working tree against the base branch, like the PR check does, before committing.

New meta files (in the working tree, committed or not, not git-ignored, and not in the base) get
their checksums filled in and are validated. All files under models/ are checked against the
repo rules: no changed or deleted existing files, every new file listed in a new meta file, no
BOMs, no case collisions. Run from anywhere inside the repo.

The base defaults to origin's default branch, fetched first.

Example: new-models --jar nzshm-opensha-all.jar
"""
import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

from .common import META_SUFFIX, Report, load_configs, model_type, run_validation
from .meta import process
from .rules import check_changes, git


def default_base(repo, fetch, r):
    try:
        ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").decode().strip()
    except subprocess.CalledProcessError:
        ref = "origin/main"
    if fetch:
        branch = ref.split("/", 1)[1]
        print(f"fetching origin {branch} ...", flush=True)
        try:
            git(repo, "fetch", "--quiet", "origin", branch)
        except subprocess.CalledProcessError as e:
            r.warn(f"git fetch failed, using the local {ref}: {e.stderr.decode().strip()}")
    return ref


def worktree_changes(repo, base):
    """[(status, path, detail)] of the working tree under models/ against base, plus all local paths."""
    in_base = {}
    for line in git(repo, "ls-tree", "-r", "-z", base, "--", "models").decode().split("\0"):
        if line:
            info, path = line.split("\t", 1)
            mode, _, blob = info.split()
            in_base[path] = (mode, blob)

    out = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "models").decode()
    local = sorted({p for p in out.split("\0") if p and Path(repo, p).is_file()})

    existing = [p for p in local if p in in_base]
    blobs = []
    if existing:
        blobs = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "--stdin-paths"],
            input="\n".join(existing) + "\n", check=True, capture_output=True, text=True,
        ).stdout.split()

    changes = [("A", p, "new") for p in local if p not in in_base]
    for p, blob in zip(existing, blobs):
        mode, base_blob = in_base[p]
        executable = bool(os.stat(Path(repo, p)).st_mode & stat.S_IXUSR)
        if blob != base_blob:
            changes.append(("M", p, "content changed"))
        elif executable != (mode == "100755"):
            changes.append(("mode", p, "file mode changed"))
    local_set = set(local)
    changes += [("D", p, "deleted") for p in in_base if p not in local_set]
    return changes, local


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="ref to compare against (default: origin's default branch, fetched first)")
    ap.add_argument("--no-fetch", action="store_true", help="don't fetch the default base first")
    ap.add_argument("--check", action="store_true", help="don't write; fail if a checksum is missing or wrong")
    ap.add_argument("--jar", help="nzshm-opensha jar; runs the type's validation command")
    ap.add_argument("--strip-bom", action="store_true",
                    help="remove UTF-8 byte order marks from new meta files and their listed files")
    a = ap.parse_args()
    if a.check and a.strip_bom:
        ap.error("--check and --strip-bom can't be combined")

    r = Report()
    repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    base = a.base or default_base(repo, not a.no_fetch, r)
    print(f"comparing against {base}\n")

    changes, local = worktree_changes(repo, base)
    metas = [p for s, p, _ in changes if s == "A" and p.endswith(META_SUFFIX)]
    print("new meta files:\n  " + ("\n  ".join(metas) or "(none)") + "\n")
    if not a.jar:
        r.warn("no --jar given: the nzshm-opensha validation is not run")

    # fill in checksums / strip BOMs first, then apply the same rules as the PR check
    process(r, [str(repo / p) for p in metas], check=a.check, remove_bom=a.strip_bom)
    configs = load_configs(repo)
    check_changes(r, repo, base, configs, changes, local, immutable=r.err, allow_non_model=True)

    if not r.errors and a.jar:
        for path in metas:
            if not run_validation(r, str(repo), path, configs[model_type(path)], a.jar):
                break

    sys.exit(r.finish())


if __name__ == "__main__":
    main()
