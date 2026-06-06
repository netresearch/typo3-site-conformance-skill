#!/usr/bin/env python3
"""Generate rules.json — the deduped 73-rule gold-standard conformance catalogue.

Source of truth: the published conformance ruleset
(https://pages.nrdev.de/typo3/typo3-project-standard → Conformance Ruleset).

Each rule carries a `scope`:
  - "repo"     : statically checkable against this repository; the gold project
                 must pass 100 % of these.
  - "advisory" : architectural / estate / runtime / base-image properties that
                 cannot be asserted from a single template repo. Reported with a
                 by-design note, excluded from the gold-project score.
"""
import json
import pathlib

# (code, category, severity, scope, requirement)
RULES = [
    # --- STRUCT ---------------------------------------------------------------
    ("STRUCT-001", "STRUCT", "error",   "repo", "TYPO3 config directory must be at project root as config/, not build/config/"),
    ("STRUCT-002", "STRUCT", "error",   "repo", "config/system/settings.php must contain no plaintext secrets"),
    ("STRUCT-003", "STRUCT", "error",   "repo", "config/system/additional.php must exist and source env values from $_SERVER"),
    ("STRUCT-004", "STRUCT", "warning", "repo", "composer.lock must be committed for project-type composer.json"),
    ("STRUCT-005", "STRUCT", "warning", "repo", "config/sites/ must contain at least one site config.yaml"),
    ("STRUCT-006", "SEC",    "error",   "repo", "No committed live-environment files (.env.production etc.)"),
    ("STRUCT-007", "STRUCT", "warning", "repo", ".gitignore must exclude vendor/, var/, public/ and live-env patterns"),
    ("STRUCT-008", "STRUCT", "info",    "repo", "build/ directory must not exist after migration to config/"),
    ("DRO-019",    "STRUCT", "info",    "advisory", "New sites should use the three-repo layout (app / deploy / infra)"),
    # --- CONTAINER ------------------------------------------------------------
    ("CI-IMG-001", "CONTAINER", "error",   "repo", "Carrier base image must not use alpine:edge"),
    ("CI-IMG-002", "CONTAINER", "error",   "repo", "Cache service must use Valkey, not Redis"),
    ("CI-IMG-003", "CONTAINER", "error",   "repo", "First-party app and db images must use immutable version tags, not :latest"),
    ("CI-IMG-004", "CONTAINER", "error",   "repo", "No secrets committed to settings.php or any build artefact"),
    ("CI-IMG-005", "CONTAINER", "error",   "repo", "Production config must not set debug-mode defaults"),
    ("CI-IMG-006", "CONTAINER", "warning", "repo", "ofelia must use a pinned version tag, not :latest"),
    ("CI-IMG-007", "CONTAINER", "warning", "repo", "All long-running services must define deploy.resources.limits"),
    ("CI-IMG-008", "CONTAINER", "warning", "repo", "Stateful services must define healthcheck blocks"),
    ("CI-IMG-009", "CONTAINER", "warning", "repo", "docker.sock must not be mounted directly; use a socket proxy"),
    ("CI-IMG-010", "CONTAINER", "warning", "repo", "Development-only images must carry pinned tags"),
    ("CI-IMG-011", "CONTAINER", "warning", "repo", "Compose file must use canonical filename compose.yaml"),
    ("CI-IMG-012", "CONTAINER", "warning", "repo", "COMPOSE_FILE env-var overlay pattern must not be used"),
    ("CI-IMG-013", "CONTAINER", "info",    "repo", "Carrier Dockerfile should use SGID not SUID on writable directories"),
    ("CI-IMG-014", "CONTAINER", "info",    "repo", "No PHP 8.2 (EOL Dec 2026) runtime without a documented upgrade plan"),
    ("CI-IMG-015", "CONTAINER", "info",    "repo", "Production Dockerfile should embed OCI image labels"),
    ("DRO-001",    "CONTAINER", "error",   "repo", "All persistent services must define a healthcheck"),
    ("DRO-002",    "CONTAINER", "error",   "repo", "depends_on must use condition: service_healthy for persistent deps"),
    ("DRO-003",    "CONTAINER", "error",   "repo", "All persistent services must set restart: unless-stopped"),
    ("DRO-015",    "CONTAINER", "warning", "repo", "ofelia scheduler failure must have webhook notification configured"),
    ("DRO-017",    "CONTAINER", "info",    "advisory", "PHP-FPM status endpoint should be enabled for metrics scraping"),
    ("DRO-020",    "CONTAINER", "info",    "repo", "Compose canonical filename should be compose.yaml"),
    # --- CI -------------------------------------------------------------------
    ("CI-001",     "CI", "warning", "repo", "ofelia scheduler image must reference a pinned version tag"),
    ("CI-002",     "CI", "warning", "repo", "COMPOSER_AUTH should use BuildKit --mount=type=secret, not ARG"),
    ("DRO-013",    "CI", "error",   "repo", "A weekly restore-verification job must exist"),
    ("SC-001",     "CI", "error",   "repo", "composer audit must run before every Docker build"),
    ("SC-002",     "CI", "error",   "repo", "Vulnerability scan (Trivy CRITICAL+HIGH) must gate image push"),
    ("SC-003",     "CI", "error",   "repo", "SBOM must be generated for every production image build"),
    ("SC-007",     "CI", "error",   "repo", "All CI task image references must be immutably pinned"),
    ("SC-008",     "CI", "error",   "repo", "fly CLI downloaded in GitLab CI must have its checksum verified"),
    ("SC-009",     "CI", "error",   "repo", "Dependency updates must go via merge requests, not direct to main"),
    ("SC-010",     "CI", "warning", "repo", "GitLab native secret detection must be enabled"),
    ("SC-011",     "CI", "warning", "repo", "The test gate in the Concourse pipeline must not be disabled"),
    ("SC-012",     "CI", "warning", "repo", "composer.lock must be committed in project-type repositories"),
    ("SC-013",     "CI", "warning", "repo", "Compose runtime service images must be pinned to specific versions"),
    # --- DEPLOY ---------------------------------------------------------------
    ("DEPLOY-001", "DEPLOY", "warning", "advisory", "CI pipeline files should live in a separate deploy repo"),
    ("DEPLOY-002", "DEPLOY", "warning", "repo", "Ansible playbooks should live in a separate deploy repo"),
    ("DRO-004",    "DEPLOY", "error",   "repo", "Valkey/Redis must require authentication"),
    ("DRO-005",    "DEPLOY", "error",   "repo", "Cache service must disable persistence (--save '' and no AOF)"),
    ("DRO-006",    "DEPLOY", "error",   "repo", "Cache service must set maxmemory and allkeys-lru eviction"),
    ("DRO-008",    "DEPLOY", "error",   "repo", "Cache image must use Valkey, not Redis"),
    ("DRO-009",    "DEPLOY", "error",   "repo", "Cache image must be pinned to a stable version tag, not :latest"),
    ("DRO-010",    "DEPLOY", "error",   "repo", "Dockerfile final stage must not use FROM alpine:edge"),
    ("DRO-012",    "DEPLOY", "warning", "repo", "Development-mode flags must not be committed in settings.php"),
    ("DRO-014",    "DEPLOY", "error",   "repo", "Scheduler standard must be ofelia; in-image dcron disabled"),
    ("DRO-016",    "DEPLOY", "warning", "repo", "TYPO3 log output must go to stdout/stderr, not an on-disk FileWriter"),
    ("DRO-018",    "DEPLOY", "warning", "advisory", "Each site must be registered in external uptime monitoring"),
    # --- DEP ------------------------------------------------------------------
    ("DEP-001",    "DEP", "error",   "repo", "PHP platform constraint must be declared in composer.json"),
    ("DEP-002",    "DEP", "error",   "repo", "Dev-branch constraints must not appear in composer.json"),
    ("DEP-003",    "DEP", "warning", "repo", "minimum-stability must be declared as 'stable'"),
    ("DEP-004",    "DEP", "warning", "repo", "composer.lock must be committed for type:project"),
    # --- SEC ------------------------------------------------------------------
    ("DRO-007",    "SEC", "error",   "repo", "ofelia must not mount docker.sock directly; use a socket proxy"),
    ("DRO-011",    "SEC", "error",   "repo", "Credentials must not be committed; .env git-ignored; .env.dist schema"),
    ("SC-004",     "SEC", "error",   "repo", "Container images must be signed with cosign after push"),
    ("SC-005",     "SEC", "error",   "repo", "COMPOSER_AUTH must not be passed as a Docker build ARG"),
    ("SC-006",     "SEC", "error",   "repo", "Secrets must not be committed in build configuration files"),
    ("SEC-001",    "SEC", "error",   "repo", "redis service image must specify an explicit version tag"),
    ("SEC-002",    "SEC", "error",   "repo", "installToolPassword must not be hardcoded in settings.php"),
    ("SEC-003",    "SEC", "error",   "repo", "encryptionKey must be env-driven in additional.php"),
    ("SEC-004",    "SEC", "error",   "repo", "Production env files must not be committed to git"),
    ("SEC-005",    "SEC", "warning", "repo", "devIPmask wildcard must not be committed"),
    ("SEC-006",    "SEC", "warning", "repo", "trustedHostsPattern wildcard must not be committed"),
    # --- DOC ------------------------------------------------------------------
    ("DOC-001",    "DOC", "error",   "repo", "AGENTS.md must exist at repository root"),
    ("DOC-002",    "DOC", "error",   "repo", "CLAUDE.md must exist as a symlink to AGENTS.md"),
    ("DOC-003",    "DOC", "warning", "repo", "README.md must document setup, env vars and make targets"),
]

WEIGHTS = {"error": 10, "warning": 5, "info": 1}


def main() -> None:
    rules = [
        {
            "code": code,
            "category": category,
            "severity": severity,
            "weight": WEIGHTS[severity],
            "scope": scope,
            "requirement": requirement,
        }
        for (code, category, severity, scope, requirement) in RULES
    ]
    out = {
        "version": "1.0.0",
        "reference": "https://pages.nrdev.de/typo3/typo3-project-standard",
        "weights": WEIGHTS,
        "rules": rules,
    }
    path = pathlib.Path(__file__).with_name("rules.json")
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(rules)} rules to {path}")


if __name__ == "__main__":
    main()
