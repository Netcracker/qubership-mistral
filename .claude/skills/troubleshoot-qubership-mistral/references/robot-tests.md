# Troubleshooting Robot Integration Tests

`tests/robot/` contains the Robot Framework integration-test suite for Qubership Mistral. It is packaged as a Docker image and run as the `mistral-tests` Kubernetes Deployment when `integrationTests.enabled` is true.

The general failure signatures are:

- The `mistral-tests` pod/deployment is in `Error`, `CrashLoopBackOff`, or `OOMKilled` state.
- The Mistral CR/operator reports `Mistral critical tests failed`.
- Specific test groups fail or are unexpectedly skipped.

## Integration-tests chart parameters

| Parameter | Effect on test execution |
|---|---|
| `integrationTests.enabled` | Creates the `mistral-tests` Deployment and service. If false, no test pod is deployed. |
| `integrationTests.runTestsOnly` | When true, the operator skips deploying/updating Mistral services and only runs the test pod. Use for re-running tests against an already-running Mistral instance. |
| `integrationTests.runBenchmarks` | When true, sets `RUN_BENCHMARKS=True` in the test pod and the tag filter excludes functional suites (`basic`, `security`, `dr`, `heartbeat`) and runs only `mistral_svt` benchmark tests. When false, `mistral_svt` and `benchmark_skip` tests are excluded. |
| `integrationTests.waitTestResultOnJob` | When true, the operator blocks reconciliation until tests finish and marks the CR as failed if critical tests fail. When false, the operator marks install successful and checks test status in a background thread. |
| `integrationTests.waitTestResultTimeout` | How long (seconds) the operator waits for the `mistral-tests` Deployment to report a result before treating it as failed. |
| `integrationTests.mistralReadyTimeout` | How long (seconds) the test pod waits for all Mistral deployments (`app=mistral`) to be ready before starting Robot execution. |
| `integrationTests.dockerImage` | Test runner image; default is `ghcr.io/netcracker/qubership-mistral-tests:main`. |
| `integrationTests.prometheusUrl` | Required for `alerts` tests. Sets `PROMETHEUS_URL` env var; if unset, the `alerts` tag is excluded. |

## How tests are organized

- `tests/robot/tests/Mistral.robot` — functional/integration tests. Key tags:
  - `basic` — core workflow execution, skip/retry/join, Jinja/YAQL expressions, notifications, HTTP/oauth2 actions, idempotent execution, task skip, dry-run, etc.
  - `security` — authentication/401 checks. Requires `AUTH_ENABLE=true`.
  - `dr` — disaster-recovery / pause-mode tests.
  - `heartbeat` — heartbeat test.
  - `http`, `notifications` — feature-specific subsets.
  - `custom-actions` — always excluded by the tag filter (relies on OpenStack custom actions).
  - `noncritical` — tests that may fail without failing the overall suite.
  - `mistral_images`, `mistral_container_hardening`, `dbaas` — deploy-descriptor / platform checks.
- `tests/robot/tests/Mistral_svt.robot` — stress/scale/benchmark tests. Key tags:
  - `mistral_svt` — all SVT cases.
  - `benchmark_skip` — skipped when `RUN_BENCHMARKS=true` (too heavy for a benchmark run).
  - `smoke` — lighter SVT cases.
  - Sub-tags: `delayed_calls`, `context_merge`, `nested_wfs`.
- `tests/robot/Alerts.robot` — Prometheus alert tests. Tagged `alerts`. Requires `PROMETHEUS_URL`.
- `tests/robot/tests/tags_exclusion.py` — helper used by the base test image to compute Robot `--exclude` tags from environment:
  - `RUN_BENCHMARKS` true → exclude `basic`, `security`, `dr`, `heartbeat`, `benchmark_skip`; include `mistral_svt`.
  - `RUN_BENCHMARKS` false → exclude `mistral_svt`.
  - `AUTH_ENABLE` false → also exclude `security`.
  - `PROMETHEUS_URL` unset → also exclude `alerts`.
  - `custom-actions` is always excluded.
- `tests/robot/workflows/` — YAML workflow fixtures loaded by the tests.
- `tests/robot/lib/` — Python helper libraries (Mistral API client, Kubernetes utils, workflow generators, HTTP mock server).
- `tests/robot/Dockerfile` and `tests/robot/entrypoint.sh` — build the `mistral-tests` image on top of `ghcr.io/netcracker/qubership-docker-integration-tests`.
- `tests/robot/mistral_pods_checker.py` — executed at startup to wait for Mistral deployments to become ready (`mistralReadyTimeout` applies here).

## Common failure modes and troubleshooting steps

### 1. `mistral-tests` pod is stuck or crashing

- Check pod status and events
- Look for `ImagePullBackOff`, `OOMKilled`, `RunContainerError`, or security-context/volume mount errors.
- Read the container logs

### 2. Tests fail immediately with connection/API errors

- The test pod waits for all Mistral deployments (`app=mistral`) to be ready before running Robot. This is controlled by `integrationTests.mistralReadyTimeout` (default 90s).
- Verify Mistral pods are actually ready
- If a Mistral service is not ready, fix that service first; the robot reference does not replace general Mistral troubleshooting.

### 3. Specific test groups are unexpectedly skipped or fail

- Inspect the environment variables in the `mistral-tests` pod:
  - `AUTH_ENABLE` must be `true` for `security` tests to run.
  - `PROMETHEUS_URL` must be set for `alerts` tests to run.
  - `RUN_BENCHMARKS` determines whether `basic` or `mistral_svt` tests run.
- Cross-check with `tests/robot/tests/tags_exclusion.py` logic.
- If auth is disabled but `security` tests are expected, either enable Mistral auth or accept that security tests are skipped.
- If alert tests fail with Prometheus errors, verify `integrationTests.prometheusUrl` points to a reachable Prometheus and that Mistral alerts are loaded.

### 4. Benchmark / SVT tests time out

- `Mistral_svt.robot` cases have large per-test timeouts (up to 1200 seconds). If Mistral is slow or overloaded, increase `waitTestResultTimeout`.
- Check Mistral Engine and Executor logs for OOM kills, DB connection issues, or RabbitMQ backlogs.
- Heavy context-merge or nested-workflow cases may need larger Engine/Executor resources or DB tuning.

### 5. Operator reports `Mistral critical tests failed`

- When `waitTestResultOnJob=true`, the operator waits for the `IntegrationTestsExecutionStatus` condition on the `mistral-operator` Deployment and fails the CR if the condition type is `Failed`.
- Read operator logs for the summary line `Robot Tests result Summary:`.
- Read the full `mistral-tests` logs and any Robot output artifacts to identify the failing test case.
- If `waitTestResultOnJob=false`, the operator marks the install successful and checks the result in a background thread; failures are still logged but do not block the CR from becoming successful.

### 6. `runTestsOnly=true` but tests cannot reach Mistral

- This mode assumes Mistral services are already deployed and reachable.
- The test pod uses `http(s)://mistral:8989/v2`; verify the `mistral` service exists in the namespace and the API is responding.
- If TLS is enabled for the API (`mistral.tls.services.api.enabled`), the test pod mounts the TLS secret and uses `https://mistral:8989/v2`.

## Relevant source files

- Test image: `tests/robot/Dockerfile`, `tests/robot/entrypoint.sh`
- Tag filtering: `tests/robot/tests/tags_exclusion.py`
- Pod readiness check: `tests/robot/mistral_pods_checker.py`
- Operator test orchestration: `operator/src/kubernetes_helper.py`
  - `run_tests`
  - `generate_robot_tests_pod_template_body`
  - `check_if_tests_are_failed`
  - `set_deploy_status_and_run_tests`
- Chart parameters: `operator/deployments/charts/mistral-operator/values.yaml` (`integrationTests`)
