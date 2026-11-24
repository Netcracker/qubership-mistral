# Mistral 21

This directory is a **self-contained build root** for Mistral 21, kept side by side
with the current major in `../mistral/`.

## Layout

| Path | Version | Role |
|------|---------|------|
| `../mistral/` | current major | current product; new work lands here |
| `mistral21/` | 21 | previous major; supported, security fixes only |

Directory suffixes name **the version being retired**, so `mistral21/` keeps its name
until 21 is dropped. `../mistral/` is always the current major and is never renamed.

## Build

The Docker build context is this directory, not the repo root:

```bash
docker build -f mistral21/Dockerfile mistral21 -t qubership-mistral-21:local
```

Declared in `.github/docker-build-config.json` and `.github/workflows/push.yml` as a
separate component, mirroring `docker-redis/7` and `docker-redis/8` in
`Netcracker/qubership-redis`.

## Test

```bash
cd mistral21
tox -e py3            # unit tests, .stestr.conf -> ./mistral/tests/unit
```

All `tox.ini` and `.stestr.conf` paths are `{toxinidir}`-relative, so no edits are
needed when running from inside this directory.

## Version-specific files

These differ from the repo root and must be kept in sync deliberately:

| File | Here (21) | Repo root (current) |
|------|-----------|---------------------|
| `Dockerfile` | `PBR_VERSION="21.0.0"`, installs `nc_requirements-21.txt` | current version, `nc_requirements.txt` |
| `nc_requirements-21.txt` | 21 pins | `nc_requirements.txt` = current pins |
| `opensource_version.py` | `MISTRAL_VERSION = '21.0.0'` | current version |

`requirements.txt`, `test-requirements.txt`, `setup.cfg`, `setup.py`, `tox.ini`,
`.stestr.conf`, `.coveragerc`, `config/` and `tools/` are copied from the root and
should be updated here only when a change genuinely applies to 21.

Both trees declare `name = mistral` in `setup.cfg` and export the same console
scripts (`mistral-server`, `mistral-db-manage`, ...). They are never installed into
the same environment: each Docker image installs exactly one tree.

## Database migrations

Each tree carries its **own** two migration chains:

- `mistral/db/sqlalchemy/migration/alembic_migrations/versions/` (upstream, 45 files in 21)
- `mistral/db/sqlalchemy/nc_migration/nc_alembic_migrations/versions/` (NetCracker, 5 files in 21)

A database is migrated by the `mistral-db-manage` that ships in the image being
deployed, so a 21 deployment runs 21's chains and a 22 deployment runs 22's.
Do not merge the two trees' chains.

## Retirement

Support window is **current + previous**. When the next major (23) lands:

1. snapshot the then-current tree to `mistral22/`
2. upgrade `../mistral/` to 23
3. delete this directory, plus:
   - the `qubership-mistral-21` component in `.github/docker-build-config.json`,
     `.github/workflows/push.yml` and `.github/clean.yml`
   - the `mistral21:` block in the operator chart `values.yaml` and
     `values.schema.json`
   - `delivery/mistral/21.0.0/`, the `.manifest-21` job, its promote snippet and
     its CCI row in `PROD.Platform.HA/mistral-operator`
