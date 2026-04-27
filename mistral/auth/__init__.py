# Copyright 2016 - Brocade Communications Systems, Inc.
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

import abc
import json

from oslo_config import cfg
from oslo_log import log as logging
from stevedore import driver

from mistral import exceptions as exc


LOG = logging.getLogger(__name__)

_IMPL_AUTH_HANDLER = None


def load_project_rules():
    """Parse CONF.auth.project_rules from JSON. Returns a list of rule dicts."""
    raw = cfg.CONF.auth.project_rules
    try:
        rules = json.loads(raw)
        if rules:
            LOG.info("Loaded %d auth project rule(s)", len(rules))
        return rules
    except (ValueError, TypeError) as e:
        LOG.warning(
            "Failed to parse auth.project_rules, defaulting to empty: %s", e
        )
        return []


def _match_rule(rule, claims):
    """Return True if all field/value pairs in the rule match the claims.

    Each rule must have a 'field', 'value', and 'project' key.
    - If claims[field] is a list  -> True when value is in the list
    - If claims[field] is a scalar -> True when value equals the scalar
    """
    field = rule.get('field', '')
    value = rule.get('value', '')
    claim_val = claims.get(field)

    if claim_val is None:
        return False

    if isinstance(claim_val, list):
        return value in claim_val

    return str(claim_val) == str(value)


def resolve_project(rules, claims, default):
    """Return the project of the first matching rule, or default if none match.

    When rules is empty the default is returned immediately, preserving each
    handler's existing behaviour.
    """
    for rule in rules:
        if _match_rule(rule, claims):
            project = rule.get('project', default)
            LOG.debug(
                "Project rule matched: field=%r value=%r -> project=%r",
                rule.get('field'), rule.get('value'), project
            )
            return project
    return default


def get_auth_handler():
    auth_type = cfg.CONF.auth_type

    global _IMPL_AUTH_HANDLER

    if not _IMPL_AUTH_HANDLER:
        mgr = driver.DriverManager(
            'mistral.auth',
            auth_type,
            invoke_on_load=True
        )

        _IMPL_AUTH_HANDLER = mgr.driver

    return _IMPL_AUTH_HANDLER


class AuthHandler(object, metaclass=abc.ABCMeta):
    """Abstract base class for an authentication plugin."""

    @abc.abstractmethod
    def authenticate(self, req):
        raise exc.UnauthorizedException()
