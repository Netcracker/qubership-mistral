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
import re

from oslo_config import cfg
from oslo_log import log as logging
from stevedore import driver

from mistral import exceptions as exc


LOG = logging.getLogger(__name__)

_IMPL_AUTH_HANDLER = None

TOKEN_HEADER_KEY = 'Authorization'
_AUTH_HEADER_PATTERN = re.compile(r'^\w+\s(.*)$')


def extract_token_from_header(headers):
    header_with_token = headers.get(TOKEN_HEADER_KEY)

    if not header_with_token:
        token = headers.get('X-Auth-Token')

        if token:
            return token

        raise exc.UnauthorizedException(
            message='There is no token in headers(X-Auth-Token,Authorization)'
        )

    header_pattern_match = _AUTH_HEADER_PATTERN.match(header_with_token)

    if header_pattern_match is None:
        raise exc.UnauthorizedException(
            'Does not match pattern ' + _AUTH_HEADER_PATTERN.pattern
        )

    groups = header_pattern_match.groups()

    if len(groups) != 1:
        raise exc.UnauthorizedException(
            'Not found the token in the header. '
            'Authorization header: {}'.format(header_with_token)
        )

    return groups[0]


def get_auth_handler():
    global _IMPL_AUTH_HANDLER

    if not _IMPL_AUTH_HANDLER:
        mgr = driver.DriverManager(
            'mistral.auth',
            cfg.CONF.auth_type,
            invoke_on_load=True
        )
        _IMPL_AUTH_HANDLER = mgr.driver

    return _IMPL_AUTH_HANDLER


class AuthHandler(object, metaclass=abc.ABCMeta):
    """Abstract base class for an authentication plugin."""

    @abc.abstractmethod
    def authenticate(self, req):
        raise exc.UnauthorizedException()


class HybridAuthHandler(AuthHandler):
    """Validates tokens against K8s SA first, keycloak-oidc on failure.

    Used when m2m_auth_mode=hybrid to support a mixed environment where
    both ServiceAccount tokens and Keycloak OIDC tokens may be presented.
    """

    def __init__(self):
        super().__init__()
        from mistral.auth import k8s_sa as _k8s_sa_mod
        from mistral.auth import keycloak as _keycloak_mod
        try:
            self._k8s_handler = _k8s_sa_mod.K8sSAAuthHandler()
        except Exception:
            LOG.warning(
                "K8s SA handler failed to initialize in hybrid mode; "
                "k8s-sa validation will be skipped"
            )
            self._k8s_handler = None
        self._keycloak_handler = _keycloak_mod.KeycloakAuthHandler()

    def authenticate(self, req):
        if self._k8s_handler is not None:
            try:
                return self._k8s_handler.authenticate(req)
            except exc.UnauthorizedException:
                LOG.debug(
                    "K8s SA token validation failed in hybrid mode, "
                    "falling back to keycloak-oidc"
                )
        return self._keycloak_handler.authenticate(req)
