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
from stevedore import driver

from mistral import exceptions as exc


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
