# Copyright 2014 - Mirantis, Inc.
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

import abc
import inspect
import traceback

from mistral_lib import actions
from oslo_log import log

LOG = log.getLogger(__name__)


class OpenStackAction(actions.Action):
    """OpenStack Action.

    OpenStack Action is the basis of all OpenStack-specific actions,
    which are constructed via OpenStack Action generators.
    """
    _kwargs_for_run = {}
    client_method_name = None
    _service_name = None
    _service_type = None
    _client_class = None

    def __init__(self, **kwargs):
        self._kwargs_for_run = kwargs

    @abc.abstractmethod
    def _create_client(self, context):
        """Creates client required for action operation."""
        return None

    @classmethod
    def _get_client_class(cls):
        return cls._client_class

    @classmethod
    def _get_client_method(cls, client):
        hierarchy_list = cls.client_method_name.split('.')
        attribute = client

        for attr in hierarchy_list:
            attribute = getattr(attribute, attr)

        return attribute

    @classmethod
    def _get_fake_client(cls):
        """Returns python-client instance which initiated via wrong args.

        It is needed for getting client-method args and description for
        saving into DB.
        """
        # Default is simple _get_client_class instance
        return cls._get_client_class()()

    @classmethod
    def get_fake_client_method(cls):
        return cls._get_client_method(cls._get_fake_client())

    def _get_client(self, context):
        """Returns python-client instance via cache or creation

        Gets client instance according to specific OpenStack Service
        (e.g. Nova, Glance, Heat, Keystone etc)

        """
        try:
            client = self._create_client(context)
        except Exception:
            client = self._create_client(context)
        return client

    def get_session_and_auth(self, context):
        """Get keystone session and auth parameters.

        :param context: the action context
        :return: dict that can be used to initialize service clients
        """

        return None

    def get_service_endpoint(self, context):
        """Get OpenStack service endpoint.

        'service_name' and 'service_type' are defined in specific OpenStack
        service action.
        """
        endpoint = None

        return endpoint

    def run(self, context):
        try:
            method = self._get_client_method(self._get_client(context))

            result = method(**self._kwargs_for_run)

            if inspect.isgenerator(result):
                return [v for v in result]

            return result
        except Exception as e:
            # Print the traceback for the last exception so that we can see
            # where the issue comes from.
            LOG.warning(traceback.format_exc())

            raise Exception(
                "%s.%s failed: %s" %
                (self.__class__.__name__, self.client_method_name, str(e))
            )

    def test(self, context):
        method = self._get_client_method(self._create_test_client(context))

        return method(**self._kwargs_for_run)


if __name__ == '__main__':
    pass
