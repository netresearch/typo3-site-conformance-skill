# Migrating a legacy site repo to gold conformance

Transforming a `support/typo3-NN/app`-style repo (the de-facto pattern) into a
gold-conformant one. The runnable end state is `typo3-14-gold`; diff against it.

## The seven moves

1. **Flatten to root.** Move the TYPO3 Composer project out of `app/` so
   `composer.json`, `config/`, `public/`, `vendor/` are at the repo root.
   Delete `build/config/` — `config/system/settings.php` + `config/system/additional.php`
   live at the composer-project root (`STRUCT-001/008`).
2. **De-secret the config.** Strip every credential, hash, debug flag and host
   wildcard from `settings.php`. Inject them at runtime in `additional.php` from
   `$_SERVER` (`encryptionKey`, install-tool password, DB creds, cache auth,
   SMTP). `.env` is git-ignored; `.env.dist` is the schema (`SEC-*`, `STRUCT-002/003`).
3. **Rename + pin Compose.** `docker-compose.yml` → `compose.yaml`; dev overlay →
   `compose.override.yaml` (drop `COMPOSE_FILE=a:b:c`). Pin every image by digest;
   add `healthcheck`, `deploy.resources.limits`, `restart` to persistent
   services (`CI-IMG-*`, `DRO-001/003`).
4. **Redis → Valkey.** Swap the cache image to `valkey/valkey`, add
   `--requirepass`, `--maxmemory` + `--maxmemory-policy allkeys-lru`, `--save ""`
   and no AOF (`DRO-004/005/006/008`).
5. **Sandbox the scheduler.** ofelia must not mount `docker.sock`; route it
   through `tecnativa/docker-socket-proxy` with only `CONTAINERS`/`EXEC`/`POST`
   (`DRO-007`).
6. **Harden the pipeline.** Add, in order: `composer audit` → build → Trivy
   `--exit-code 1` gate → CycloneDX SBOM → push → `cosign sign`. Move dependency
   updates to a merge request. Add a weekly restore-verification job. Verify the
   `fly` download checksum in GitLab CI (`SC-*`, `DRO-013`).
7. **Build hardening.** Multi-stage Dockerfile; `COMPOSER_AUTH` as a BuildKit
   secret (never an `ARG`); non-root final stage; OCI labels; SGID (`g+s`) not
   SUID on writable dirs (`CI-IMG-013/015`, `SC-005`).

## Verify

Run the executable checker against the migrated repo:

```bash
python3 tools/conformance/check.py .   # from a typo3-14-gold checkout, or vendored
```

Target: 100 % of repo-scope rules. The four advisory rules
(`DRO-019` three-repo split, `DEPLOY-001` ci-colocation, `DRO-017` php-fpm
status, `DRO-018` uptime monitoring) are estate/runtime concerns — report, do
not gate.
