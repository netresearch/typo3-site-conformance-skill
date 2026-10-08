<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# typo3-site-conformance-skill

Agent skill for assessing and hardening deployable TYPO3 site/project repositories (`composer.json` type `project` plus Docker/Compose). It ships a rule catalogue and a self-contained checker, `check.py`.

## Repo Structure

```
skills/typo3-site-conformance/
  SKILL.md                skill definition and trigger description
  references/             migration, sealed settings.php and database seed guides
  checker/check.py        the checker (PyYAML declared as PEP 723 script metadata)
  checker/gen_rules.py    generates rules.json from the pinned rule catalogue
  checker/rules.json      generated rule catalogue
  checker/README.md       checker scope model and scoring
tests/test_check.py       unittest suite for check.py and gen_rules.py
evals/evals.json          eval cases for the skill
docs/ARCHITECTURE.md      components and data flow of the checker
docs/SECURITY-ASSURANCE.md  threat model, trust boundaries, countermeasures
plugin.json               Agent Plugins manifest
.claude-plugin/plugin.json  Claude Code manifest
composer.json             Composer distribution metadata
.github/workflows/        CI callers of reusable workflows
```

## Commands

- Run the checker: `python3 skills/typo3-site-conformance/checker/check.py <repo-path>` (or `uv run` on the same file)
- Tests: `python3 tests/test_check.py` (needs Python 3 and PyYAML; CI runs `tests/*.py` through `.github/workflows/tests.yml`)
- Regenerate the catalogue: `python3 skills/typo3-site-conformance/checker/gen_rules.py` (writes `rules.json` and warns when `CATALOGUE_SHA256` is stale)
- Skill validation: `bash validate-skill.sh .` from `skill-repo-skill`, as the README's Contributing section says

## Rules

- Licensing is split: code, configuration and workflows are MIT ([LICENSE-MIT](LICENSE-MIT)); documentation and skill content are CC-BY-SA-4.0 ([LICENSE-CC-BY-SA-4.0](LICENSE-CC-BY-SA-4.0)). `composer.json` and both manifests declare `(MIT AND CC-BY-SA-4.0)`.
- Keep `plugin.json` and `.claude-plugin/plugin.json` in step; Skill Validation checks that they agree ([docs/SECURITY-ASSURANCE.md](docs/SECURITY-ASSURANCE.md)).
- Change a rule in `checker/gen_rules.py`, then regenerate `rules.json`; a change to `check.py` or `gen_rules.py` comes with a test in `tests/test_check.py` that fails without it ([README.md](README.md#contributing)).
- The workflow files that also exist in the `skill` template of `netresearch/.github` are governed by it; `.github/template.yaml` lists the intentional exception (`lint.yml`, ShellCheck severity `style`). Template Drift fails when a governed file differs.
- Reusable workflows are called by `@main` from `netresearch/.github`, `netresearch/skill-repo-skill` and `netresearch/typo3-ci-workflows`.
- Branch protection on `main` requires the checks `Skill Validation / Skill Validation`, `Analyze (actions)`, `DCO` and `tests / Skill Tests` (read with `gh api repos/netresearch/typo3-site-conformance-skill/branches/main/protection`); commits carry a `Signed-off-by` trailer (`git commit -s`).

## References

- [README.md](README.md): usage, tests, dependencies, checks that run on pull requests
- [skills/typo3-site-conformance/SKILL.md](skills/typo3-site-conformance/SKILL.md): skill content
