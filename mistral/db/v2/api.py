# Copyright 2015 - Mirantis, Inc.
# Copyright 2015 - StackStorm, Inc.
# Copyright 2020 Nokia Software.
# Modified in 2025 by NetCracker Technology Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import contextlib

from oslo_config import cfg
from oslo_db import api as db_api

_BACKEND_MAPPING = {
    'sqlalchemy': 'mistral.db.v2.sqlalchemy.api',
}

IMPL = db_api.DBAPI('sqlalchemy', backend_mapping=_BACKEND_MAPPING)

CONF = cfg.CONF


def setup_db():
    IMPL.setup_db()


def drop_db():
    IMPL.drop_db()


# Transaction control.


def start_tx():
    IMPL.start_tx()


def commit_tx():
    IMPL.commit_tx()


def rollback_tx():
    IMPL.rollback_tx()


def end_tx():
    IMPL.end_tx()


@contextlib.contextmanager
def transaction(read_only=False):
    with IMPL.transaction(read_only):
        yield


def refresh(model):
    IMPL.refresh(model)


def expire_all():
    IMPL.expire_all()


# Locking.


def acquire_lock(model, id):
    return IMPL.acquire_lock(model, id)


# Workbooks.

def get_workbook(name, namespace, fields=()):
    return IMPL.get_workbook(name, namespace=namespace, fields=fields)


def load_workbook(name, namespace, fields=()):
    """Unlike get_workbook this method is allowed to return None."""
    return IMPL.load_workbook(name, namespace=namespace, fields=fields)


def get_workbooks(limit=None, marker=None, sort_keys=None,
                  sort_dirs=None, fields=None, **kwargs):
    return IMPL.get_workbooks(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        fields=fields,
        **kwargs
    )


def create_workbook(values):
    return IMPL.create_workbook(values)


def update_workbook(name, values):
    return IMPL.update_workbook(name, values)


def create_or_update_workbook(name, values):
    return IMPL.create_or_update_workbook(name, values)


def delete_workbook(name, namespace=None):
    IMPL.delete_workbook(name, namespace)


def delete_workbooks(**kwargs):
    IMPL.delete_workbooks(**kwargs)


# Workflow definitions.

def get_workflow_definition(identifier, namespace='', fields=()):
    return IMPL.get_workflow_definition(
        identifier,
        namespace=namespace,
        fields=fields
    )


def get_workflow_definition_by_id(id, fields=()):
    return IMPL.get_workflow_definition_by_id(id, fields=fields)


def load_workflow_definition(name, namespace='', fields=()):
    """Unlike get_workflow_definition this method is allowed to return None."""
    return IMPL.load_workflow_definition(name, namespace, fields=fields)


def get_workflow_definitions(limit=None, marker=None, sort_keys=None,
                             sort_dirs=None, fields=None, **kwargs):
    return IMPL.get_workflow_definitions(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        fields=fields,
        **kwargs
    )


def get_workflow_definitions_count(**kwargs):
    return IMPL.get_workflow_definitions_count(**kwargs)


def create_workflow_definition(values):
    return IMPL.create_workflow_definition(values)


def update_workflow_definition(identifier, values):
    return IMPL.update_workflow_definition(identifier, values)


def create_or_update_workflow_definition(name, values):
    return IMPL.create_or_update_workflow_definition(name, values)


def delete_workflow_definition(identifier, namespace=''):
    IMPL.delete_workflow_definition(identifier, namespace)


def delete_workflow_definitions(**kwargs):
    IMPL.delete_workflow_definitions(**kwargs)


# Dynamic actions.

def get_dynamic_action_definition(identifier, namespace='', fields=()):
    return IMPL.get_dynamic_action_definition(identifier, fields, namespace)


def load_dynamic_action_definition(identifier, namespace='', fields=()):
    return IMPL.load_dynamic_action_definition(identifier, fields, namespace)


def create_dynamic_action_definition(values):
    return IMPL.create_dynamic_action_definition(values)


def update_dynamic_action_definition(identifier, values, namespace=''):
    return IMPL.update_dynamic_action_definition(identifier, values, namespace)


def get_dynamic_action_definitions(limit=None, marker=None, sort_keys=None,
                                   sort_dirs=None, fields=None, **kwargs):
    return IMPL.get_dynamic_action_definitions(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        fields=fields,
        **kwargs
    )


def delete_dynamic_action_definition(identifier, namespace=''):
    return IMPL.delete_dynamic_action_definition(identifier, namespace)


def delete_dynamic_action_definitions(**kwargs):
    return IMPL.delete_dynamic_action_definitions(**kwargs)


# Code sources.

def get_code_source(identifier, namespace='', fields=()):
    return IMPL.get_code_source(identifier, fields, namespace=namespace)


def load_code_source(identifier, namespace='', fields=()):
    return IMPL.load_code_source(identifier, fields, namespace=namespace)


def create_code_source(values):
    return IMPL.create_code_source(values)


def update_code_source(identifier, values, namespace=''):
    return IMPL.update_code_source(identifier, values, namespace=namespace)


def get_code_sources(limit=None, marker=None, sort_keys=None,
                     sort_dirs=None, fields=None, **kwargs):
    return IMPL.get_code_sources(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        fields=fields,
        **kwargs
    )


def delete_code_source(identifier, namespace=''):
    return IMPL.delete_code_source(identifier, namespace=namespace)


def delete_code_sources(**kwargs):
    return IMPL.delete_code_sources(**kwargs)


# Action definitions.

def get_action_definition_by_id(id, fields=()):
    return IMPL.get_action_definition_by_id(id, fields=fields)


def get_action_definition(name, fields=(), namespace=''):
    return IMPL.get_action_definition(name, fields=fields, namespace=namespace)


def load_action_definition(name, fields=(), namespace=''):
    """Unlike get_action_definition this method is allowed to return None."""
    action_def = IMPL.load_action_definition(
        name,
        fields=fields,
        namespace=namespace
    )

    # If action definition was not found in the workflow namespace,
    # check in the default namespace
    if action_def:
        return action_def

    return IMPL.load_action_definition(name, fields=fields, namespace='')


def get_action_definitions(limit=None, marker=None, sort_keys=None,
                           sort_dirs=None, **kwargs):
    return IMPL.get_action_definitions(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        **kwargs
    )


def create_action_definition(values):
    return IMPL.create_action_definition(values)


def update_action_definition(identifier, values):
    return IMPL.update_action_definition(identifier, values)


def create_or_update_action_definition(name, values):
    return IMPL.create_or_update_action_definition(name, values)


def delete_action_definition(name, namespace=''):
    return IMPL.delete_action_definition(name, namespace=namespace)


def delete_action_definitions(**kwargs):
    return IMPL.delete_action_definitions(**kwargs)


# Action executions.

def get_action_execution(id, fields=(), insecure=False):
    return IMPL.get_action_execution(id, fields=fields, insecure=insecure)


def load_action_execution(name, fields=()):
    """Unlike get_action_execution this method is allowed to return None."""
    return IMPL.load_action_execution(name, fields=fields)


def get_action_executions(**kwargs):
    return IMPL.get_action_executions(**kwargs)


def create_action_execution(values):
    return IMPL.create_action_execution(values)


def update_action_execution(id, values, insecure=False):
    return IMPL.update_action_execution(id, values, insecure)


def create_or_update_action_execution(id, values):
    return IMPL.create_or_update_action_execution(id, values)


def update_action_execution_heartbeat(id):
    return IMPL.update_action_execution_heartbeat(id)


def delete_action_execution(id):
    return IMPL.delete_action_execution(id)


def delete_action_executions(**kwargs):
    IMPL.delete_action_executions(**kwargs)


# Workflow executions.

def get_workflow_execution(id, fields=()):
    return IMPL.get_workflow_execution(id, fields=fields)


def load_workflow_execution(name, fields=()):
    """Unlike get_workflow_execution this method is allowed to return None."""
    return IMPL.load_workflow_execution(name, fields=fields)


def get_workflow_executions(limit=None, marker=None, sort_keys=None,
                            sort_dirs=None, **kwargs):
    return IMPL.get_workflow_executions(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        **kwargs
    )


def get_workflow_executions_count(**kwargs):
    return IMPL.get_workflow_executions_count(**kwargs)


def create_workflow_execution(values):
    return IMPL.create_workflow_execution(values)


def update_workflow_execution(id, values):
    return IMPL.update_workflow_execution(id, values)


def create_or_update_workflow_execution(id, values):
    return IMPL.create_or_update_workflow_execution(id, values)


def delete_workflow_execution(id, strict=True):
    return IMPL.delete_workflow_execution(id, strict)


def delete_workflow_executions(**kwargs):
    IMPL.delete_workflow_executions(**kwargs)


def update_workflow_execution_state(**kwargs):
    return IMPL.update_workflow_execution_state(**kwargs)


def update_workflow_executions_read_only_status(**kwargs):
    return IMPL.update_workflow_executions_read_only_status(**kwargs)


def get_tasks_statistics_of_execution(wf_ex_id, current_only):
    return IMPL.get_tasks_statistics_of_execution(wf_ex_id, current_only)

# Tasks executions.


def get_task_execution(id, fields=()):
    return IMPL.get_task_execution(id, fields=fields)


def load_task_execution(id, fields=()):
    """Unlike get_task_execution this method is allowed to return None."""
    return IMPL.load_task_execution(id, fields=fields)


def get_task_executions(limit=None, marker=None, sort_keys=None,
                        sort_dirs=None, **kwargs):
    return IMPL.get_task_executions(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        **kwargs
    )


def get_task_executions_count(**kwargs):
    return IMPL.get_task_executions_count(**kwargs)


def get_task_executions_count_with_filters(**kwargs):
    return IMPL.get_task_executions_count_with_filters(**kwargs)


def get_completed_task_executions(**kwargs):
    return IMPL.get_completed_task_executions(**kwargs)


def get_completed_task_executions_as_batches(**kwargs):
    return IMPL.get_completed_task_executions_as_batches(**kwargs)


def get_incomplete_actions(**kwargs):
    return IMPL.get_incomplete_actions(**kwargs)


def get_incomplete_actions_count(**kwargs):
    return IMPL.get_incomplete_actions_count(**kwargs)


def get_incomplete_task_executions(**kwargs):
    return IMPL.get_incomplete_task_executions(**kwargs)


def get_incomplete_task_executions_count(**kwargs):
    return IMPL.get_incomplete_task_executions_count(**kwargs)


def create_task_execution(values):
    return IMPL.create_task_execution(values)


def update_task_execution(id, values):
    return IMPL.update_task_execution(id, values)


def create_or_update_task_execution(id, values):
    return IMPL.create_or_update_task_execution(id, values)


def delete_task_execution(id):
    return IMPL.delete_task_execution(id)


def delete_task_executions(**kwargs):
    return IMPL.delete_task_executions(**kwargs)


def update_task_execution_state(**kwargs):
    return IMPL.update_task_execution_state(**kwargs)


def get_sub_executions_count(id, workflow, accepted=True,
                             states=(), or_=False):
    return IMPL.get_sub_executions_count(id, workflow, accepted,
                                         states, or_)


def get_sub_executions(id, workflow, accepted=True,
                       states=(), or_=False, limit=None):
    return IMPL.get_sub_executions(id, workflow, accepted,
                                   states, or_, limit)


def get_accepted_executions_indexes(id, workflow, accepted):
    return IMPL.get_accepted_executions_indexes(id, workflow, accepted)


def get_with_items_statistics_of_task(task_ex_id, type):
    return IMPL.get_with_items_statistics_of_task(task_ex_id, type)


# Delayed calls.

def get_delayed_calls_to_start(time, batch_size=None):
    return IMPL.get_delayed_calls_to_start(time, batch_size)


def get_overdue_calls(time):
    return IMPL.get_overdue_calls(time)


def create_delayed_call(values):
    return IMPL.create_delayed_call(values)


def delete_delayed_call(id):
    return IMPL.delete_delayed_call(id)


def update_delayed_call(id, values, query_filter=None):
    return IMPL.update_delayed_call(id, values, query_filter)


def get_delayed_call(id):
    return IMPL.get_delayed_call(id)


def get_delayed_calls(**kwargs):
    return IMPL.get_delayed_calls(**kwargs)


def get_delayed_calls_count(**kwargs):
    return IMPL.get_delayed_calls_count(**kwargs)


def delete_delayed_calls(**kwargs):
    return IMPL.delete_delayed_calls(**kwargs)


# Scheduled jobs.

def get_scheduled_jobs_to_start(time, batch_size=None):
    return IMPL.get_scheduled_jobs_to_start(time, batch_size)


def create_scheduled_job(values):
    return IMPL.create_scheduled_job(values)


def delete_scheduled_job(id):
    return IMPL.delete_scheduled_job(id)


def update_scheduled_job(id, values, query_filter=None):
    return IMPL.update_scheduled_job(id, values, query_filter)


def get_scheduled_job(id):
    return IMPL.get_scheduled_job(id)


def get_scheduled_jobs(**kwargs):
    return IMPL.get_scheduled_jobs(**kwargs)


def delete_scheduled_jobs(**kwargs):
    return IMPL.delete_scheduled_jobs(**kwargs)


def get_scheduled_jobs_count(**kwargs):
    return IMPL.get_scheduled_jobs_count(**kwargs)


# Cron triggers.

def get_cron_trigger(identifier, fields=()):
    return IMPL.get_cron_trigger(identifier, fields=fields)


def get_cron_trigger_by_id(id, fields=()):
    return IMPL.get_cron_trigger_by_id(id, fields=fields)


def load_cron_trigger(identifier, fields=()):
    """Unlike get_cron_trigger this method is allowed to return None."""
    return IMPL.load_cron_trigger(identifier, fields=fields)


def get_cron_triggers(**kwargs):
    return IMPL.get_cron_triggers(**kwargs)


def get_next_cron_triggers(time):
    return IMPL.get_next_cron_triggers(time)


def get_expired_executions(expiration_time, limit=None, columns=()):
    return IMPL.get_expired_executions(
        expiration_time,
        limit,
        columns
    )


def get_running_expired_sync_action_executions(expiration_time,
                                               limit, session=None):
    return IMPL.get_running_expired_sync_action_executions(
        expiration_time,
        limit
    )


def get_superfluous_executions(max_finished_executions, limit=None,
                               columns=()):
    return IMPL.get_superfluous_executions(
        max_finished_executions,
        limit,
        columns
    )


def create_cron_trigger(values):
    return IMPL.create_cron_trigger(values)


def update_cron_trigger(identifier, values, query_filter=None):
    return IMPL.update_cron_trigger(identifier, values,
                                    query_filter=query_filter)


def create_or_update_cron_trigger(identifier, values):
    return IMPL.create_or_update_cron_trigger(identifier, values)


def delete_cron_trigger(identifier):
    return IMPL.delete_cron_trigger(identifier)


def delete_cron_triggers(**kwargs):
    return IMPL.delete_cron_triggers(**kwargs)


# Environments.

def get_environment(name, fields=()):
    return IMPL.get_environment(name, fields=fields)


def load_environment(name, fields=()):
    """Unlike get_environment this method is allowed to return None."""
    return IMPL.load_environment(name, fields=fields)


def get_environments(limit=None, marker=None, sort_keys=None,
                     sort_dirs=None, **kwargs):
    return IMPL.get_environments(
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        **kwargs
    )


def create_environment(values):
    return IMPL.create_environment(values)


def update_environment(name, values):
    return IMPL.update_environment(name, values)


def create_or_update_environment(name, values):
    return IMPL.create_or_update_environment(name, values)


def delete_environment(name):
    IMPL.delete_environment(name)


def delete_environments(**kwargs):
    IMPL.delete_environments(**kwargs)


# Resource members.


def create_resource_member(values):
    return IMPL.create_resource_member(values)


def get_resource_member(resource_id, res_type, member_id):
    return IMPL.get_resource_member(resource_id, res_type, member_id)


def get_resource_members(resource_id, res_type):
    return IMPL.get_resource_members(resource_id, res_type)


def update_resource_member(resource_id, res_type, member_id, values):
    return IMPL.update_resource_member(
        resource_id,
        res_type,
        member_id,
        values
    )


def delete_resource_member(resource_id, res_type, member_id):
    IMPL.delete_resource_member(resource_id, res_type, member_id)


def delete_resource_members(**kwargs):
    IMPL.delete_resource_members(**kwargs)


# Event triggers.

def get_event_trigger(id, insecure=False, fields=()):
    return IMPL.get_event_trigger(id, insecure, fields=fields)


def load_event_trigger(id, insecure=False, fields=()):
    return IMPL.load_event_trigger(id, insecure, fields=fields)


def get_event_triggers(insecure=False, limit=None, marker=None, sort_keys=None,
                       sort_dirs=None, fields=None, **kwargs):
    return IMPL.get_event_triggers(
        insecure=insecure,
        limit=limit,
        marker=marker,
        sort_keys=sort_keys,
        sort_dirs=sort_dirs,
        fields=fields,
        **kwargs
    )


def create_event_trigger(values):
    return IMPL.create_event_trigger(values)


def update_event_trigger(id, values):
    return IMPL.update_event_trigger(id, values)


def delete_event_trigger(id):
    return IMPL.delete_event_trigger(id)


def delete_event_triggers(**kwargs):
    return IMPL.delete_event_triggers(**kwargs)


# Locks.

def create_named_lock(name):
    return IMPL.create_named_lock(name)


def get_named_locks(limit=None, marker=None):
    return IMPL.get_named_locks(limit=limit, marker=marker)


def delete_named_lock(lock_id):
    return IMPL.delete_named_lock(lock_id)


@contextlib.contextmanager
def named_lock(name):
    with IMPL.named_lock(name):
        yield


def get_maintenance_status():
    return IMPL.get_maintenance_status()


def update_maintenance_status(status):
    return IMPL.update_maintenance_status(status)


# Monitoring


def get_action_execution_count_by_state():
    return IMPL.get_action_execution_count_by_state()


def get_task_execution_count_by_state():
    return IMPL.get_task_execution_count_by_state()


def get_workflow_execution_count_by_state():
    return IMPL.get_workflow_execution_count_by_state()


def get_delayed_calls_count_by_target():
    return IMPL.get_delayed_calls_count_by_target()


def get_calls_for_recovery(timeout):
    return IMPL.get_calls_for_recovery(timeout)


def get_expired_idle_task_executions(timeout):
    return IMPL.get_expired_idle_task_executions(timeout)


def delete_named_locks(**kwargs):
    return IMPL.delete_named_locks(**kwargs)


def get_stucked_subwf_tasks(timeout):
    return IMPL.get_stucked_subwf_tasks(timeout)


def get_expired_subwf_tasks(timeout):
    return IMPL.get_expired_subwf_tasks(timeout)


def get_expired_waiting_tasks(timeout):
    return IMPL.get_expired_waiting_tasks(timeout)


def get_task_retries(limit=None):
    return IMPL.get_task_retries(limit=limit)


def get_recent_workflow_executions(limit=None):
    return IMPL.get_recent_workflow_executions(limit=limit)
