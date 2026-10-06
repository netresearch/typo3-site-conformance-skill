<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Security Assurance Case

This document states what users of the typo3-site-conformance skill can and cannot expect in terms of security, and argues why the expectations hold. Every claim names the file that implements it. The components and data flows are described in [ARCHITECTURE.md](ARCHITECTURE.md). Vulnerabilities are reported privately as described in the [organisation security policy](https://github.com/netresearch/.github/blob/main/SECURITY.md).

## What the project ships

| Part | Files | Runs code? |
|------|-------|------------|
| Skill instructions and references | `skills/typo3-site-conformance/SKILL.md`, `skills/typo3-site-conformance/references/*.md` | No. Text an AI agent loads. |
| Rule catalogue | `skills/typo3-site-conformance/checker/rules.json` | No. Data read by the checker. |
| Checker | `skills/typo3-site-conformance/checker/check.py` | Yes. Python, run by the user or the agent against a target repository. |
| Catalogue generator | `skills/typo3-site-conformance/checker/gen_rules.py` | Yes, for maintainers: writes `rules.json`. |
| Tests | `tests/test_check.py` | Yes, for maintainers and CI only. |

## Security requirements

1. `check.py` treats the target repository as data. It installs nothing, writes no file, opens no network connection and does not evaluate target file content as code.
2. The rule catalogue a user runs is the reviewed catalogue: `rules.json` matches `gen_rules.py`, and `gen_rules.py` matches its pinned hash.
3. The skill and its releases are delivered unmodified from this repository.
4. Changes to `main` are proposed as pull requests, on which the checks listed in [README.md](../README.md#governance-and-policies) run. Branch protection of `main` requires a subset of them and does not bind administrators.

## Actors and trust boundaries

- **User**: chooses the repository to assess and runs the checker, or asks an agent to. Trusted.
- **AI agent**: loads `SKILL.md` and the references, runs the checker and, when asked to harden a repository, edits it (SKILL.md, Workflow steps 2 and 4). It acts with the user's permissions and the tools the user's agent platform grants.
- **Target repository**: input for the checker. `check.py` parses its files as text, YAML or JSON and asks `git` which of them are tracked.
- **Maintainers and CI**: change and release this repository.

Boundary 1 lies between the checker and the target repository: file content is parsed as text, YAML or JSON and matched with regular expressions. Boundary 2 lies between this repository and the user's machine: releases are built and signed in CI.

## Argument per requirement

### 1. The checker treats the target as data

- `check.py` reads files with `pathlib.Path.read_text` and `os.walk`; it has no call that writes a file, and it imports no network module (`json`, `os`, `pathlib`, `re`, `subprocess`, `sys`, `yaml`).
- YAML is loaded with `yaml.SafeLoader` (`compose.yaml`) or with `_Loader`, a subclass that maps every unknown tag to `None` (`compose.override.yaml`, `ci/pipeline.yml`; `check.py`, `_Loader`), so a document cannot construct Python objects. A YAML or JSON syntax error makes the file count as absent instead of stopping the run; undecodable bytes are replaced. A YAML document whose aliases expand to more than 100,000 nodes counts as absent too (`_within_node_budget`); the largest compose and Concourse files measured expand to about 1,100.
- The only external program is `git`, started with an argument list and no shell: `git -C <root> ls-files` and `git -C <root> ls-files --error-unmatch .env`, each with a timeout (`Ctx.git_tracked`, `Ctx.git_ls_files`). Both run through `_project_git` with `core.fsmonitor=false`, `core.hooksPath=/dev/null` and `GIT_CONFIG_NOSYSTEM=1`, so a command the target's own `.git/config` names for these does not run.
- The result is a report on standard output and the exit code; `tests/test_check.py` runs the command line against a fixture repository and asserts both. Text from the target in that report (its directory name, the details of a rule) is printed with control and bidirectional formatting characters replaced by `?` (`_printable`).

### 2. The catalogue is the reviewed catalogue

- `gen_rules.py` recomputes the SHA-256 of the inline rules and prints a drift warning when it differs from `CATALOGUE_SHA256`.
- `tests/test_check.py` asserts that the hash matches, that a copy of `gen_rules.py` reproduces the committed `rules.json` byte for byte, that every repo-scope rule has a check in `check.CHECKS` (so no rule is silently reported as `SKIP`), and that each check fails on a fixture that violates it.

### 3. Delivered content is the reviewed content

- Releases are built by `.github/workflows/release.yml`, which calls the `netresearch/skill-repo-skill` release workflow with `id-token: write` and `attestations: write`. That workflow signs `SHA256SUMS.txt` keyless with `cosign sign-blob` and attests the release archives and checksums with `actions/attest-build-provenance`.
- The Skill Validation job checks that `plugin.json` and `.claude-plugin/plugin.json` agree and that the `SKILL.md` version matches the plugin version.

### 4. Pull requests run automated checks

`lint.yml`, `eval-validate.yml` and `tests.yml` grant `contents: read` only. `auto-merge-deps.yml` runs on `pull_request_target` and calls the shared workflow in `netresearch/.github`, which contains no checkout step and runs no pull request code; this repository passes it no secrets. The checks themselves are listed in [README.md](../README.md#governance-and-policies).

## Common weaknesses

| Weakness | Where it could arise | Countermeasure |
|----------|---------------------|----------------|
| CWE-502 deserialization of untrusted data | YAML in the target repository | `yaml.SafeLoader`, or its subclass `_Loader` in which unknown tags become `None` (`check.py`). |
| CWE-78 OS command injection | Target path and file names | `git` is started with an argument list, no shell; no command string is built from input (`check.py`, `Ctx.git_tracked`, `Ctx.git_ls_files`). |
| CWE-829 functionality from an untrusted control sphere | The target's `.git/config` (fsmonitor command, hooks) | `_project_git` turns both off and skips the system config; `tests/test_check.py` (`test_git_config_of_the_target_names_no_command_that_runs`). |
| CWE-776 unbounded expansion of references | YAML aliases in the target | `_within_node_budget` treats a document above 100,000 expanded nodes as absent (`test_alias_expansion_beyond_the_budget_reads_as_malformed`). |
| CWE-150 escape sequences in output | Target text in the report | `_printable` replaces control characters (`test_report_carries_no_control_characters_from_the_target`). |
| CWE-94 code injection | PHP, YAML and Dockerfile content of the target | Content is matched with regular expressions and parsed as data; the checker does not `eval`, `exec` or import anything from the target. |
| CWE-1104 unmaintained third-party components | PyYAML, GitHub Actions | PyYAML, the only third-party Python dependency, is declared in `check.py`'s PEP 723 block and resolved by the user's installer; the shared workflows this repository calls pin third-party actions by commit SHA. |
| CWE-798 secret exposure | Commits to this repository | GitHub secret scanning with push protection is enabled for the repository. No script reads or stores credentials. |

## What the skill does not protect against

- **A passing score is not a security verdict.** The checker is a static structural heuristic. A 100 % score shows that the gold-standard structure is present, not that the target is secure; `checker/README.md` ("A heuristic, not a security control") lists the known limits.
- **The catalogue mirrors a snapshot.** The published ruleset is OAuth-gated, so parity is asserted against `CATALOGUE_SNAPSHOT` and `CATALOGUE_SHA256` in `gen_rules.py`, not re-fetched.
- **Changes the agent makes.** Hardening a repository means the agent edits it with the user's permissions. Review the changes before committing them.
- **`allowed-tools`.** `SKILL.md` declares none. Where a skill declares `allowed-tools`, it only pre-approves tools; it does not remove tools the agent already has.
- **Arguments.** The checker trusts its argument; it is meant to be the path of a repository the user chose to assess.
- **Release archives.** The shared release workflow copies a skill's `SKILL.md`, `references`, `scripts`, `assets`, `templates`, `examples` and `checkpoints.yaml`, not `checker/`, so the release archives do not contain the checker (netresearch/skill-repo-skill#368). Installing from this repository or the marketplace includes it.
