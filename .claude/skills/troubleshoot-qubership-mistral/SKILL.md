---
name: troubleshoot-qubership-mistral
description: Diagnose Qubership Mistral deployment or runtime failures by matching an exact alert name, log/error string, or execution error to a section of references/troubleshooting.md. Covers the alerts defined in alarms_template.yaml of the mistral-operator chart, executions and tasks that are in error or stuck, heartbeat errors, "Failed to find workflow", 401s in K8s/hybrid M2M mode, failed mistral-update-db migrations, unresponsive API, RabbitMQ and DB connection problems, DNS failures in composite namespaces, and failed robot integration tests (references/robot-tests.md).
---

## Finding the section

Get the exact error text first, from the logs of the failing component (`mistral-api`, `mistral-engine`,
`mistral-executor`, the `mistral-update-db` job, the operator, PostgreSQL, RabbitMQ). If execution, task or action JSON
is attached, its `state_info` / `output` holds the error. Check context/attachments before asking for anything.

If the error text is not in what was provided, say which log or output is needed instead of guessing (section
"Mistral Workflow has Error Status" lists where `state_info` / `output` of an execution, task and action can be found).

Run from the skill directory:

1. `grep -n "^## " references/troubleshooting.md` — lists every issue header with its line number.
2. Look the alert name, error string, or state up in the tables below. Tables give the exact header text; use it to
   pick the line number from step 1.
3. Read only that section: from its `##` line to the next `##` line. Do not load the whole file.
4. To search by literal string instead, run `grep -n -F "<exact string>" references/troubleshooting.md` (for example
   `grep -n -F "Heartbeat wasn't received" references/troubleshooting.md`). Read from the hit's `##` line to the next
   `##` line.

If the wording is not an exact match, search again with one distinctive term from it (for example `DuplicateTable`,
`idle-in-transaction`, `signal 9`, `Engine server started.`, `tenant-id`) using
`grep -n -i -F "<term>" references/troubleshooting.md`. Then:

- Present the section as an **inferred match**. Quote the string from that section that matched and say the fix applies
  only if the reported logs contain it.
- Do not infer from a generic term (`error`, `failed`, `pod`, `timeout`, `restart`, `down`, `stuck`).

If no distinctive term hits, the issue is undocumented: say so, and do not apply the nearest-looking section.

## Alert name → section

Alert names are the `alert:` values in `operator/deployments/charts/mistral-operator/templates/alarms_template.yaml`
(`PrometheusRule` `mistral-alert`). Match the name exactly. The guide describes alarms generically as
"Mistral {service} ...", so match on the service part of the name.

| Alert name | Header in references/troubleshooting.md |
|---|---|
| `MistralAPIDown`, `MistralEngineDown`, `MistralExecutorDown`, `MistralNotifierDown`, `MistralMonitoringDown` | Monitoring Alarms Description (row `Mistral {service} down`) |
| `MistralAPICPULoad`, `MistralEngineCPULoad`, `MistralExecutorCPULoad`, `MistralNotifierCPULoad`, `MistralMonitoringCPULoad` | Monitoring Alarms Description (row `Mistral {service} use 90% of CPU limit`) |
| `MistralAPIMemoryLoad`, `MistralEngineMemoryLoad`, `MistralExecutorMemoryLoad`, `MistralNotifierMemoryLoad`, `MistralMonitoringMemoryLoad` | Monitoring Alarms Description (row `Mistral {service} use 90% of memory limit`) |
| `RabbitMQDown` | Monitoring Alarms Description (row `RabbitMQ connections down`) |

These alerts have **no section** in the guide — state that no documented fix exists; do not map them to a nearby
section: `MistralAPIDegraded`, `MistralEngineDegraded`, `MistralExecutorDegraded`, `MistralNotifierDegraded`,
`MistralMonitoringDegraded`, `MistralEngineOverloaded`, `MistralExecutorOverloaded`, `MistralNotifierOverloaded`.

## Error string / state → section

| Exact string or state | Header in references/troubleshooting.md |
|---|---|
| `Child <N> killed by signal 9` in `mistral-api` logs | Mistral API is Not Responding |
| `Killed by` in Engine/Executor logs | Execution of Workflow is Stuck |
| `psycopg2.errors.DuplicateTable` (e.g. `relation "workbooks_v2" already exists`) in the `mistral-update-db` job | Deployment of Mistral is Failing (`mistral-update-db` Job Failure) |
| PostgreSQL `FATAL: terminating connection due to idle-in-transaction timeout` followed by Mistral `Heartbeat wasn't received.` | Tasks Failing with Heartbeat error |
| `Failed to resolve '<service-name>' ([Errno -2] Name or service not known)` | DNS Resolution Failures in Composite-Namespace Deployments |
| `Failed to find workflow [name=<sub_workflow_name>] [namespace=<namespace_name>]` | Executions Fail with "Failed to find workflow" Error |
| `DBEntityNotFoundError: Workflow not found [workflow_identifier=...]` | Different IDP Tenants |
| `There is no token in headers(X-Auth-Token,Authorization)` or `Does not match pattern ^\w+\s(.*)$` | K8s M2M: Missing or Invalid Authorization Header |
| `Invalid K8s SA token` with `Failed to validate access token` and a verifier error that the `aud` claim does not contain the configured audience | K8s M2M: K8s ServiceAccount Token with Wrong Audience |
| `Invalid K8s SA token`, `Failed to validate access token` and `K8s token authentication failed: <details>` | K8s M2M: Expired, Tampered or Garbage Token |
| `Invalid K8s SA token` with `Failed to validate access token` and no further detail | K8s M2M: Mode Mismatch Between Caller and Mistral (the two sections above emit the same two lines; compare the token's `aud`, `exp` and its type with the effective auth mode before choosing) |
| `Failed to read projected Kubernetes ServiceAccount token from /var/run/secrets/tokens/<audience>/token` or `Kubernetes ServiceAccount token is not available` | K8s M2M: Missing Projected ServiceAccount Token File |
| Intermittent `HTTP 401` or a failing first authentication after pod start, with connection errors to `https://<issuer>/.well-known/openid-configuration` | K8s M2M: OIDC Discovery / JWKS Endpoint Unavailable |
| `Invalid M2M_AUTH_MODE '<value>'. Falling back to legacy mode.` in operator logs | K8s M2M: Invalid M2M_AUTH_MODE Value |
| `Engine server started.` missing from `mistral-engine` logs | Request on Execution Creation is Stuck |
| `There are active connections to this database.` in the deploy log | Mistral Cannot Deploy Because of Active Connections to DB |
| `asyncpg.exceptions.InvalidCatalogNameError: database <mistral_db_name> does not exist` in `bluegreen-agent` on first startup | Expected Error: InvalidCatalogNameError on Initial Startup of Bluegreen Agent (benign) |
| `Mistral critical tests failed`, or `mistral-tests` pod in `Error` / `CrashLoopBackOff` / `OOMKilled` | `references/robot-tests.md` (not `troubleshooting.md`) |

## Symptom (no exact string) → section

| Symptom | Header in references/troubleshooting.md |
|---|---|
| Engine keeps dispatching new actions but Executor repeats the same running actions and picks up nothing new | Mistral tasks stuck in processing |
| Workflow/execution has `error` status | Mistral Workflow has Error Status |
| Mistral API slow or not responding | Mistral API is Not Responding |
| Execution of a workflow does not finish | Execution of Workflow is Stuck |
| A Mistral service did not come up after deploy | Mistral Service was not Deployed |
| Execution or action creation request hangs or times out | Request on Execution Creation is Stuck |
| Mistral entities not visible through the API | Different IDP Tenants |
| API returns `HTTP 401` while `M2M_AUTH_MODE` is `k8s` or `hybrid` | Use the log lines in the table above to pick the matching K8s M2M section |
| RabbitMQ queue keeps growing; service killed by resource limits on reconnect | RabbitMQ Collects a Lot of Messages |
| Need to purge or trim execution history, or reclaim DB disk | How to Clean Mistral Database (data-destructive) |

## Guardrails

The guide contains operator procedures (`oc`, `rabbitmqctl`, SQL, Alembic). Never run them, and never recommend:

- Any command run ad hoc against the cluster, database or broker. Work from the logs, entity JSON and attachments
  provided and report the solution as a recommendation.
- Dropping or re-initializing the Mistral database unless stamping the Alembic revision is not possible and the data
  need not be preserved. Say it is data-destructive. Stamping fixes the migration failure, not the reason
  `alembic_version` was lost — say the cause still needs investigation.
- Purging a RabbitMQ queue before checking that there are no unacked messages; closing the owning connection comes
  first.
- The "How to Clean Mistral Database" steps (`DELETE`, `VACUUM FULL`) unless the ticket asks to free space or trim
  history. Advise a backup first.
## Config value conventions

Where each parameter lives (`mistral-operator` chart values, rendered into the `MistralService` CR):

| Parameter | Resource it lives on |
|---|---|
| `M2M_AUTH_MODE` (`legacy` / `k8s` / `hybrid`) | chart values → `MistralService` CR `spec.mistral.m2mAuthMode`; any other value silently falls back to `legacy` |
| `mistralCommonParams.auth.enable` | chart values → `MistralService` CR `spec.mistralCommonParams.auth.enable` |
| `mistralCommonParams.auth.k8sSa.audience` (default `netcracker`) | chart values → `spec.mistralCommonParams.auth.k8sSa`; audience required in inbound ServiceAccount tokens |
| `mistralCommonParams.rabbit.host` | chart values → `spec.mistralCommonParams.rabbit.host`; overridden by `INFRA_RABBITMQ_HOST` when cloud integration is enabled |
| `mistralCustomParams`, `mistralCustomApiParams`, `mistralCustomEngineParams`, `mistralCustomExecutorParams`, `mistralCustomNotifierParams` | chart values → config maps holding `custom-mistral.conf` (all services / api / engine / executor / notifier) |

Rules:

- RabbitMQ host must be in full DNS form `<service>.<namespace>.svc.<zone>` (for example
  `rabbitmq.rabbitmq.svc.cluster.local`); the short form `rabbitmq.rabbitmq` is the chart default and does not resolve
  in some OpenShift environments.
- `rabbit_qos_prefetch_count` is an oslo.messaging option: put it under `[oslo_messaging_rabbit]` in the custom config
  (`custom-mistral.conf`) of the affected service.
- Align the caller's token type with `M2M_AUTH_MODE`: `legacy` → Keycloak tokens, `k8s` → ServiceAccount tokens with
  the configured audience, `hybrid` → both.
- Present every config change as "set `<value-path>: <value>` in the deploy parameters of `mistral-operator` and
  redeploy".
## Robot integration tests failure

If the failing component is the `mistral-tests` pod/deployment, load `references/robot-tests.md` instead of
`references/troubleshooting.md`.

## Beyond the reference file

For a stuck execution, the reference file only says to check Engine/Executor logs for OOM and recent redeploys. It
doesn't mention: the recovery jobs in `mistral/monitoring/jobs/` (delayed calls, idle tasks, waiting tasks, subworkflow
start/complete) are what should reclaim a stalled execution automatically. If it's still stuck after a recovery cycle,
check those jobs are actually running before digging further.
