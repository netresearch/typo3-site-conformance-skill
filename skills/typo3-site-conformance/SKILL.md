---
name: typo3-site-conformance
description: "Use when assessing or hardening a deployable TYPO3 SITE/PROJECT repo (composer type:project + Docker/Compose) — not an extension. Triggers on: compose.yaml/docker-compose.yml + config/sites or config/system in a TYPO3 repo, site conformance, gold standard, project conformance, container/Compose topology, Concourse pipeline review, supply-chain (Trivy/SBOM/cosign), secret-free settings.php/additional.php, Valkey cache, ofelia scheduler, image digest pinning, .gitlab-ci validate-only. For EXTENSION quality use typo3-conformance instead."
metadata:
  version: "0.1.0"
  repository: https://github.com/netresearch/typo3-site-conformance-skill
  author: Netresearch DTT GmbH
---

# TYPO3 Site / Project Conformance

Score and harden a **deployable TYPO3 site distribution** against the Netresearch
gold standard. This is the **site/project** counterpart to `typo3-conformance`
(which scopes to *extensions*).

## When to use

- A repo with `composer.json` `"type": "project"` **and** a root Compose file.
- Reviewing container topology, Concourse CI, supply-chain gating, secret
  handling, or TYPO3 site config (`config/system`, `config/sites`).
- Bootstrapping a new customer site from the gold skeleton.

Extension repos (`ext_emconf.php`, `Classes/`, TER) → use **`typo3-conformance`**.
Generic supply-chain hardening → **`enterprise-readiness`**; Docker/Compose →
**`docker-development`**; Concourse → **`concourse-ci`**.

## Source of truth (do not duplicate the rules)

This skill is a **router + methodology**, not a second copy of the ruleset. The
73-rule catalogue is single-sourced:

- **Spec (canonical, human):** `typo3-project-standard` →
  `docs/conformance.md` (https://pages.nrdev.de/typo3/typo3-project-standard).
- **Executable checker:** `typo3-14-gold` → `tools/conformance/check.py` +
  `rules.json`, run with `make conformance` (CI-gated; the gold skeleton passes
  100 %). https://git.netresearch.de/typo3/typo3-14-gold

To score a repo: run the checker against it, or apply the rule intents below.

## The seven rule families (intent — full text in the spec)

| Family | Intent |
|--------|--------|
| `STRUCT` | TYPO3-native layout: `config/` at composer-project root, no `build/config`, `config/sites/*/config.yaml`, committed `composer.lock`, `.gitignore` excludes vendor/var/public + live-env files |
| `CONTAINER` | `compose.yaml` (not `docker-compose.yml`); images digest-pinned (no `:latest`/`alpine:edge`); healthchecks + `deploy.resources.limits` + `restart` on persistent services; no direct `docker.sock` mount |
| `CI` | composer audit → Trivy gate → SBOM → cosign; CI task images pinned; fly download checksum-verified; secret detection; test gate; updates via MR |
| `DEPLOY` | Valkey (auth + eviction + no persistence); ofelia scheduler via socket-proxy; weekly restore-verification; logs to stdout/stderr |
| `DEP` | declared PHP platform constraint; no dev-branch constraints; `minimum-stability: stable`; committed lock |
| `SEC` | no committed secrets (settings.php/additional.php secret-free, env-driven); no committed live-env files; no debug/host wildcards |
| `DOC` | `AGENTS.md` + `CLAUDE.md`→symlink; `README` documents setup/env/make |

## Workflow

1. **Gate.** Confirm `type: project` + root Compose. Otherwise N/A (extension → `typo3-conformance`).
2. **Score.** Run the executable checker (`make conformance`) or evaluate the families above. ERROR blocks; WARN should fix; INFO advisory.
3. **Scope.** Architecture/estate/runtime rules (three-repo split, uptime, php-fpm status, ci-colocation) are *advisory* — report, don't gate.
4. **Fix → re-score.** Keep repo-scope rules at 100 %.

See `references/migration-from-reference.md` for transforming a legacy
`support/typo3-NN/app`-style repo (app/ wrapper, `build/config`, committed
secrets, Redis, `:latest`) into a conformant one.
