# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## What This Project Is

Qubership Mistral is a workflow engine forked from OpenStack Mistral. Workflows are YAML (YAQL `<% %>` or Jinja2
`{{ }}`). The repository ships two things:

1. **Mistral services** (Python): `api`, `engine`, `executor`, `notifier`(all started by
   `mistral-server`) and `monitoring` (started by `mistral-monitoring`).
2. **`operator/`**: a [Kopf](https://kopf.readthedocs.io/) Kubernetes operator (`netcracker.com/v2` `MistralService`)
   that deploys the services and runs the DB jobs.


## Repository Structure

| Path | Purpose |
|------|---------|
| `mistral/api/` | REST API controllers (Pecan, `controllers/v2/`) |
| `mistral/engine/`, `mistral/workflow/` | Orchestration, task scheduling, workflow state machine |
| `mistral/executors/`, `mistral/notifiers/` | Action execution; event publishing |
| `mistral/services/`, `mistral/scheduler/`, `mistral/event_engine/` | Core services, cron triggers, event triggers |
| `mistral/actions/`, `mistral/expressions/` | Built-in actions; YAQL/Jinja evaluators |
| `mistral/monitoring/` | Prometheus metrics (FastAPI) and `jobs/` recovery jobs |
| `mistral/config.py`, `mistral/policies/` | All config options and defaults; RBAC policy rules |
| `mistral/db/sqlalchemy/` | ORM models, `migration/` (upstream Alembic), `nc_migration/` (NetCracker Alembic) |
| `mistral/tests/unit/` | Unit tests (stestr, see `.stestr.conf`) |
| `operator/src/`, `operator/src/tests/` | Operator code (`handler.py`) and its pytest tests |
| `operator/deployments/charts/mistral-operator/` | Helm chart: `crds/crd.yaml`, `templates/`, `values.yaml`, `values.schema.json` |
| `operator/deploy/` | Plain-YAML install set (legacy; its `crd.yaml` is a stub, see Compatibility) |
| `tests/robot/`, `tests/custom-actions/` | Robot Framework E2E suite and custom-action test images |
| `releasenotes/notes/`, `doc/source/`, `custom_doc/` | Reno notes, Sphinx docs, user docs |
| `agent-packages/` | APM packages for agent skills (see Generated Code) |

## Compatibility Rules

These contracts must not break. Before editing any of them, run the check listed; if it shows a break, **stop and ask
a human** with the diff and a migration plan. Do not implement the break.

- **REST API** (`mistral/api/controllers/v2/`): never remove or rename a route, field or status code. Check:
  `git diff origin/main -- mistral/api | grep -E '^-\s+@(pecan\.expose|wsme_pecan\.wsexpose)'` must print nothing.
  Never edit existing assertions in `mistral/tests/unit/api/` to make them pass.
- **Policy names** (`mistral/policies/`): never rename or remove a rule. Check:
  `git diff origin/main -- mistral/policies | grep -E '^-\s+name='` must print nothing.
- **Config options** (`mistral/config.py`): never rename or remove an option or change a default. Adding is fine.
- **Helm values** (`values.yaml`): never remove or rename a key; a new key needs a matching entry in
  `values.schema.json`. Check: `helm template mistral-operator operator/deployments/charts/mistral-operator`
  exits 0 with default values.
- **CRD** `operator/deployments/charts/mistral-operator/crds/crd.yaml` (version `v2`) is the source of truth. Never
  remove or tighten a field in `spec`. `operator/deploy/crd.yaml` is a 15-line `v1` stub; do not copy the chart CRD
  into it and do not edit it without asking.
- **DB migrations**: never edit, renumber or delete an existing file under `.../versions/`. Add a new one (next
  number after `044_*.py` upstream; Alembic hash for `nc_migration`). Destructive changes (drop table/column, type
  narrowing) need human approval. Migrations must work on SQLite (tests) and PostgreSQL (production).
- **Standard workflows/actions** in `mistral/resources/`: never rename or remove one.

## Guardrails

- Credentials come from Kubernetes secrets or config volumes; never log, print or hard-code
  them in CRs, manifests, defaults or tests.
- Never change workflow/task execution state outside `mistral/engine/` and `mistral/workflow/`.
- Never hand-edit files under `agent-packages/**/references/` and `doc/source/**`(upstream docs).
- Never commit `.tox/`, `.venv*/`, `.stestr/`, `*.sqlite`, `mistral.log`, `cover/`, `doc/build/`, `etc/*.sample` that
  are generated. Run `git status` before staging; only intended files may be listed.
- Never bump a dependency by hand (Renovate does it); never change pins in `nc_requirements.txt` without asking.

## Generated Code

Never edit these by hand. Change the source, regenerate, and commit the result when it is tracked.

| Generated file | Source | Command | Tracked |
|----------------|--------|---------|---------|
| `etc/mistral.conf.sample` | `mistral/config.py` | `tox -e genconfig` | no (git-ignored) |
| `etc/policy.yaml.sample` | `mistral/policies/` | `tox -e genpolicy` | no (do not commit) |
| `.agents/`, `.claude/`, `.cursor/`, `.github/instructions/` | `agent-packages/**/.apm/`, `apm.yml` | `apm install` | yes |
| `agent-packages/**/references/` | `custom_doc/troubleshooting.md` | edit the source; CI workflow `sync-troubleshooting-skill.yml` copies it | yes |

- After `apm install`, `git status` must list only files under the paths above. If `apm install` fails for any
  reason (hash mismatch, "no trustworthy local deployment baseline"), stop and ask a human.

## Test Changes

Setup once. `tox -e py3` alone does not install `nc_requirements.txt`, but unit tests need `confluent-kafka` and
`setuptools==81.0.0` from it, so use a venv (`psycopg2` needs libpq headers; if it fails to build, run
`pip install psycopg2-binary`):

```bash
python3 -m venv .venv && . .venv/bin/activate
PIP_NO_BUILD_ISOLATION=0 pip install -r requirements.txt -r test-requirements.txt -r nc_requirements.txt && PIP_NO_BUILD_ISOLATION=0 pip install -e .
```

Commands by trigger (all from the repo root, venv active):

| After changing | Run | Pass condition |
|----------------|-----|----------------|
| any `mistral/**/*.py` | `bash tools/prepare_db.sh sqlite && stestr run` | exit 0, `Failed: 0` |
| a single module (fast loop) | `stestr run mistral.tests.unit.workflow.test_states --concurrency 1` | exit 0 |
| any `*.py` | `git diff --name-only --diff-filter=d origin/main -- '*.py' | xargs -r flake8` | no output |
| `mistral/config.py` | `tox -e genconfig` then `PATH=$PWD/.tox/genconfig/bin:$PATH tools/config/check_uptodate.sh` | both exit 0 |
| `mistral/policies/` | `tox -e genpolicy` | exit 0 |
| `agent-packages/**` | `apm install` | exit 0 (see Generated Code) |
| `operator/src/**` | `pip install -r operator/build/requirements.txt pytest && (cd operator/src && python -m pytest tests/)` | exit 0, no failures |
| `operator/deployments/charts/**` | `ct lint --config .github/ct.yaml --target-branch main` and `helm template mistral-operator operator/deployments/charts/mistral-operator` | both exit 0 |

Robot tests are at `tests/robot/**`.

## Definition of Done

- [ ] `stestr run` shows `Failed: 0` for any change under `mistral/`
- [ ] `flake8` on changed `.py` files prints nothing
- [ ] Regeneration run for every trigger in "Generated Code"; no ignored/sample file staged
- [ ] No Backward Compatibility check shows a break; no Prohibited Actions grep prints anything
- [ ] Chart changes: `ct lint` and `helm template` exit 0; operator changes: `pytest` exit 0
