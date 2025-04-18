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

import datetime
import hashlib
import json
import sys

from oslo_config import cfg
from oslo_log import log as logging
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship

from mistral.db.sqlalchemy import model_base as mb
from mistral.db.sqlalchemy import types as st
from mistral import exceptions as exc
from mistral.services import security
from mistral_lib import utils

# Definition objects.

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _get_hash_function_by(column_name):
    def calc_hash(context):
        val = context.current_parameters[column_name] or {}

        if isinstance(val, dict):
            # If the value is a dictionary we need to make sure to have
            # keys in the same order in a string representation.
            hash_base = json.dumps(sorted(val.items()))
        else:
            hash_base = str(val)

        return hashlib.sha256(hash_base.encode('utf-8')).hexdigest()

    return calc_hash


def validate_long_type_length(cls, field_name, value):
    """Makes sure the value does not exceeds the maximum size."""
    if value:
        # Get the configured limit.
        size_limit_kb = cfg.CONF.engine.execution_field_size_limit_kb

        # If the size is unlimited.
        if size_limit_kb < 0:
            return

        size_kb = int(sys.getsizeof(str(value)) / 1024)

        if size_kb > size_limit_kb:
            msg = (
                "Field size limit exceeded"
                " [class={}, field={}, size={}KB, limit={}KB]"
            ).format(
                cls.__name__,
                field_name,
                size_kb,
                size_limit_kb
            )

            LOG.error(msg)

            raise exc.SizeLimitExceededException(msg)


def validate_name_has_no_spaces(name):
    """Makes sure name does not contain spaces."""
    if name:
        if " " in name:
            msg = (
                "Name '{}' must not contain spaces"
            ).format(name)

            LOG.error(msg)

            raise exc.InvalidModelException(msg)


def register_length_validator(attr_name):
    """Register an event listener on the attribute.

    This event listener will validate the size every
    time a 'set' occurs.
    """
    for cls in utils.iter_subclasses(Execution):
        if hasattr(cls, attr_name):
            event.listen(
                getattr(cls, attr_name),
                'set',
                lambda t, v, o, i: validate_long_type_length(cls, attr_name, v)
            )


def register_name_validator():
    """Register an event listener on the attribute.

    This event listener will validate that name of object does not
    contains spaces every time a 'set' occurs.
    """
    for cls in utils.iter_subclasses(Definition):
        event.listen(
            getattr(cls, "name"),
            'set',
            lambda t, v, o, i: validate_name_has_no_spaces(v)
        )


class Definition(mb.MistralSecureModelBase):
    __abstract__ = True

    id = mb.id_column()
    name = sa.Column(sa.String(255))
    namespace = sa.Column(sa.String(255), nullable=True)
    definition = sa.Column(st.MediumText(), nullable=True)
    spec = sa.Column(st.JsonMediumDictType())
    tags = sa.Column(st.JsonListType())
    is_system = sa.Column(sa.Boolean())


# There's no WorkbookExecution so we safely omit "Definition" in the name.
class Workbook(Definition):
    """Contains info about workbook (including definition in Mistral DSL)."""

    __tablename__ = 'workbooks_v2'
    __table_args__ = (
        sa.UniqueConstraint(
            'name',
            'namespace',
            'project_id'
        ),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
    )


class WorkflowDefinition(Definition):
    """Contains info about workflow (including definition in Mistral DSL)."""

    __tablename__ = 'workflow_definitions_v2'
    checksum = sa.Column(sa.String(32), nullable=True)
    __table_args__ = (
        sa.UniqueConstraint(
            'name',
            'namespace',
            'project_id'
        ),
        sa.Index('%s_is_system' % __tablename__, 'is_system'),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
    )

    workbook_name = sa.Column(sa.String(255))


class ActionDefinition(Definition):
    """Contains info about registered Actions."""

    __tablename__ = 'action_definitions_v2'
    __table_args__ = (
        sa.UniqueConstraint(
            'name',
            'namespace',
            'project_id'),
        sa.Index('%s_is_system' % __tablename__, 'is_system'),
        sa.Index('%s_action_class' % __tablename__, 'action_class'),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
    )

    workbook_name = sa.Column(sa.String(255))

    # Main properties.
    description = sa.Column(sa.Text())
    input = sa.Column(sa.Text())

    # Service properties.
    action_class = sa.Column(sa.String(200))
    attributes = sa.Column(st.JsonDictType())


class CodeSource(mb.MistralSecureModelBase):
    """Contains info about registered CodeSources."""

    __tablename__ = 'code_sources'
    __table_args__ = (
        sa.UniqueConstraint(
            'name',
            'namespace',
            'project_id'
        ),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
    )

    # Main properties.
    id = mb.id_column()
    name = sa.Column(sa.String(255))
    content = sa.Column(sa.Text())
    version = sa.Column(sa.Integer())
    namespace = sa.Column(sa.String(255), nullable=True)
    tags = sa.Column(st.JsonListType())


class MistralMetrics(mb.MistralModelBase):
    """Table for maintenance mode."""

    __tablename__ = 'mistral_metrics'
    __table_args__ = (
        sa.UniqueConstraint('name'),
    )
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String(255), nullable=False)
    value = sa.Column(sa.String(255), nullable=False)


class DynamicActionDefinition(mb.MistralSecureModelBase):
    """Contains info about registered Dynamic Actions."""

    __tablename__ = 'dynamic_action_definitions'
    __table_args__ = (
        sa.UniqueConstraint(
            'name',
            'namespace',
            'project_id'
        ),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
    )

    # Main properties.
    id = mb.id_column()
    name = sa.Column(sa.String(255))
    namespace = sa.Column(sa.String(255), nullable=True)
    class_name = sa.Column(sa.String(255))
    code_source_name = sa.Column(sa.String(255))


DynamicActionDefinition.code_source_id = sa.Column(
    sa.String(36),
    sa.ForeignKey(CodeSource.id, ondelete='CASCADE'),
    nullable=False
)

DynamicActionDefinition.code_source = relationship(
    CodeSource,
    remote_side=CodeSource.id,
    lazy='select'
)


# Execution objects.

class Execution(mb.MistralSecureModelBase):
    __abstract__ = True

    # Common properties.
    id = mb.id_column()
    name = sa.Column(sa.String(255))
    description = sa.Column(sa.String(255), nullable=True)
    workflow_name = sa.Column(sa.String(255))
    workflow_namespace = sa.Column(sa.String(255))
    workflow_id = sa.Column(sa.String(80))
    state = sa.Column(sa.String(20))
    state_info = sa.Column(sa.Text(), nullable=True)
    tags = sa.Column(st.JsonListType())

    # Internal properties which can be used by engine.
    runtime_context = sa.Column(st.JsonLongDictType())


class ActionExecution(Execution):
    """Contains action execution information."""

    __tablename__ = 'action_executions_v2'

    __table_args__ = (
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
        sa.Index('%s_state' % __tablename__, 'state'),
        sa.Index('%s_updated_at' % __tablename__, 'updated_at')
    )

    # Main properties.
    spec = sa.Column(st.JsonMediumDictType())
    accepted = sa.Column(sa.Boolean(), default=False)
    input = sa.Column(st.JsonLongDictType(), nullable=True)
    output = sa.orm.deferred(sa.Column(st.JsonLongDictType(), nullable=True))
    last_heartbeat = sa.Column(
        sa.DateTime,
        default=lambda: utils.utc_now_sec() + datetime.timedelta(
            seconds=CONF.action_heartbeat.first_heartbeat_timeout
        )
    )
    is_sync = sa.Column(sa.Boolean(), default=None, nullable=True)


class WorkflowExecution(Execution):
    """Contains workflow execution information."""

    __tablename__ = 'workflow_executions_v2'

    __table_args__ = (
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
        sa.Index('%s_state' % __tablename__, 'state'),
        sa.Index('%s_updated_at' % __tablename__, 'updated_at'),
    )

    # Main properties.
    spec = sa.orm.deferred(sa.Column(st.JsonMediumDictType()))
    accepted = sa.Column(sa.Boolean(), default=False)
    input = sa.orm.deferred(sa.Column(st.JsonLongDictType(), nullable=True))
    output = sa.orm.deferred(sa.Column(st.JsonLongDictType(), nullable=True))
    params = sa.orm.deferred(sa.Column(st.JsonLongDictType()))

    # Initial workflow context containing workflow variables, environment,
    # openstack security context etc.
    # NOTES:
    #   * Data stored in this structure should not be copied into inbound
    #     contexts of tasks. No need to duplicate it.
    #   * This structure does not contain workflow input.
    context = sa.orm.deferred(sa.Column(st.JsonLongDictType()))


class TaskExecution(Execution):
    """Contains task runtime information."""

    __tablename__ = 'task_executions_v2'

    __table_args__ = (
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
        sa.Index('%s_state' % __tablename__, 'state'),
        sa.Index('%s_updated_at' % __tablename__, 'updated_at'),
        sa.UniqueConstraint('unique_key')
    )

    # Main properties.
    spec = sa.orm.deferred(sa.Column(st.JsonMediumDictType()))
    action_spec = sa.Column(st.JsonLongDictType())
    unique_key = sa.Column(sa.String(255), nullable=True)
    type = sa.Column(sa.String(10))
    started_at = sa.Column(sa.DateTime, nullable=True)
    finished_at = sa.Column(sa.DateTime, nullable=True)

    # Whether the task is fully processed (publishing and calculating commands
    # after it). It allows to simplify workflow controller implementations
    # significantly.
    processed = sa.Column(sa.BOOLEAN, default=False)

    # Set to True if the completion of the task led to starting new
    # tasks.
    # The value of this property should be ignored if the task
    # is not completed.
    has_next_tasks = sa.Column(sa.Boolean, default=False)

    # The names of the next tasks.
    # [(task_name, event)]
    next_tasks = sa.Column(st.JsonListType())

    # Set to True if the task finished with an error and the error
    # is handled (e.g. with 'on-error' clause for direct workflows)
    # so that the error shouldn't bubble up to the workflow level.
    # The value of this property should be ignored if the task
    # is not completed.
    error_handled = sa.Column(sa.Boolean, default=False)

    # Data Flow properties.
    in_context = sa.Column(st.JsonLongDictType())
    published = sa.Column(st.JsonLongDictType())

    @property
    def executions(self):
        return (
            self.action_executions
            if not self.spec.get('workflow')
            else self.workflow_executions
        )

    def to_dict(self):
        d = super(TaskExecution, self).to_dict()

        utils.datetime_to_str_in_dict(d, 'started_at')
        utils.datetime_to_str_in_dict(d, 'finished_at')

        return d


for cls in utils.iter_subclasses(Execution):
    event.listen(
        # Catch and trim Execution.state_info to always fit allocated size.
        # Note that the limit is 65500 which is less than 65535 (2^16 -1).
        # The reason is that utils.cut() is not exactly accurate in case if
        # the value is not a string, but, for example, a dictionary. If we
        # limit it exactly to 65535 then once in a while it may go slightly
        # beyond the allowed maximum size. It may depend on the order of
        # keys in a string representation and other things that are hidden
        # inside utils.cut_dict() method.
        cls.state_info,
        'set',
        lambda t, v, o, i: utils.cut(v, 65500),
        retval=True
    )

# Many-to-one for 'ActionExecution' and 'TaskExecution'.

ActionExecution.task_execution_id = sa.Column(
    sa.String(36),
    sa.ForeignKey(TaskExecution.id, ondelete='CASCADE'),
    nullable=True
)

TaskExecution.action_executions = relationship(
    ActionExecution,
    backref=backref('task_execution', remote_side=[TaskExecution.id]),
    cascade='all, delete-orphan',
    foreign_keys=ActionExecution.task_execution_id,
    lazy='select',
    passive_deletes=True
)

sa.Index(
    '%s_task_execution_id' % ActionExecution.__tablename__,
    'task_execution_id'
)

# Many-to-one for 'WorkflowExecution' and 'TaskExecution'.

WorkflowExecution.task_execution_id = sa.Column(
    sa.String(36),
    sa.ForeignKey(TaskExecution.id, ondelete='CASCADE'),
    nullable=True
)

TaskExecution.workflow_executions = relationship(
    WorkflowExecution,
    backref=backref('task_execution', remote_side=[TaskExecution.id]),
    cascade='all, delete-orphan',
    foreign_keys=WorkflowExecution.task_execution_id,
    lazy='select',
    passive_deletes=True
)

sa.Index(
    '%s_task_execution_id' % WorkflowExecution.__tablename__,
    'task_execution_id'
)

# Many-to-one for 'WorkflowExecution' and 'WorkflowExecution'

WorkflowExecution.root_execution_id = sa.Column(
    sa.String(36),
    sa.ForeignKey(WorkflowExecution.id, ondelete='SET NULL'),
    nullable=True
)

WorkflowExecution.root_execution = relationship(
    WorkflowExecution,
    remote_side=WorkflowExecution.id,
    lazy='select'
)

# Many-to-one for 'TaskExecution' and 'WorkflowExecution'.

TaskExecution.workflow_execution_id = sa.Column(
    sa.String(36),
    sa.ForeignKey(WorkflowExecution.id, ondelete='CASCADE')
)

WorkflowExecution.task_executions = relationship(
    TaskExecution,
    backref=backref('workflow_execution', remote_side=[WorkflowExecution.id]),
    cascade='all, delete-orphan',
    foreign_keys=TaskExecution.workflow_execution_id,
    lazy='select',
    passive_deletes=True
)

sa.Index(
    '%s_workflow_execution_id' % TaskExecution.__tablename__,
    TaskExecution.workflow_execution_id
)

sa.Index(
    '%s_workflow_execution_id_name' % TaskExecution.__tablename__,
    TaskExecution.workflow_execution_id, TaskExecution.name
)


# Other objects.


class DelayedCall(mb.MistralModelBase):
    """Contains info about delayed calls."""

    __tablename__ = 'delayed_calls_v2'

    id = mb.id_column()
    factory_method_path = sa.Column(sa.String(200), nullable=True)
    target_method_name = sa.Column(sa.String(80), nullable=False)
    method_arguments = sa.Column(st.JsonDictType())
    serializers = sa.Column(st.JsonDictType())
    key = sa.Column(sa.String(250), nullable=True)
    auth_context = sa.Column(st.JsonMediumDictType())
    execution_time = sa.Column(sa.DateTime, nullable=False)
    processing = sa.Column(sa.Boolean, default=False, nullable=False)


sa.Index(
    '%s_execution_time' % DelayedCall.__tablename__,
    DelayedCall.execution_time
)


class ScheduledJob(mb.MistralModelBase):
    """Contains info about scheduled jobs."""

    __tablename__ = 'scheduled_jobs_v2'

    id = mb.id_column()

    run_after = sa.Column(sa.Integer)

    # The full name of the factory function that returns/builds a Python
    # (target) object whose method should be called. Optional.
    target_factory_func_name = sa.Column(sa.String(200), nullable=True)

    # May take two different forms:
    # 1. Full path of a target function that should be called. For example,
    #  "mistral.utils.random_sleep".
    # 2. Name of a method to call on a target object, if
    #  "target_factory_func_name" is specified.
    func_name = sa.Column(sa.String(80), nullable=False)

    func_args = sa.Column(st.JsonDictType())
    func_arg_serializers = sa.Column(st.JsonDictType())
    auth_ctx = sa.Column(st.JsonDictType())
    execute_at = sa.Column(sa.DateTime, nullable=False)
    captured_at = sa.Column(sa.DateTime, nullable=True)

    key = sa.Column(sa.String(250), nullable=True)


class Environment(mb.MistralSecureModelBase):
    """Contains environment variables for workflow execution."""

    __tablename__ = 'environments_v2'

    __table_args__ = (
        sa.UniqueConstraint('name', 'project_id'),
        sa.Index('%s_name' % __tablename__, 'name'),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
    )

    # Main properties.
    id = mb.id_column()
    name = sa.Column(sa.String(200))
    description = sa.Column(sa.Text())
    variables = sa.Column(st.JsonLongDictType())


class CronTrigger(mb.MistralSecureModelBase):
    """Contains info about cron triggers."""

    __tablename__ = 'cron_triggers_v2'

    __table_args__ = (
        sa.UniqueConstraint('name', 'project_id'),
        sa.UniqueConstraint(
            'workflow_input_hash', 'workflow_name', 'pattern', 'project_id',
            'workflow_params_hash', 'remaining_executions',
            'first_execution_time'
        ),
        sa.Index(
            '%s_next_execution_time' % __tablename__,
            'next_execution_time'
        ),
        sa.Index('%s_project_id' % __tablename__, 'project_id'),
        sa.Index('%s_scope' % __tablename__, 'scope'),
        sa.Index('%s_workflow_name' % __tablename__, 'workflow_name'),
    )

    id = mb.id_column()
    name = sa.Column(sa.String(200))
    pattern = sa.Column(
        sa.String(100),
        nullable=True,
        default='0 0 30 2 0'  # Set default to 'never'.
    )
    first_execution_time = sa.Column(sa.DateTime, nullable=True)
    next_execution_time = sa.Column(sa.DateTime, nullable=False)
    workflow_name = sa.Column(sa.String(255))
    remaining_executions = sa.Column(sa.Integer)

    workflow_id = sa.Column(
        sa.String(36),
        sa.ForeignKey(WorkflowDefinition.id)
    )
    workflow = relationship('WorkflowDefinition', lazy='joined')

    workflow_params = sa.Column(st.JsonDictType())
    workflow_params_hash = sa.Column(
        sa.CHAR(64),
        default=_get_hash_function_by('workflow_params')
    )
    workflow_input = sa.Column(st.JsonDictType())
    workflow_input_hash = sa.Column(
        sa.CHAR(64),
        default=_get_hash_function_by('workflow_input')
    )

    trust_id = sa.Column(sa.String(80))

    def to_dict(self):
        d = super(CronTrigger, self).to_dict()

        utils.datetime_to_str_in_dict(d, 'first_execution_time')
        utils.datetime_to_str_in_dict(d, 'next_execution_time')

        return d


# Register all hooks related to secure models.
mb.register_secure_model_hooks()

# TODO(rakhmerov): This is a bad solution. It's hard to find in the code,
# configure flexibly etc. Fix it.
# Register an event listener to verify that the size of all the long columns
# affected by the user do not exceed the limit configuration.
for attr_name in ['input', 'output', 'params', 'published']:
    register_length_validator(attr_name)

register_name_validator()


class ResourceMember(mb.MistralModelBase):
    """Contains info about resource members."""

    __tablename__ = 'resource_members_v2'
    __table_args__ = (
        sa.UniqueConstraint(
            'resource_id',
            'resource_type',
            'member_id'
        ),
    )

    id = mb.id_column()
    resource_id = sa.Column(sa.String(80), nullable=False)
    resource_type = sa.Column(
        sa.String(50),
        nullable=False,
        default='workflow'
    )
    project_id = sa.Column(sa.String(80), default=security.get_project_id)
    member_id = sa.Column(sa.String(80), nullable=False)
    status = sa.Column(sa.String(20), nullable=False, default="pending")


class EventTrigger(mb.MistralSecureModelBase):
    """Contains info about event triggers."""

    __tablename__ = 'event_triggers_v2'

    __table_args__ = (
        sa.UniqueConstraint('exchange', 'topic', 'event', 'workflow_id',
                            'project_id'),
        sa.Index('%s_project_id_workflow_id' % __tablename__, 'project_id',
                 'workflow_id'),
    )

    id = mb.id_column()
    name = sa.Column(sa.String(200))

    workflow_id = sa.Column(
        sa.String(36),
        sa.ForeignKey(WorkflowDefinition.id)
    )
    workflow = relationship('WorkflowDefinition', lazy='joined')
    workflow_params = sa.Column(st.JsonDictType())
    workflow_input = sa.Column(st.JsonDictType())

    exchange = sa.Column(sa.String(80), nullable=False)
    topic = sa.Column(sa.String(80), nullable=False)
    event = sa.Column(sa.String(80), nullable=False)

    trust_id = sa.Column(sa.String(80))


class NamedLock(mb.MistralModelBase):
    """Contains info about named locks.

    Usage of named locks is based on properties of READ COMMITTED
    transactions of the most generally used SQL databases such as
    Postgres, MySQL, Oracle etc.

    The locking scenario is as follows:
    1. Transaction A (TX-A) inserts a row with unique 'id' and
        some value that identifies a locked object stored in 'name'.
    2. Transaction B (TX-B) and any subsequent transactions tries
        to insert a row with unique 'id' and the same value of 'name'
        field and it waits till TX-A is completed due to transactional
        properties of READ COMMITTED.
    3. If TX-A then immediately deletes the record and commits then
        TX-B and or one of the subsequent transactions are released
        and its 'insert' is completed.
    4. Then the scenario repeats with step #2 where the role of TX-A
        will be playing a transaction that just did insert.

    Practically, this table should never contain any committed rows.
    All its usage is around the play with transactional storages.
    """

    __tablename__ = 'named_locks'

    sa.UniqueConstraint('name')

    id = mb.id_column()
    name = sa.Column(sa.String(255))


sa.UniqueConstraint(NamedLock.name)
