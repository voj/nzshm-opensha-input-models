# GitHub setup

One-off configuration needed for the `check-models` workflow to actually enforce immutability.
Without these settings the check is advisory only.

## 1. Actions

Settings → Actions → General:

- **Actions permissions:** make sure these are allowed: `actions/checkout`,
  `GNS-Science/nshm-github-actions/.github/actions/python-install-uv` and the actions it uses
  (`actions/setup-python`, `astral-sh/setup-uv`). Java comes preinstalled on the runner.
  The `tests` workflow uses the reusable workflow
  `GNS-Science/nshm-github-actions/.github/workflows/python-run-tests-uv.yml`, which additionally
  uses `codecov/codecov-action` and `slackapi/slack-github-action` (the latter only for scheduled runs).
- **Workflow permissions:** "Read repository contents and packages permissions".
  The workflow additionally requests `pull-requests: read` itself, to look up PR labels in manual runs.
- **Fork pull request workflows:** require approval for outside contributors, so a maintainer
  looks at a fork PR before it runs the validator.

## 2. Validator jar

Edit `config/validator.json`:

- `url`: download URL of the nzshm-opensha fatjar (https).
- `sha256`: `sha256sum nzshm-opensha-all.jar`.
- `java`: Java major version; must be preinstalled on the runner image
  (`JAVA_HOME_<version>_X64`).

If the bucket is private, add AWS credentials as repository secrets
(Settings → Secrets and variables → Actions) and replace the `curl` in
`.github/workflows/check-models.yml` with an authenticated download.

Set the `validation` command in each `config/models/*.json`, e.g.

```json
"validation": ["java", "-jar", "{jar}", "<subcommand>", "{meta}"]
```

`{jar}`, `{meta}` (repo-relative meta file path) and `{repo}` (repo root) are substituted.
The command runs from the repo root; exit code 0 means the model is accepted.

Optional: add a `CODECOV_TOKEN` repository secret for coverage reports, then set
`fail-on-codecov-error: true` in `.github/workflows/tests.yml`.

## 3. Label

Create the label that allows PRs to change files outside `models/`:

```sh
gh label create allow-non-model-changes --description "PR may change files outside models/"
```

Only users with write access can apply labels.

## 4. CODEOWNERS

Create `.github/CODEOWNERS` so changes to the rules need a maintainer's review
(replace the handles):

```
/config/   @<maintainer>
/src/      @<maintainer>
/pyproject.toml @<maintainer>
/uv.lock   @<maintainer>
/tests/    @<maintainer>
/tox.ini   @<maintainer>
/.github/  @<maintainer>
/docs/     @<maintainer>
```

## 5. Ruleset for `main`

The check must have run at least once (open any PR) before it can be selected below.

Settings → Rules → Rulesets → New ruleset → New branch ruleset:

- **Name:** `protect-main`
- **Enforcement status:** Active
- **Bypass list:** leave empty, including admins. The only escape hatch is the manual
  `modify_models` run described in the README.
- **Target branches:** Include default branch.
- **Rules:**
  - Restrict deletions
  - Block force pushes
  - Require a pull request before merging
    - Required approvals: 1
    - Require review from Code Owners
    - Dismiss stale pull request approvals when new commits are pushed
  - Require status checks to pass
    - Add `check-models` (source: GitHub Actions)
    - Add the test jobs, e.g. `tests / run_unit_tests (3.12, ubuntu-latest)`, one per Python version
    - Require branches to be up to date before merging

Blocking force pushes and deletions matters most: consumers read files from raw URLs on `main`,
so history must never be rewritten.

## 6. Verify

Open test PRs and confirm:

- adding a valid model passes;
- editing an existing data file fails;
- editing `README.md` fails without the label and passes with it;
- the merge button is blocked while the check fails, also for admins;
- a manual run with `modify_models` on a branch with a modified data file passes and unblocks
  the merge (manual runs report under the same `check-models` name on the branch's head commit).
