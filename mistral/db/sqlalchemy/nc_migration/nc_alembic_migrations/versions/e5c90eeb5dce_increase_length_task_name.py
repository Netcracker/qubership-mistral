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

"""Increase length of task name

Revision ID: e5c90eeb5dce
Revises: 79ceffbdf791
Create Date: 2020-01-24 19:44:15.796299

"""

# revision identifiers, used by Alembic.
revision = 'e5c90eeb5dce'
down_revision = '79ceffbdf791'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.alter_column('task_executions_v2', 'unique_key', type_=sa.String(350))
    op.alter_column('task_executions_v2', 'name', type_=sa.String(350))
    op.alter_column('named_locks', 'name', type_=sa.String(350))
