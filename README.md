# NZSHM Input Models

This repo contains all NZSHM input models such as the fault model, deformation models, paleo rates, etc.

Files are read directly from raw URLs on `main`, e.g.
`https://raw.githubusercontent.com/voj/nzshm-opensha-input-models/refs/heads/main/models/faultModels/<file>`.
To keep those URLs stable, **files under `models/` are immutable**: they can be added, never changed,
renamed or deleted. Every pull request is checked by the `check-models` workflow.
GitHub configuration is described in [docs/setup.md](docs/setup.md).

## Layout

- `models/<type>/...` model data. Each direct child of `models/` is a model type; subfolders are allowed.
- `config/models/<type>.json` config per model type: meta schema and validation command.
- `config/schema/` JSON schemas for meta files (common + one per type).
- `config/validator.json` nzshm-opensha jar used for validation.
- `src/model_checks/` uv project with the CLI tools `check-pr` (run on every PR), `new-models` and `model-meta`; tests in `tests/`.

## Adding a model

1. Add the data file(s) somewhere under the matching `models/<type>/` folder.
2. Add a meta file next to them, named `<something>.meta.json`. It must list every file of the model,
   with paths relative to the meta file. Leave out `sha256`, it is filled in by `model-meta` (step 3):

   ```json
   {
     "name": "cfm_1_1_all",
     "description": "What the model is and how it differs from others.",
     "date": "2026-11",
     "provenance": "Where the data came from (free text).",
     "owner": "Who is responsible for it (free text).",
     "files": [
       {"path": "cfm_1_1_all.xml"},
       {"path": "cfm_1_1_all.xml.FaultsByNameAlt.txt"}
     ],
     "modelName": "...",
     "crustal": true,
     "partition": "CRUSTAL"
   }
   ```

   - `date` may be `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.
   - Type-specific fields (here `modelName`, `crustal`, `partition`) are defined in
     `config/schema/<type>.schema.json`. Unknown fields are rejected.
3. Fill in the checksums and validate all new meta files (see [Tools](#tools)):

   ```sh
   uv run --locked new-models --jar <path/to/nzshm-opensha-all.jar>
   ```

4. Commit and open a PR. Several models can be added in one PR. The check verifies that:
   - only new files are added under `models/`;
   - every new file is listed in exactly one new meta file and its checksum matches;
   - no new file starts with a byte order mark (BOM);
   - meta files match the schemas;
   - the model passes the validation command for its type (nzshm-opensha jar).

## Tools

Requires [uv](https://docs.astral.sh/uv/). Dependencies are resolved with a 1-week cutoff
(`exclude-newer` in `pyproject.toml`, pinned in `uv.lock`): packages uploaded less than a week ago are
never installed. Use `--locked` so the lock file is used as is.

```sh
uv sync --locked

# fetch origin/main, then check the working tree (committed or not) like the PR check does:
# fill in sha256 of new meta files, validate them, and report changed, deleted or unlisted files
uv run --locked new-models --jar <path/to/nzshm-opensha-all.jar>
# also remove UTF-8 BOMs from new files first (UTF-16/32 files must be converted by hand)
uv run --locked new-models --strip-bom --jar <path/to/nzshm-opensha-all.jar>
# only verify, don't write; offline (no fetch) or against another base
uv run --locked new-models --check --no-fetch
uv run --locked new-models --check --base <ref>

# fill in sha256 of the listed files of given meta files and validate (several at once are fine)
uv run --locked model-meta models/<type>/<file>.meta.json
# only verify, don't write
uv run --locked model-meta --check models/<type>/<file>.meta.json
# also run the nzshm-opensha validation
uv run --locked model-meta --jar <path/to/nzshm-opensha-all.jar> models/<type>/<file>.meta.json

# run the PR check locally against main (only sees committed changes)
uv run --locked check-pr --rules . --repo . --base origin/main --jar <path/to/nzshm-opensha-all.jar>
```

Tests:

```sh
uv run --locked pytest        # quick
uv run --locked tox           # all Python versions, as in CI
```

`model-meta` only rewrites a meta file if a checksum was added or changed. Don't run it on meta
files that are already on `main`: their checksums must not change.

## Changing metadata

Only these fields of an existing meta file may be changed:

- `owner`
- `deprecated`: mark a model as deprecated (can be edited later):

  ```json
  "deprecated": {"date": "2026-11", "reason": "Superseded by v2.", "replacedBy": "models/faultModels/cfm_1_1_all.meta.json"}
  ```

  `replacedBy` is optional and must point to an existing meta file (repo-relative path).

Deprecated models stay in place; don't move them to another folder.

## Changing files outside `models/`

Changes to the README, configs, schemas, scripts or workflows fail the check unless the PR has the
`allow-non-model-changes` label (requires write access). The rules are always taken from the base
branch, so a PR changing them is still checked against the current rules.

Adding a new model type: create `models/<type>/`, `config/models/<type>.json` and
`config/schema/<type>.schema.json` in a labelled PR. Models of that type can be added once it is merged.

## Circumventing the immutability check

Only for exceptional cases, e.g. data that must be removed for legal reasons or was committed by
mistake. Changing or removing a file breaks every consumer of its raw URL.

1. Open a PR with the change. The `check-models` check fails.
2. Run the check manually on the PR branch with `modify_models` set: Actions → check-models →
   Run workflow → select the branch → tick "Do not fail on modified models", or

   ```sh
   gh workflow run check-models.yml --ref <pr-branch> -f modify_models=true
   ```

   Changes to existing files under `models/` are then reported as warnings instead of errors.
   All other checks still apply.
3. Merge once the manual run has passed. Any new push to the branch runs the normal check again,
   so the override has to be repeated after every push.

Never force-push to `main`: history must stay intact.
