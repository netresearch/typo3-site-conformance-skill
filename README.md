# TYPO3 Site / Project Conformance Skill

Conformance and hardening for **deployable TYPO3 v14 site/project repositories**
— the site/project counterpart to the extension-scoped
[`typo3-conformance`](https://github.com/netresearch/typo3-conformance-skill).

## What this skill solves

TYPO3 work splits into two worlds: reusable **extensions** (packages,
`ext_emconf.php`, `Classes/`, TER) and deployable **sites** (`type: project`,
Docker/Compose, CI/CD, secrets, runtime). The existing conformance skill covers
extensions; this one covers the **site/project** half — repository layout,
container topology, Concourse pipeline, supply-chain gating, secret handling,
and the Valkey/ofelia runtime — against the Netresearch gold standard.

It is a **router + methodology**, not a copy of the ruleset: the 73-rule
catalogue lives canonically in the
[gold-standard spec](https://pages.nrdev.de/typo3/typo3-project-standard) and as
an **executable checker** in
[`typo3-14-gold`](https://git.netresearch.de/typo3/typo3-14-gold)
(`tools/conformance/check.py`, `make conformance`). This skill routes you there
and explains the scope model and the migration moves.

## Use when

- A repository has `composer.json` `"type": "project"` **and** a root Compose
  file (`compose.yaml`/`docker-compose.yml`).
- You are reviewing or hardening container/Compose topology, a Concourse
  pipeline, supply-chain gating, or TYPO3 site config (`config/system`,
  `config/sites`).
- You are forking the gold skeleton to start a new customer site, or migrating a
  legacy `support/typo3-NN/app`-style repo.

For **extension** repos use `typo3-conformance` instead.

## Expected outputs

- A pass/fail conformance verdict per rule family (STRUCT, CONTAINER, CI,
  DEPLOY, DEP, SEC, DOC) with file:line evidence.
- A prioritized remediation list (ERROR blocks, WARN should-fix, INFO advisory).
- For migrations: the concrete seven-move transformation plan
  (`references/migration-from-reference.md`).

## Context requirements

- Read access to the target repository tree (`composer.json`, `Dockerfile`,
  `compose*.yaml`, `ci/`, `config/system`, `config/sites`, `.gitlab-ci.yml`,
  `AGENTS.md`).
- To run the executable checker: `python3` + the `typo3-14-gold` checkout (or a
  vendored copy of `tools/conformance/`).

## Example prompts

- "Is this TYPO3 site repo gold-conformant? Score it."
- "Review our `compose.yaml` and Concourse pipeline against the gold standard."
- "Migrate this `support/typo3-12/app` repo to the gold layout."
- "Why is `make conformance` failing on STRUCT-001 / SC-007?"

## Related skills

- [`typo3-conformance`](https://github.com/netresearch/typo3-conformance-skill)
  — extension quality/TER readiness (the sibling).
- `enterprise-readiness` — generic supply-chain/OpenSSF hardening.
- `docker-development`, `concourse-ci` — the underlying container/CI mechanics.

## Compatibility

TYPO3 v14.3 LTS (current gold target), PHP 8.4 baseline. Reference
implementation: `typo3-14-gold`.

## Installation

Add the Netresearch marketplace and install the plugin:

```
/plugin marketplace add netresearch/claude-code-marketplace
/plugin install typo3-site-conformance
```

## Contributing

Issues and PRs welcome. The rule catalogue is single-sourced in the
[gold-standard spec](https://pages.nrdev.de/typo3/typo3-project-standard) and
the [`typo3-14-gold`](https://git.netresearch.de/typo3/typo3-14-gold) checker —
propose rule changes there; this repo carries the routing/methodology only.
Run `bash validate-skill.sh .` (from `skill-repo-skill`) before opening a PR.

## License

Code MIT, content CC-BY-SA-4.0 — see `LICENSE-MIT` and `LICENSE-CC-BY-SA-4.0`.
© Netresearch DTT GmbH.
