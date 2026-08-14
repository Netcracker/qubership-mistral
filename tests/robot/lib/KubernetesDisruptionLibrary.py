# Copyright 2025 - NetCracker Technology Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time
from urllib.parse import quote
import requests
from kubernetes import client, config
from robot.api import logger
from robot.utils import asserts


def _console(msg):
    """Print to Robot console output (visible in CI/stdout), not only log.html."""
    logger.console(str(msg))
    logger.info(str(msg))


def upsert_ini_section(config_text, section, param_lines):
    """Insert or replace keys under [section] in an INI-style config string.

    param_lines: iterable of 'key = value' (or 'key=value') strings.
    """
    config_text = config_text or ""
    lines = config_text.splitlines()
    section_header = f"[{section}]"

    updates = {}
    for raw in param_lines:
        line = (raw or "").strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line (expected key=value): {raw!r}")
        key, value = line.split("=", 1)
        updates[key.strip()] = value.strip()

    if not updates:
        return config_text

    section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            section_idx = i
            break

    if section_idx is None:
        new_lines = list(lines)
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(section_header)
        for key, value in updates.items():
            new_lines.append(f"{key} = {value}")
        return "\n".join(new_lines) + ("\n" if config_text.endswith("\n") else "")

    # Walk section body and replace existing keys; append missing ones before next section
    i = section_idx + 1
    seen = set()
    out = lines[:section_idx + 1]
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        if stripped and not stripped.startswith("#") and not stripped.startswith(";") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key} = {updates[key]}")
                seen.add(key)
                i += 1
                continue
        out.append(lines[i])
        i += 1

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key} = {value}")

    out.extend(lines[i:])
    result = "\n".join(out)
    if config_text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


class KubernetesDisruptionLibrary:
    ROBOT_LIBRARY_SCOPE = 'GLOBAL'

    def __init__(self, namespace="mistral", rabbitmq_url=None,
                 rabbitmq_admin_user="guest", rabbitmq_admin_password="guest",
                 rabbitmq_vhost="/"):
        """
        Initialize Kubernetes disruption library.

        Args:
            namespace: Kubernetes namespace where Mistral is deployed
            rabbitmq_url: RabbitMQ management API URL (e.g., http://rabbitmq:15672)
            rabbitmq_admin_user: RabbitMQ management admin username
            rabbitmq_admin_password: RabbitMQ management admin password
            rabbitmq_vhost: RabbitMQ vhost (default: /)
        """
        self._namespace = namespace
        self._rabbitmq_url = rabbitmq_url
        self._rabbitmq_vhost = quote(rabbitmq_vhost or "/", safe="")
        self._rabbitmq_auth = requests.auth.HTTPBasicAuth(rabbitmq_admin_user, rabbitmq_admin_password)

        self._api_client = None
        self._apps_api = None
        self._core_api = None

    def _qpath(self, queue_name):
        """URL-encoded queue segment for RabbitMQ management API paths."""
        return quote(str(queue_name), safe="")

    def _ensure_k8s(self):
        if self._apps_api is not None:
            return
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self._api_client = client.ApiClient()
        self._apps_api = client.AppsV1Api(self._api_client)
        self._core_api = client.CoreV1Api(self._api_client)
        logger.info(f"KubernetesDisruptionLibrary initialized for namespace: {self._namespace}")

    # ========== Kubernetes Pod Operations ==========

    def scale_deployment(self, deployment_name, replicas, namespace=None):
        """Scale a deployment to specified number of replicas."""
        self._ensure_k8s()
        ns = namespace or self._namespace
        deployment = self._apps_api.read_namespaced_deployment(deployment_name, ns)
        deployment.spec.replicas = int(replicas)
        self._apps_api.patch_namespaced_deployment(deployment_name, ns, deployment)
        logger.info(f"Scaled deployment {deployment_name} to {replicas} replicas")

    def delete_pods_for_deployment(self, deployment_name, namespace=None, grace_period=0):
        """Force-delete all pods for a deployment (simulates crash)."""
        self._ensure_k8s()
        ns = namespace or self._namespace
        label_selector = f"app={deployment_name}"

        pods = self._core_api.list_namespaced_pod(ns, label_selector=label_selector)
        for pod in pods.items:
            self._core_api.delete_namespaced_pod(
                pod.metadata.name,
                ns,
                grace_period_seconds=grace_period
            )
            logger.info(f"Force-deleted pod {pod.metadata.name}")

    def wait_pods_ready(self, deployment_name, expected_replicas, timeout=300, namespace=None):
        """Wait until deployment has expected ready replicas."""
        self._ensure_k8s()
        ns = namespace or self._namespace
        start_time = time.time()
        expected_replicas = int(expected_replicas)

        while time.time() - start_time < timeout:
            deployment = self._apps_api.read_namespaced_deployment(deployment_name, ns)
            status = deployment.status
            spec_generation = deployment.metadata.generation
            observed_generation = status.observed_generation or 0
            updated_replicas = status.updated_replicas or 0
            ready_replicas = status.ready_replicas or 0

            rollout_seen = observed_generation >= spec_generation
            rollout_complete = (
                rollout_seen
                and updated_replicas == expected_replicas
                and ready_replicas == expected_replicas
            )

            if rollout_complete:
                logger.info(
                    f"Deployment {deployment_name} rollout complete: "
                    f"{ready_replicas}/{expected_replicas} ready, "
                    f"{updated_replicas}/{expected_replicas} updated"
                )
                return True

            logger.debug(
                f"Waiting for {deployment_name} rollout: "
                f"ready={ready_replicas}/{expected_replicas}, "
                f"updated={updated_replicas}/{expected_replicas}, "
                f"observed_generation={observed_generation}/{spec_generation}"
            )
            time.sleep(5)

        asserts.fail(f"Deployment {deployment_name} did not complete rollout to "
                     f"{expected_replicas} replicas within {timeout}s")

    def restart_deployment(self, deployment_name, namespace=None):
        """Trigger rolling restart by patching pod template annotation."""
        self._ensure_k8s()
        ns = namespace or self._namespace
        deployment = self._apps_api.read_namespaced_deployment(deployment_name, ns)

        if deployment.spec.template.metadata.annotations is None:
            deployment.spec.template.metadata.annotations = {}

        deployment.spec.template.metadata.annotations['restartedAt'] = str(time.time())
        self._apps_api.patch_namespaced_deployment(deployment_name, ns, deployment)
        logger.info(f"Triggered rolling restart of {deployment_name}")

    def get_configmap_value(self, configmap_name, key, namespace=None):
        """Return the current string value of a single key in a ConfigMap."""
        self._ensure_k8s()
        ns = namespace or self._namespace
        cm = self._core_api.read_namespaced_config_map(configmap_name, ns)
        data = cm.data or {}

        if key not in data:
            logger.info(f"Key {key} not present in ConfigMap {configmap_name}, treating as empty")
            return ""

        return data[key]

    def upsert_config_section(self, config_text, section, *param_lines):
        """Robot-friendly wrapper around upsert_ini_section."""
        return upsert_ini_section(config_text, section, param_lines)

    def patch_configmap_value(self, configmap_name, key, value, namespace=None):
        """Set a single key in a ConfigMap to the given string value (merge patch)."""
        self._ensure_k8s()
        ns = namespace or self._namespace
        body = {"data": {key: value}}
        self._core_api.patch_namespaced_config_map(configmap_name, ns, body)

    # ========== PostgreSQL Operations ==========

    def _get_pg_connect_kwargs(self):
        """Resolve Postgres DSN from mistral-common-params + mistral-secret."""
        import base64

        self._ensure_k8s()
        ns = self._namespace
        cm = self._core_api.read_namespaced_config_map('mistral-common-params', ns)
        secret = self._core_api.read_namespaced_secret('mistral-secret', ns)

        def _b64(key):
            return base64.b64decode(secret.data[key]).decode()

        host = (cm.data.get('pg-host') or '').removesuffix('.svc')
        return {
            'host': host,
            'port': int(cm.data.get('pg-port') or 5432),
            'dbname': cm.data.get('pg-db-name'),
            'user': _b64('pg-user'),
            'password': _b64('pg-password'),
        }

    def execute_sql(self, sql, *params):
        """Execute a SQL statement against the Mistral Postgres DB.

        Returns rowcount for DML. Use %s placeholders with positional params.
        """
        import psycopg2

        conn_kwargs = self._get_pg_connect_kwargs()
        conn = psycopg2.connect(**conn_kwargs)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params if params else None)
                    rowcount = cur.rowcount
            logger.debug(f"SQL ok rowcount={rowcount}: {sql} params={params}")
            return rowcount
        finally:
            conn.close()

    def mark_execution_running_stale(self, execution_id, age_seconds=120):
        """Set workflow execution to RUNNING with aged updated_at."""
        self.execute_sql(
            "UPDATE workflow_executions_v2 "
            "SET state='RUNNING', "
            "updated_at=(NOW() AT TIME ZONE 'UTC') - (%s * INTERVAL '1 second') "
            "WHERE id=%s",
            int(age_seconds),
            execution_id,
        )

    def mark_task_state_stale(self, task_id, state, age_seconds=120):
        """Set task execution state with aged updated_at."""
        self.execute_sql(
            "UPDATE task_executions_v2 "
            "SET state=%s, "
            "updated_at=(NOW() AT TIME ZONE 'UTC') - (%s * INTERVAL '1 second') "
            "WHERE id=%s",
            state,
            int(age_seconds),
            task_id,
        )

    def delete_workflow_execution_cascade(self, execution_id):
        """Delete a workflow execution and its tasks/actions (expired-subwf case)."""
        self.execute_sql(
            "DELETE FROM action_executions_v2 WHERE task_execution_id IN "
            "(SELECT id FROM task_executions_v2 WHERE workflow_execution_id=%s)",
            execution_id,
        )
        self.execute_sql(
            "DELETE FROM task_executions_v2 WHERE workflow_execution_id=%s",
            execution_id,
        )
        self.execute_sql(
            "DELETE FROM workflow_executions_v2 WHERE id=%s",
            execution_id,
        )

    def delete_actions_for_task(self, task_id):
        """Delete action executions belonging to a task (waiting-join case)."""
        self.execute_sql(
            "DELETE FROM action_executions_v2 WHERE task_execution_id=%s",
            task_id,
        )

    def corrupt_all_recovery_case_states(
        self,
        expired_parent_id,
        expired_child_ex_id,
        expired_task_id,
        stucked_parent_id,
        stucked_task_id,
        waiting_parent_id,
        waiting_task_id,
        age_seconds=120,
    ):
        """Apply manual-test DB corruption for all three recovery scenarios."""
        age = int(age_seconds)
        self.delete_workflow_execution_cascade(expired_child_ex_id)
        self.mark_task_state_stale(expired_task_id, 'RUNNING', age)
        self.mark_execution_running_stale(expired_parent_id, age)

        self.mark_task_state_stale(stucked_task_id, 'RUNNING', age)
        self.mark_execution_running_stale(stucked_parent_id, age)

        self.delete_actions_for_task(waiting_task_id)
        self.mark_task_state_stale(waiting_task_id, 'WAITING', age)
        self.mark_execution_running_stale(waiting_parent_id, age)

    # ========== RabbitMQ Operations ==========

    def get_queue_arguments(self, queue_name):
        """Query RabbitMQ management API for queue arguments."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping queue check")
            return None

        try:
            response = requests.get(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}/"
                f"{self._qpath(queue_name)}",
                auth=self._rabbitmq_auth
            )
            if response.status_code == 200:
                data = response.json()
                args = data.get('arguments', {})
                logger.debug(f"Queue {queue_name} arguments: {args}")
                return args
            _console(f"Queue {queue_name} not found (status={response.status_code})")
            return None
        except Exception as e:
            _console(f"Failed to get queue arguments: {e}")
            return None

    def create_queue_with_arguments(self, queue_name, arguments=None, durable=False, auto_delete=False):
        """Create a queue via RabbitMQ management API with custom arguments."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping queue create")
            return

        def _as_bool(value):
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            return str(value).strip().lower() in ('1', 'true', 'yes')

        body = {
            "durable": _as_bool(durable),
            "auto_delete": _as_bool(auto_delete),
            "arguments": arguments or {}
        }
        try:
            response = requests.put(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}/"
                f"{self._qpath(queue_name)}",
                auth=self._rabbitmq_auth,
                json=body
            )
            if response.status_code in (201, 204):
                logger.debug(
                    f"Created queue {queue_name} durable={body['durable']} "
                    f"arguments={arguments}"
                )
            else:
                logger.debug(
                    f"Failed to create queue: {response.status_code} {response.text}"
                )
        except Exception as e:
            _console(f"Failed to create queue: {e}")

    def get_queue_bindings(self, queue_name):
        """Return bindings for a queue (source exchange + routing_key)."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping bindings get")
            return []

        try:
            response = requests.get(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}/"
                f"{self._qpath(queue_name)}/bindings",
                auth=self._rabbitmq_auth
            )
            if response.status_code != 200:
                _console(
                    f"Failed to get bindings for {queue_name}: "
                    f"{response.status_code} {response.text}"
                )
                return []

            bindings = []
            for b in response.json():
                # Skip the default binding to the queue itself (empty source)
                source = b.get('source') or ''
                if not source:
                    continue
                bindings.append({
                    'source': source,
                    'destination': b.get('destination') or queue_name,
                    'routing_key': b.get('routing_key') or '',
                    'arguments': b.get('arguments') or {},
                    'destination_type': b.get('destination_type') or 'queue',
                })
            return bindings
        except Exception as e:
            logger.debug(f"Failed to get bindings for {queue_name}: {e}")
            return []

    def bind_queue(self, queue_name, exchange, routing_key='', arguments=None):
        """Bind a queue to an exchange (required after management-API create)."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping bind")
            return False

        body = {
            'routing_key': routing_key or '',
            'arguments': arguments or {},
        }
        try:
            response = requests.post(
                f"{self._rabbitmq_url}/api/bindings/{self._rabbitmq_vhost}/"
                f"e/{quote(str(exchange), safe='')}/q/{self._qpath(queue_name)}",
                auth=self._rabbitmq_auth,
                json=body
            )
            if response.status_code in (201, 204):
                logger.debug(
                    f"Bound queue {queue_name} to exchange {exchange} "
                    f"routing_key={routing_key!r}"
                )
                return True
            logger.debug(
                f"Failed to bind {queue_name} to {exchange}: "
                f"{response.status_code} {response.text}"
            )
            return False
        except Exception as e:
            _console(f"Failed to bind {queue_name}: {e}")
            return False

    def restore_queue_bindings(self, queue_name, bindings):
        """Re-apply previously captured bindings to a recreated queue."""
        ok = True
        for b in bindings or []:
            if not self.bind_queue(
                queue_name,
                b.get('source'),
                routing_key=b.get('routing_key') or '',
                arguments=b.get('arguments') or {},
            ):
                ok = False
        return ok

    def _infer_exchange_for_queue(self, queue_name, prefix=None):
        """Guess control exchange from sibling executor queues if needed."""
        candidates = []
        if prefix:
            candidates = [
                q['name'] for q in self.get_executor_work_queues(prefix)
                if q['name'] != queue_name
            ]
        # Also try the server-specific sibling naming pattern
        if prefix and queue_name == prefix:
            candidates.append(f"{prefix}.0.0.0.0")
        for name in candidates:
            for b in self.get_queue_bindings(name):
                if b.get('source'):
                    return b['source']
        return 'openstack'

    def replace_queue_with_custom_args(self, queue_name, arguments, durable=True,
                                       prefix=None):
        """Delete queue and recreate with custom args, restoring exchange bindings.

        Management-API create alone leaves the queue unbound, so engine publishes
        never land. We capture bindings first and re-apply them after recreate.

        Engine run_action casts without server target → routing_key == topic
        (shared queue name), so this queue must stay bound to that key.
        """
        bindings = self.get_queue_bindings(queue_name)
        # If this queue was already recreated unbound earlier, learn exchange
        # from a sibling and synthesize the oslo topic binding.
        if not bindings:
            exchange = self._infer_exchange_for_queue(queue_name, prefix)
            bindings = [{
                'source': exchange,
                'routing_key': queue_name,
                'arguments': {},
            }]
            logger.debug(
                f"No prior bindings for {queue_name}; "
                f"will bind to {exchange} with routing_key={queue_name}"
            )

        self.delete_queue(queue_name)
        self.create_queue_with_arguments(
            queue_name, arguments=arguments, durable=durable, auto_delete=False
        )
        self.restore_queue_bindings(queue_name, bindings)

        restored = self.get_queue_bindings(queue_name)
        if not restored:
            asserts.fail(
                f"Queue {queue_name} has no exchange bindings after recreate; "
                f"engine publishes would be dropped"
            )
        return self.get_queue_arguments(queue_name)

    def get_executor_work_queues(self, prefix):
        """Return non-fanout executor queues (shared topic + server-specific).

        Oslo creates:
          - {topic} shared anycast queue (routing_key=topic; used by run_action)
          - {topic}.{server} server-specific work queue (e.g. *.0.0.0.0)
          - {topic}_fanout_* transient fanout members (ignored here)
        """
        queues = self.list_queues_by_prefix(prefix)
        work = [
            q for q in queues
            if '_fanout_' not in q.get('name', '')
        ]
        #_console(f"Executor work queues (non-fanout) for '{prefix}': {work}")
        return work

    def get_shared_executor_queue_name(self, prefix):
        """Return the shared topic queue name (engine cast target without server).

        Oslo listen() declares queue={topic} with routing_key={topic}.
        ExecutorClient.run_action does not pass server → publishes to this key.
        """
        work = self.get_executor_work_queues(prefix)
        exact = [q for q in work if q.get('name') == prefix]
        if exact:
            #_console(f"Shared executor topic queue: {prefix}")
            return prefix
        asserts.fail(
            f"Shared executor queue '{prefix}' not found among work queues: "
            f"{[q.get('name') for q in work]}"
        )

    def get_primary_executor_queue_name(self, prefix):
        """Prefer shared topic queue (cast target); else server-specific."""
        work = self.get_executor_work_queues(prefix)
        if not work:
            asserts.fail(f"No executor work queues found with prefix '{prefix}'")

        exact = [q for q in work if q.get('name') == prefix]
        if exact:
            _console(f"Primary executor queue (shared topic): {prefix}")
            return prefix

        server_specific = [
            q for q in work
            if q['name'].startswith(prefix + '.')
        ]
        if server_specific:
            server_specific.sort(
                key=lambda q: (
                    0 if (q.get('type') == 'quorum' or q.get('durable')) else 1,
                    q['name'],
                )
            )
            name = server_specific[0]['name']
            _console(f"Primary executor queue (server-specific): {name}")
            return name

        name = work[0]['name']
        _console(f"Primary executor queue (fallback): {name}")
        return name

    def get_work_queue_message_count(self, prefix):
        """Unread message count on non-fanout executor work queues only.

        RabbitMQ management API exposes several counters; for "unread" we check ready-to-deliver and unacknowledged messages.
        """
        work = self.get_executor_work_queues(prefix)
        total = sum(
            (q.get('messages_ready', 0) or 0) + (q.get('messages_unacknowledged', 0) or 0)
            for q in work
        )
        return total

    def work_queue_has_unread_messages(self, prefix):
        """Assert at least one unread message on non-fanout executor work queues."""
        count = self.get_work_queue_message_count(prefix)
        if count <= 0:
            asserts.fail(
                f"Expected unread messages in executor work queues "
                f"with prefix '{prefix}' but found {count}"
            )
        return count

    def wait_executor_consumers(self, prefix, timeout=120):
        """Wait until at least one non-fanout executor queue has a consumer."""
        start = time.time()
        while time.time() - start < timeout:
            work = self.get_executor_work_queues(prefix)
            consumers = sum(q.get('consumers', 0) for q in work)
            if consumers > 0:
                logger.debug(f"Executor consumers ready on work queues: {consumers}")
                return True
            time.sleep(5)
        asserts.fail(
            f"No consumers on executor work queues with prefix '{prefix}' "
            f"within {timeout}s"
        )

    def verify_queue_has_no_custom_arguments(self, queue_name, custom_args):
        """Assert that none of the given custom argument keys are present in the queue."""
        actual_args = self.get_queue_arguments(queue_name)
        if actual_args is None:
            asserts.fail(f"Could not retrieve arguments for queue {queue_name}")

        found = [k for k in custom_args if k in actual_args]
        if found:
            asserts.fail(
                f"Queue {queue_name} still has custom arguments after recreation: {found}"
            )
        logger.debug(
            f"Queue {queue_name} has no custom arguments {custom_args} — as expected"
        )

    def delete_queue(self, queue_name):
        """Delete a queue from RabbitMQ."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping queue delete")
            return

        try:
            response = requests.delete(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}/"
                f"{self._qpath(queue_name)}",
                auth=self._rabbitmq_auth
            )
            if response.status_code == 204:
                logger.debug(f"Deleted queue {queue_name}")
            else:
                _console(f"Failed to delete queue: {response.status_code}")
        except Exception as e:
            _console(f"Failed to delete queue: {e}")

    def verify_queue_exists(self, queue_name, timeout=60):
        """Wait until queue exists (after recreation)."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping queue verify")
            return

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}/"
                    f"{self._qpath(queue_name)}",
                    auth=self._rabbitmq_auth
                )
                if response.status_code == 200:
                    _console(f"Queue {queue_name} verified as existing")
                    return True
            except Exception:
                pass

            time.sleep(3)

        asserts.fail(f"Queue {queue_name} did not appear within {timeout}s")

    def delete_mistral_queues_by_prefix(self, prefix):
        """Delete all queues whose name starts with prefix (operator update path).

        Mirrors operator rabbitmq_helper.delete_existing_queues() for the
        queues matching the given prefix.
        """
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping queue delete")
            return []

        try:
            response = requests.get(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}",
                auth=self._rabbitmq_auth
            )
            if response.status_code != 200:
                _console(
                    f"Failed to list queues for delete: "
                    f"{response.status_code} {response.text}"
                )
                return []

            deleted = []
            for q in response.json():
                name = q.get('name', '')
                if not name.startswith(prefix):
                    continue
                if 'mistral' not in name:
                    continue
                del_resp = requests.delete(
                    f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}/"
                    f"{self._qpath(name)}",
                    auth=self._rabbitmq_auth
                )
                if del_resp.status_code in (204, 404):
                    deleted.append(name)
                    logger.debug(f"Deleted queue {name}")
                else:
                    _console(
                        f"Failed to delete queue {name}: "
                        f"{del_resp.status_code} {del_resp.text}"
                    )
            logger.debug(f"Deleted mistral queues with prefix '{prefix}': {deleted}")
            return deleted
        except Exception as e:
            _console(f"Failed to delete mistral queues by prefix: {e}")
            return []

    def list_queues_by_prefix(self, prefix):
        """Return summary dicts for queues whose name starts with prefix."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping queue list")
            return []

        try:
            response = requests.get(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}",
                auth=self._rabbitmq_auth
            )
            if response.status_code != 200:
                _console(
                    f"Failed to list queues: {response.status_code} {response.text}"
                )
                return []

            result = []
            for q in response.json():
                name = q.get('name', '')
                if not name.startswith(prefix):
                    continue
                result.append({
                    'name': name,
                    'messages': q.get('messages', 0),
                    'messages_ready': q.get('messages_ready', 0),
                    'messages_unacknowledged': q.get('messages_unacknowledged', 0),
                    'consumers': q.get('consumers', 0),
                    'arguments': q.get('arguments', {}),
                    'type': q.get('type') or (q.get('arguments') or {}).get('x-queue-type'),
                    'durable': q.get('durable'),
                })
            #_console(f"Queues with prefix '{prefix}': {result}")
            return result
        except Exception as e:
            _console(f"Failed to list queues by prefix: {e}")
            return []

    def get_queue_message_count_by_prefix(self, prefix):
        """Return total message count across all queues whose name starts with prefix."""
        if not self._rabbitmq_url:
            _console("RabbitMQ URL not configured, skipping message count")
            return 0

        try:
            response = requests.get(
                f"{self._rabbitmq_url}/api/queues/{self._rabbitmq_vhost}",
                auth=self._rabbitmq_auth
            )
            if response.status_code == 200:
                matched = [
                    q for q in response.json()
                    if q.get('name', '').startswith(prefix)
                ]
                total = sum(q.get('messages', 0) for q in matched)
                _console(
                    f"Total messages in queues with prefix '{prefix}': {total}; "
                    f"matched={[q.get('name') for q in matched]}"
                )
                return total
            _console(
                f"Failed to get queue message count: "
                f"{response.status_code} {response.text}"
            )
            return 0
        except Exception as e:
            _console(f"Failed to get queue message count by prefix: {e}")
            return 0

