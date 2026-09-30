#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Behaviour tests for the bundled conformance checker.

Covers skills/typo3-site-conformance/checker/check.py and gen_rules.py:

- a "gold" fixture repository that passes every repo-scope rule;
- one mutation per rule in check.CHECKS that must make that rule fail;
- the command line: exit codes, the FAIL/PASS rows and the FAILING line;
- the helpers (image pinning, secret detection, placeholder expansion, comment
  stripping, the additional.php dev-flag guard);
- parity between rules.json, gen_rules.py and check.CHECKS.

Standard library only, apart from PyYAML, which the checker itself needs.
Run: python3 tests/test_check.py   (exit 0 = all tests passed)
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    import yaml  # noqa: F401  (imported by check.py; fail here with a clear message)
except ImportError:
    print(
        "::error::PyYAML not importable by "
        f"{sys.executable} — the checker's declared dependency is missing"
    )
    sys.exit(1)

REPO = pathlib.Path(__file__).resolve().parent.parent
CHECKER = REPO / "skills" / "typo3-site-conformance" / "checker"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, CHECKER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load("check")
gen_rules = _load("gen_rules")

DIGEST = "sha256:" + "a" * 64

# --------------------------------------------------------------------------- #
# Gold fixture: the smallest repository tree that passes every repo-scope rule.
# --------------------------------------------------------------------------- #
GOLD = {
    "composer.json": json.dumps(
        {
            "name": "acme/site",
            "type": "project",
            "require": {"php": "^8.4", "typo3/cms-core": "^14.3"},
            "config": {"platform": {"php": "8.4.0"}},
            "minimum-stability": "stable",
        }
    ),
    "composer.lock": "{}\n",
    "config/system/settings.php": """<?php
return [
    'BE' => ['debug' => false, 'installToolPassword' => ''],
    'FE' => ['debug' => false],
    'SYS' => [
        'displayErrors' => 0,
        'devIPmask' => '',
        'encryptionKey' => '',
        'trustedHostsPattern' => 'www\\\\.example\\\\.com',
    ],
    'LOG' => ['writerConfiguration' => ['warning' => [
        \\TYPO3\\CMS\\Core\\Log\\Writer\\FileWriter::class => ['logFile' => 'php://stderr'],
    ]]],
];
""",
    "config/system/additional.php": """<?php
$GLOBALS['TYPO3_CONF_VARS']['SYS']['encryptionKey'] = $_SERVER['TYPO3_ENCRYPTION_KEY'] ?? '';
if (\\TYPO3\\CMS\\Core\\Core\\Environment::getContext()->isDevelopment()) {
    $GLOBALS['TYPO3_CONF_VARS']['SYS']['displayErrors'] = 1;
    $GLOBALS['TYPO3_CONF_VARS']['BE']['debug'] = true;
    $GLOBALS['TYPO3_CONF_VARS']['SYS']['devIPmask'] = '*';
}
""",
    "config/sites/main/config.yaml": "base: 'https://www.example.com/'\nrootPageId: 1\n",
    ".gitignore": "/vendor/\n/var/\n/public/\n.env\n*.prod.env\n",
    ".env.dist": (
        "# schema only, no values\n"
        "APP_IMAGE=registry.netresearch.de/acme/site:1.2.3\n"
        "DB_IMAGE=mariadb:11.4\n"
        "VALKEY_TAG=8.1\n"
        "TYPO3_ENCRYPTION_KEY=\n"
    ),
    "Dockerfile": f"""# syntax=docker/dockerfile:1
FROM composer:2.8 AS build
RUN --mount=type=secret,id=composer_auth,env=COMPOSER_AUTH composer install
FROM php:8.4-fpm-alpine@{DIGEST}
LABEL org.opencontainers.image.version="1.2.3" \\
      org.opencontainers.image.source="https://example.com/acme/site" \\
      org.opencontainers.image.vendor="ACME"
RUN pecl install apcu-5.1.24
RUN mkdir -p /var/www/var && chmod g+s /var/www/var
""",
    "compose.yaml": """services:
  app:
    image: ${APP_IMAGE}
    deploy: {resources: {limits: {memory: 512m}}}
  db:
    image: ${DB_IMAGE}
    restart: unless-stopped
    healthcheck: {test: [CMD, healthcheck.sh, --connect]}
    deploy: {resources: {limits: {memory: 1g}}}
  valkey:
    image: valkey/valkey:${VALKEY_TAG}
    restart: unless-stopped
    command: [valkey-server, --requirepass, "${VALKEY_PASSWORD}", --save, "", --maxmemory, 256mb, --maxmemory-policy, allkeys-lru]
    healthcheck: {test: [CMD, valkey-cli, ping]}
    deploy: {resources: {limits: {memory: 300m}}}
  web:
    image: registry.netresearch.de/acme/web:latest
    restart: unless-stopped
    healthcheck: {test: [CMD, curl, -f, http://localhost/]}
    deploy: {resources: {limits: {memory: 256m}}}
    depends_on:
      db: {condition: service_healthy}
      setup: {condition: service_completed_successfully}
  setup:
    image: ${APP_IMAGE}
    command: [vendor/bin/typo3, setup]
  backup:
    image: ${APP_IMAGE}
    deploy: {resources: {limits: {memory: 128m}}}
  socket-proxy:
    image: tecnativa/docker-socket-proxy:0.3.0
    restart: unless-stopped
    volumes: [/var/run/docker.sock:/var/run/docker.sock:ro]
    healthcheck: {test: [CMD, wget, -qO-, http://localhost:2375/_ping]}
    deploy: {resources: {limits: {memory: 64m}}}
  ofelia:
    image: mcuadros/ofelia:0.3.18
    restart: unless-stopped
    command: daemon --docker
    environment: [DOCKER_HOST=tcp://socket-proxy:2375]
    labels:
      ofelia.job-exec.scheduler.command: vendor/bin/typo3 scheduler:run
    healthcheck: {test: [CMD, pgrep, ofelia]}
    deploy: {resources: {limits: {memory: 64m}}}
""",
    "compose.override.yaml": """services:
  web:
    ports: !reset []
  pma:
    image: phpmyadmin:5.2.1
  mailpit:
    image: axllent/mailpit:v1.20
""",
    "ofelia/config.ini": "[global]\nslack-webhook = ${OFELIA_WEBHOOK}\n",
    "ci/pipeline.yml": f"""image: &tool-image
  type: registry-image
  source: {{repository: alpine, tag: "3.20"}}
resources:
  - name: app-image
    type: registry-image
    source: {{repository: registry.netresearch.de/acme/site, tag: latest}}
jobs:
  - name: test
    plan:
      - task: phpunit
        config:
          platform: linux
          image_resource: *tool-image
          run: {{path: sh, args: [-c, vendor/bin/phpunit]}}
  - name: build-and-sign
    plan:
      - get: source
        passed: [test]
      - task: audit
        config:
          platform: linux
          image_resource:
            type: registry-image
            source: {{repository: composer@{DIGEST}}}
          run: {{path: sh, args: [-c, composer audit]}}
      - task: scan
        config:
          platform: linux
          image_resource:
            type: registry-image
            source: {{repository: aquasec/trivy, tag: "0.58.0"}}
          run: {{path: sh, args: [-c, trivy image --exit-code 1 --severity CRITICAL,HIGH app]}}
      - task: sbom
        config:
          platform: linux
          image_resource: *tool-image
          run: {{path: sh, args: [-c, sbom-toolbox generate && stack-sbom collect]}}
      - task: sign
        config:
          platform: linux
          image_resource: *tool-image
          run: {{path: sh, args: [-c, cosign sign app && cosign attest --type cyclonedx app]}}
  - name: restore-verify
    plan:
      - task: restore
        config:
          platform: linux
          image_resource: *tool-image
          run: {{path: sh, args: [-c, restore-db && verify-db]}}
""",
    ".gitlab-ci.yml": """include:
  - template: Jobs/Secret-Detection.gitlab-ci.yml
validate:
  script:
    - curl -fsSLO https://example.com/fly && sha256sum -c fly.sha256
""",
    "AGENTS.md": "# Agents\n",
    "README.md": "# Site\n\nCopy `.env.dist` to `.env`, then run `make install`.\n",
}


def _git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def build_repo(root: pathlib.Path, files: dict[str, str | None]) -> pathlib.Path:
    """Write `files` below `root` (a None value skips the file), add the
    CLAUDE.md -> AGENTS.md symlink and stage everything in a fresh git index."""
    for rel, content in files.items():
        if content is None:
            continue
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    link = root / "CLAUDE.md"
    if "AGENTS.md" in files and files["AGENTS.md"] is not None:
        link.symlink_to("AGENTS.md")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    return root


def _replace(rel: str, old: str, new: str):
    def mutate(files: dict) -> None:
        assert old in files[rel], f"mutation anchor missing in {rel}: {old!r}"
        files[rel] = files[rel].replace(old, new)

    return mutate


def _set(rel: str, content: str | None):
    def mutate(files: dict) -> None:
        files[rel] = content

    return mutate


def _add_after_build(rel: str, content: str, track: bool = False):
    """A file created after the index is built (optionally force-added)."""

    def post(root: pathlib.Path) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if track:
            _git(root, "add", "-f", rel)

    return post


def _both(*mutations):
    def mutate(files: dict) -> None:
        for m in mutations:
            m(files)

    return mutate


# code -> (mutation of the file dict, optional post-build step)
MUTATIONS = {
    "STRUCT-001": (
        _set("build/config/system/settings.php", "<?php return [];\n"),
        None,
    ),
    "STRUCT-002": (
        _replace(
            "config/system/settings.php",
            "'installToolPassword' => ''",
            "'installToolPassword' => \"hunter2\"",
        ),
        None,
    ),
    "STRUCT-003": (
        _replace(
            "config/system/additional.php",
            "$_SERVER['TYPO3_ENCRYPTION_KEY'] ?? ''",
            "getenv('TYPO3_ENCRYPTION_KEY')",
        ),
        None,
    ),
    "STRUCT-004": (_set("composer.lock", None), None),
    "STRUCT-005": (_set("config/sites/main/config.yaml", None), None),
    "STRUCT-006": (_set("deploy/.env.production", "DB_PASSWORD=x\n"), None),
    "STRUCT-007": (_replace(".gitignore", "/var/\n", ""), None),
    "STRUCT-008": (_set("build/config/README", "legacy\n"), None),
    "CI-IMG-001": (
        _replace("Dockerfile", "FROM composer:2.8", "FROM alpine:edge"),
        None,
    ),
    "CI-IMG-002": (
        _replace("compose.yaml", "valkey/valkey:${VALKEY_TAG}", "redis:7.4"),
        None,
    ),
    "CI-IMG-003": (
        _replace(".env.dist", "DB_IMAGE=mariadb:11.4", "DB_IMAGE=mariadb:latest"),
        None,
    ),
    "CI-IMG-004": (
        _replace(
            "config/system/settings.php",
            "'encryptionKey' => ''",
            "'encryptionKey' => 'not-hex-but-committed'",
        ),
        None,
    ),
    "CI-IMG-005": (
        _replace(
            "config/system/settings.php", "'displayErrors' => 0", "'displayErrors' => 2"
        ),
        None,
    ),
    "CI-IMG-006": (
        _replace("compose.yaml", "mcuadros/ofelia:0.3.18", "mcuadros/ofelia:latest"),
        None,
    ),
    "CI-IMG-007": (
        _replace(
            "compose.yaml",
            "    image: ${APP_IMAGE}\n    deploy: {resources: {limits: {memory: 128m}}}\n",
            "    image: ${APP_IMAGE}\n",
        ),
        None,
    ),
    "CI-IMG-008": (
        _replace(
            "compose.yaml", "    healthcheck: {test: [CMD, valkey-cli, ping]}\n", ""
        ),
        None,
    ),
    "CI-IMG-009": (
        _replace(
            "compose.yaml",
            "    environment: [DOCKER_HOST=tcp://socket-proxy:2375]\n",
            "    environment: [DOCKER_HOST=tcp://socket-proxy:2375]\n"
            "    volumes: [/var/run/docker.sock:/var/run/docker.sock]\n",
        ),
        None,
    ),
    "CI-IMG-010": (
        _replace("compose.override.yaml", "phpmyadmin:5.2.1", "phpmyadmin:latest"),
        None,
    ),
    "CI-IMG-011": (_set("docker-compose.yml", "services: {}\n"), None),
    "CI-IMG-012": (
        _replace(
            ".env.dist",
            "DB_IMAGE=",
            "COMPOSE_FILE=compose.yaml:compose.prod.yaml\nDB_IMAGE=",
        ),
        None,
    ),
    "CI-IMG-013": (_replace("Dockerfile", "chmod g+s", "chmod u+s"), None),
    "CI-IMG-014": (
        _replace(
            ".env.dist",
            "DB_IMAGE=mariadb:11.4",
            "DB_IMAGE=mariadb:11.4\nPHP_IMAGE=php:8.2-fpm",
        ),
        None,
    ),
    "CI-IMG-015": (
        _replace("Dockerfile", "org.opencontainers.image.vendor", "org.example.vendor"),
        None,
    ),
    "DRO-001": (
        _replace(
            "compose.yaml",
            "    healthcheck: {test: [CMD, curl, -f, http://localhost/]}\n",
            "",
        ),
        None,
    ),
    "DRO-002": (
        _replace(
            "compose.yaml",
            "db: {condition: service_healthy}",
            "db: {condition: service_started}",
        ),
        None,
    ),
    "DRO-003": (
        _replace(
            "compose.yaml",
            "    image: registry.netresearch.de/acme/web:latest\n    restart: unless-stopped\n",
            "    image: registry.netresearch.de/acme/web:latest\n",
        ),
        None,
    ),
    "DRO-015": (_set("ofelia/config.ini", "[global]\nsave-folder = /tmp\n"), None),
    "DRO-020": (_set("docker-compose.yml", "services: {}\n"), None),
    "CI-001": (
        _replace("compose.yaml", "mcuadros/ofelia:0.3.18", "mcuadros/ofelia:latest"),
        None,
    ),
    "CI-002": (
        _replace(
            "Dockerfile",
            "FROM composer:2.8 AS build\n",
            "FROM composer:2.8 AS build\nARG COMPOSER_AUTH\n",
        ),
        None,
    ),
    "DRO-013": (
        _both(
            _replace("ci/pipeline.yml", "restore-verify", "nightly"),
            _replace("ci/pipeline.yml", "restore-db && verify-db", "restore-db"),
        ),
        # a restore without verification elsewhere under ci/ does not count
        _add_after_build("ci/restore.yml", "run: restore-db\n"),
    ),
    "SC-001": (
        _replace("ci/pipeline.yml", "composer audit", "composer validate"),
        None,
    ),
    "SC-002": (_replace("ci/pipeline.yml", "--exit-code 1", "--exit-code 0"), None),
    "SC-003": (
        _replace("ci/pipeline.yml", "sbom-toolbox generate", "syft app -o spdx-json"),
        None,
    ),
    "SC-007": (_replace("ci/pipeline.yml", 'tag: "0.58.0"', "tag: latest"), None),
    "SC-008": (
        _replace(".gitlab-ci.yml", "sha256sum -c fly.sha256", "chmod +x fly"),
        None,
    ),
    "SC-009": (
        _both(
            _replace(
                "ci/pipeline.yml",
                "restore-db && verify-db",
                "restore-db && verify-db && update-packages",
            ),
        ),
        None,
    ),
    "SC-010": (
        _replace(
            ".gitlab-ci.yml", "Secret-Detection.gitlab-ci.yml", "SAST.gitlab-ci.yml"
        ),
        None,
    ),
    "SC-011": (_replace("ci/pipeline.yml", "passed: [test]", "passed: []"), None),
    "SC-012": (_set("composer.lock", None), None),
    "SC-013": (
        _replace(
            "compose.override.yaml", "axllent/mailpit:v1.20", "axllent/mailpit:latest"
        ),
        None,
    ),
    "SC-014": (_replace("ci/pipeline.yml", " && stack-sbom collect", ""), None),
    "SC-015": (
        _replace(
            "Dockerfile", "pecl install apcu-5.1.24", "pecl install apcu redis-6.1.0"
        ),
        None,
    ),
    "SC-016": (_set("node_modules/left-pad/index.js", "module.exports = 1;\n"), None),
    "DEPLOY-002": (_set("ansible/site.yml", "- hosts: all\n"), None),
    "DRO-004": (
        _replace("compose.yaml", '--requirepass, "${VALKEY_PASSWORD}", ', ""),
        None,
    ),
    "DRO-005": (
        _replace("compose.yaml", '--save, "", ', '--save, "", --appendonly, "yes", '),
        None,
    ),
    "DRO-006": (_replace("compose.yaml", "allkeys-lru", "noeviction"), None),
    "DRO-008": (
        _replace("compose.yaml", "valkey/valkey:${VALKEY_TAG}", "redis:7.4"),
        None,
    ),
    "DRO-009": (
        _replace(
            "compose.yaml",
            "tecnativa/docker-socket-proxy:0.3.0",
            "tecnativa/docker-socket-proxy",
        ),
        None,
    ),
    "DRO-010": (
        _replace("Dockerfile", f"FROM php:8.4-fpm-alpine@{DIGEST}", "FROM php:latest"),
        None,
    ),
    "DRO-012": (
        _replace(
            "config/system/settings.php",
            "'BE' => ['debug' => false",
            "'BE' => ['debug' => true",
        ),
        None,
    ),
    "DRO-014": (
        _replace("compose.yaml", "command: daemon --docker", "command: crond -f"),
        None,
    ),
    "DRO-016": (
        _replace("config/system/settings.php", "php://stderr", "/var/log/typo3.log"),
        None,
    ),
    "DEP-001": (
        _replace("composer.json", '"platform": {"php": "8.4.0"}', '"platform": {}'),
        None,
    ),
    "DEP-002": (
        _replace(
            "composer.json", '"typo3/cms-core": "^14.3"', '"typo3/cms-core": "dev-main"'
        ),
        None,
    ),
    "DEP-003": (
        _replace(
            "composer.json",
            '"minimum-stability": "stable"',
            '"minimum-stability": "dev"',
        ),
        None,
    ),
    "DEP-004": (_set("composer.lock", None), None),
    "DRO-007": (
        _replace(
            "compose.yaml", "tecnativa/docker-socket-proxy:0.3.0", "alpine/socat:1.8.0"
        ),
        None,
    ),
    "DRO-011": (None, _add_after_build(".env", "DB_PASSWORD=secret\n", track=True)),
    "SC-004": (
        _replace("ci/pipeline.yml", " && cosign attest --type cyclonedx app", ""),
        None,
    ),
    "SC-005": (
        _replace(
            "Dockerfile",
            "FROM composer:2.8 AS build\n",
            "FROM composer:2.8 AS build\nARG COMPOSER_AUTH\n",
        ),
        None,
    ),
    "SC-006": (
        _replace(
            "config/system/settings.php",
            "'devIPmask' => ''",
            "'devIPmask' => '', 'transport_smtp_password' => 'hunter2'",
        ),
        None,
    ),
    "SEC-001": (_replace("compose.yaml", "valkey/valkey:${VALKEY_TAG}", "redis"), None),
    "SEC-002": (
        _replace(
            "config/system/settings.php",
            "'installToolPassword' => ''",
            "'installToolPassword' => '$argon2id$v=19$abc'",
        ),
        None,
    ),
    "SEC-003": (
        _replace("config/system/additional.php", "TYPO3_ENCRYPTION_KEY", "APP_KEY"),
        None,
    ),
    "SEC-004": (None, _add_after_build(".env", "DB_PASSWORD=secret\n", track=True)),
    "SEC-005": (
        _replace(
            "config/system/additional.php",
            "isDevelopment()",
            "isProduction()",
        ),
        None,
    ),
    "SEC-006": (
        _replace(
            "config/system/settings.php",
            "'trustedHostsPattern' => 'www\\\\.example\\\\.com'",
            "'trustedHostsPattern' => '.*'",
        ),
        None,
    ),
    "DOC-001": (_set("AGENTS.md", None), None),
    "DOC-002": (
        None,
        lambda root: (
            (root / "CLAUDE.md").unlink(),
            (root / "CLAUDE.md").write_text("# copy\n"),
        ),
    ),
    "DOC-003": (_replace("README.md", "`make install`", "`composer install`"), None),
}


class _TempRepo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def repo(self, mutation=None, post=None) -> pathlib.Path:
        files = dict(GOLD)
        if mutation is not None:
            mutation(files)
        build_repo(self.root, files)
        if post is not None:
            post(self.root)
        return self.root

    def run_cli(self, root: pathlib.Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CHECKER / "check.py"), str(root)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


class GoldFixtureTest(_TempRepo):
    def test_every_repo_scope_rule_passes(self) -> None:
        ctx = check.Ctx(self.repo())
        failing = {
            code: fn(ctx)[1] for code, fn in check.CHECKS.items() if not fn(ctx)[0]
        }
        self.assertEqual(failing, {})

    def test_cli_exits_zero_and_reports_100_percent(self) -> None:
        r = self.run_cli(self.repo())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("100%", r.stdout)
        self.assertNotIn("FAILING", r.stdout)
        self.assertNotIn("SKIP", r.stdout)
        for code in check.ADVISORY_NOTE:
            self.assertRegex(r.stdout, rf"ADVISORY\S*\s+{code}\s")


class MutationTest(_TempRepo):
    def test_every_check_has_a_mutation(self) -> None:
        self.assertEqual(set(MUTATIONS), set(check.CHECKS))

    def test_each_mutation_fails_its_rule(self) -> None:
        for code, (mutation, post) in MUTATIONS.items():
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                files = dict(GOLD)
                if mutation is not None:
                    mutation(files)
                build_repo(root, files)
                if post is not None:
                    post(root)
                ok, detail = check.CHECKS[code](check.Ctx(root))
                self.assertIs(bool(ok), False, f"{code} still passes: {detail}")

    def test_cli_exits_one_and_names_the_failing_rule(self) -> None:
        mutation, _ = MUTATIONS["SC-002"]
        r = self.run_cli(self.repo(mutation))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"FAIL\S*\s+SC-002\s")
        self.assertRegex(r.stdout, r"FAILING:\S*\s+SC-002\b")
        self.assertIn("1 failing", r.stdout)


class EdgeCaseTest(_TempRepo):
    """Refinements check.py and checker/README.md describe."""

    def ctx(self, mutation=None, post=None):
        return check.Ctx(self.repo(mutation, post))

    def test_app_wrapper_layout_reads_project_files_below_app(self) -> None:
        def mutate(files):
            for rel in list(files):
                if rel.startswith(("config/", "composer.")):
                    files["app/" + rel] = files.pop(rel)
            files[".gitignore"] = (
                "/app/vendor/\n/app/var/\n/app/public/*\n.env\n*.prod.env\n"
            )

        ctx = self.ctx(mutate)
        self.assertEqual(ctx.proj, self.root / "app")
        for code in ("STRUCT-001", "STRUCT-004", "STRUCT-005", "STRUCT-007", "SEC-003"):
            with self.subTest(code=code):
                self.assertTrue(check.CHECKS[code](ctx)[0])

    def test_app_wrapper_rejects_root_anchored_vendor_ignore(self) -> None:
        def mutate(files):
            files["app/composer.json"] = files.pop("composer.json")

        self.assertFalse(check.c_struct007(self.ctx(mutate))[0])

    def test_restart_policy_makes_a_job_name_persistent(self) -> None:
        mutate = _replace(
            "compose.yaml",
            "  setup:\n    image: ${APP_IMAGE}\n",
            "  setup:\n    image: ${APP_IMAGE}\n    restart: always\n",
        )
        ok, detail = check.c_dro001(self.ctx(mutate))
        self.assertFalse(ok)
        self.assertIn("setup", detail)

    def test_list_form_depends_on_fails(self) -> None:
        mutate = _replace(
            "compose.yaml",
            "    depends_on:\n      db: {condition: service_healthy}\n"
            "      setup: {condition: service_completed_successfully}\n",
            "    depends_on: [db]\n",
        )
        self.assertFalse(check.c_dro002(self.ctx(mutate))[0])

    def test_job_dependency_with_wrong_condition_fails(self) -> None:
        mutate = _replace(
            "compose.yaml",
            "setup: {condition: service_completed_successfully}",
            "setup: {condition: service_healthy}",
        )
        self.assertFalse(check.c_dro002(self.ctx(mutate))[0])

    def test_dependency_without_condition_fails(self) -> None:
        mutate = _replace("compose.yaml", "db: {condition: service_healthy}", "db: {}")
        self.assertFalse(check.c_dro002(self.ctx(mutate))[0])

    def test_digest_in_a_comment_does_not_pin_a_task_image(self) -> None:
        mutate = _replace(
            "ci/pipeline.yml",
            'tag: "0.58.0"}',
            f"tag: latest}}  # aquasec/trivy@{DIGEST}",
        )
        self.assertFalse(check.c_sc007(self.ctx(mutate))[0])

    def test_unpinned_anchor_fails_the_task_that_uses_it(self) -> None:
        mutate = _replace("ci/pipeline.yml", 'tag: "3.20"', "tag: latest")
        self.assertFalse(check.c_sc007(self.ctx(mutate))[0])

    def test_supply_chain_step_only_in_unreferenced_anchor_fails(self) -> None:
        def mutate(files):
            files["ci/pipeline.yml"] = (
                files["ci/pipeline.yml"].replace("composer audit", "composer validate")
                + "unused: &unused\n  run: {path: sh, args: [-c, composer audit]}\n"
            )

        self.assertFalse(check.c_sc001(self.ctx(mutate))[0])

    def test_supply_chain_keyword_only_in_comment_fails(self) -> None:
        mutate = _replace(
            "ci/pipeline.yml",
            "--exit-code 1 --severity CRITICAL,HIGH app]}",
            "--severity CRITICAL,HIGH app]}  # --exit-code 1",
        )
        self.assertFalse(check.c_sc002(self.ctx(mutate))[0])

    def test_cosign_without_attestation_fails_with_reason(self) -> None:
        ok, detail = check.c_sc004(self.ctx(MUTATIONS["SC-004"][0]))
        self.assertFalse(ok)
        self.assertIn("no SBOM attestation", detail)

    def test_no_sbom_at_all_is_reported(self) -> None:
        mutate = _both(
            _replace("ci/pipeline.yml", "sbom-toolbox generate && ", ""),
            _replace("ci/pipeline.yml", " --type cyclonedx", ""),
        )
        ok, detail = check.c_sc003(self.ctx(mutate))
        self.assertFalse(ok)
        self.assertEqual(detail, "no SBOM generation in pipeline")

    def test_malformed_pipeline_fails_cleanly(self) -> None:
        for text in (
            "- just\n- a list\n",
            "jobs: {not: a list}\n",
            "jobs: [1, 2]\n",
            "{{{\n",
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                files = dict(GOLD)
                files["ci/pipeline.yml"] = text
                build_repo(root, files)
                ctx = check.Ctx(root)
                self.assertFalse(check.c_sc011(ctx)[0])
                self.assertFalse(check.c_sc001(ctx)[0])

    def test_renovate_allows_update_packages_job(self) -> None:
        mutate = _both(
            MUTATIONS["SC-009"][0],
            _set("renovate.json", "{}\n"),
        )
        self.assertTrue(check.c_sc009(self.ctx(mutate))[0])

    def test_vendored_assets_need_an_sbom_fragment(self) -> None:
        asset = "packages/site/Resources/Public/JavaScript/libs/x.min.js"
        self.assertFalse(check.c_sc016(self.ctx(_set(asset, "x\n")))[0])
        both = _both(_set(asset, "x\n"), _set("sbom-vendored.cdx.json", "{}\n"))
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            files = dict(GOLD)
            both(files)
            build_repo(root, files)
            self.assertTrue(check.c_sc016(check.Ctx(root))[0])

    def test_untracked_node_modules_are_not_vendoring(self) -> None:
        post = _add_after_build("node_modules/x/index.js", "1\n")
        self.assertTrue(check.c_sc016(self.ctx(None, post))[0])

    def test_untracked_env_file_is_fine(self) -> None:
        post = _add_after_build(".env", "DB_PASSWORD=x\n")
        ctx = self.ctx(None, post)
        self.assertTrue(check.c_dro011(ctx)[0])
        self.assertTrue(check.c_struct006(ctx)[0])

    def test_constant_true_dev_guard_fails(self) -> None:
        mutate = _replace(
            "config/system/additional.php",
            "if (\\TYPO3\\CMS\\Core\\Core\\Environment::getContext()->isDevelopment()) {",
            "if (true) { // isDevelopment()",
        )
        ok, detail = check.c_ciimg005(self.ctx(mutate))
        self.assertFalse(ok)
        self.assertIn("constant-true", detail)

    def test_filewriter_subclass_is_not_the_core_writer(self) -> None:
        mutate = _replace(
            "config/system/settings.php",
            "\\TYPO3\\CMS\\Core\\Log\\Writer\\FileWriter::class => ['logFile' => 'php://stderr']",
            "\\Acme\\MyCustomFileWriter::class => ['logFile' => '/var/log/x.log']",
        )
        self.assertTrue(check.c_dro016(self.ctx(mutate))[0])

    def test_bare_redis_image_is_unpinned(self) -> None:
        mutate = _replace("compose.override.yaml", "phpmyadmin:5.2.1", "redis")
        ok, detail = check.c_sc013(self.ctx(mutate))
        self.assertFalse(ok)
        self.assertIn("bare redis", detail)

    def test_pecl_options_are_not_packages(self) -> None:
        mutate = _replace(
            "Dockerfile", "pecl install apcu-5.1.24", "pecl install -f apcu"
        )
        self.assertEqual(
            check.c_sc015(self.ctx(mutate)), (False, "unpinned pecl install: apcu")
        )

    def test_empty_directory_scores_without_crashing(self) -> None:
        r = self.run_cli(self.root)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("repo-scope score", r.stdout)
        self.assertEqual(r.stderr, "")


class HelperTest(unittest.TestCase):
    def test_pinned(self) -> None:
        cases = {
            f"nginx@{DIGEST}": True,
            f"nginx:latest@{DIGEST}": True,
            "nginx:1.27": True,
            "registry.example.com:5000/nginx:1.27": True,
            "registry.netresearch.de/acme/app:latest": True,
            "registry.netresearch.de/acme/app": True,
            "nginx": False,
            "nginx:latest": False,
            "nginx:edge": False,
            "nginx:": False,
            "registry.example.com:5000/nginx": False,
            "evil.com/registry.netresearch.de/x:latest": False,
            "registry.netresearch.de.attacker.com/x:latest": False,
        }
        for image, expected in cases.items():
            with self.subTest(image=image):
                self.assertIs(check.pinned(image), expected)

    def test_settings_secret_free(self) -> None:
        cases = {
            "'password' => ''": True,
            "'password' => '%env(DB_PASSWORD)%'": True,
            "'password' => \"$_SERVER\"": True,
            "'passwordHashing' => ['className' => 'x']": True,
            "'password' => 'hunter2'": False,
            "'transport_smtp_password' => \"hunter2\"": False,
            "'encryptionKey' => 'zzz-not-hex'": False,
            "'installToolPassword' => \"$argon2\"": True,
            "'api_key' => 'abc'": False,
            "'apiKey' => 'abc'": False,
            "'github_token' => 'ghp_x'": False,
            "'clientSecret' => 'abc'": False,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIs(
                    check.settings_secret_free(f"<?php return [{text}];"), expected
                )

    def test_expand_placeholders(self) -> None:
        env = {"SET": "value", "EMPTY": ""}.get
        self.assertEqual(check._expand_placeholders("${SET}", env), "value")
        self.assertEqual(check._expand_placeholders("${UNSET}", env), "")
        self.assertEqual(check._expand_placeholders("${UNSET:-d}", env), "d")
        self.assertEqual(check._expand_placeholders("${EMPTY:-d}", env), "d")
        self.assertEqual(check._expand_placeholders("${SET:-d}", env), "value")
        self.assertEqual(check._expand_placeholders("a/${SET}:1", env), "a/value:1")

    def test_env_dist_expands_earlier_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".env.dist").write_text(
                "# c\n\nREG=registry.example.com\nIMG=${REG}/app:${TAG:-1.0}\nnoequals\n",
                encoding="utf-8",
            )
            env = check.Ctx(root).envdist
        self.assertEqual(
            env, {"REG": "registry.example.com", "IMG": "registry.example.com/app:1.0"}
        )

    def test_strip_yaml_comments(self) -> None:
        text = "a: 1  # note\n  # whole line\nb: 'x#y'\nc: 2 #\n"
        self.assertEqual(check._strip_yaml_comments(text), "a: 1\nb: 'x#y'\nc: 2")

    def test_additional_prod_safe(self) -> None:
        self.assertEqual(check.additional_prod_safe("<?php\n")[0], True)
        guarded = "if ($ctx->isDevelopment()) { $c['SYS']['displayErrors'] = 1; }"
        self.assertEqual(check.additional_prod_safe(guarded)[0], True)
        self.assertEqual(
            check.additional_prod_safe("$c['BE']['debug'] = true;")[0], False
        )
        self.assertEqual(
            check.additional_prod_safe(
                "if (1) { $c['SYS']['devIPmask'] = '*'; } // isDevelopment()"
            )[0],
            False,
        )

    def test_block_pinned(self) -> None:
        self.assertTrue(check._block_pinned(f"source: {{repository: x@{DIGEST}}}"))
        self.assertTrue(check._block_pinned(f"version: {{digest: '{DIGEST}'}}"))
        self.assertTrue(check._block_pinned('tag: "1.2"'))
        self.assertFalse(check._block_pinned("tag: latest"))
        self.assertFalse(check._block_pinned("tag: edge"))
        self.assertFalse(check._block_pinned("repository: x"))
        self.assertFalse(check._block_pinned(f"tag: latest  # {DIGEST}"))

    def test_git_unavailable_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ctx = check.Ctx(root)
            # not a repository: ls-files fails -> None, ls-files --error-unmatch -> False
            self.assertIsNone(ctx.git_ls_files())
            self.assertEqual(
                check.c_sc016(ctx), (True, "vendoring check skipped (git unavailable)")
            )


class CatalogueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = json.loads((CHECKER / "rules.json").read_text(encoding="utf-8"))

    def test_every_repo_scope_rule_has_a_check(self) -> None:
        repo_codes = {r["code"] for r in self.rules["rules"] if r["scope"] == "repo"}
        self.assertEqual(repo_codes, set(check.CHECKS))

    def test_every_advisory_rule_has_a_note(self) -> None:
        advisory = {r["code"] for r in self.rules["rules"] if r["scope"] == "advisory"}
        self.assertEqual(advisory, set(check.ADVISORY_NOTE))

    def test_rule_count_matches_the_docs(self) -> None:
        self.assertEqual(len(self.rules["rules"]), 76)
        self.assertEqual(len(check.CHECKS), 72)

    def test_pinned_hash_matches_the_catalogue(self) -> None:
        self.assertEqual(gen_rules._catalogue_sha256(), gen_rules.CATALOGUE_SHA256)
        self.assertEqual(self.rules["catalogue_sha256"], gen_rules.CATALOGUE_SHA256)

    def test_regenerating_reproduces_committed_rules_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / "gen_rules.py"
            shutil.copy(CHECKER / "gen_rules.py", copy)
            r = subprocess.run(
                [sys.executable, str(copy)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("WARNING", r.stdout)
            self.assertEqual(
                (pathlib.Path(tmp) / "rules.json").read_bytes(),
                (CHECKER / "rules.json").read_bytes(),
            )

    def test_drift_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / "gen_rules.py"
            text = (CHECKER / "gen_rules.py").read_text(encoding="utf-8")
            anchor = '"AGENTS.md must exist at repository root"'
            self.assertIn(anchor, text)
            copy.write_text(
                text.replace(anchor, '"AGENTS.md must exist"'), encoding="utf-8"
            )
            r = subprocess.run(
                [sys.executable, str(copy)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("WARNING: catalogue drift", r.stdout)
            self.assertIn(
                f"pinned   CATALOGUE_SHA256 = {gen_rules.CATALOGUE_SHA256}", r.stdout
            )


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
