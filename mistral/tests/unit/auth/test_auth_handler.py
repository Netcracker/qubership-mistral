# Copyright 2026 - NetCracker Technology Corp.
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

from unittest import mock

from oslo_config import cfg

import mistral.auth as auth_module
from mistral import exceptions as exc
from mistral.tests.unit import base

CONF = cfg.CONF


class GetAuthHandlerTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        auth_module._IMPL_AUTH_HANDLER = None

    def tearDown(self):
        super().tearDown()
        auth_module._IMPL_AUTH_HANDLER = None
        CONF.clear_override('auth_type')

    def test_loads_handler_via_stevedore(self):
        mock_handler = mock.Mock()
        mock_mgr = mock.Mock()
        mock_mgr.driver = mock_handler

        CONF.set_override('auth_type', 'keycloak-oidc')
        with mock.patch(
            'mistral.auth.driver.DriverManager', return_value=mock_mgr
        ) as mock_dm:
            result = auth_module.get_auth_handler()

        mock_dm.assert_called_once_with(
            'mistral.auth', 'keycloak-oidc', invoke_on_load=True
        )
        self.assertIs(mock_handler, result)

    def test_handler_is_cached(self):
        mock_handler = mock.Mock()
        mock_mgr = mock.Mock()
        mock_mgr.driver = mock_handler

        CONF.set_override('auth_type', 'k8s-sa')
        with mock.patch(
            'mistral.auth.driver.DriverManager', return_value=mock_mgr
        ) as mock_dm:
            r1 = auth_module.get_auth_handler()
            r2 = auth_module.get_auth_handler()

        mock_dm.assert_called_once()
        self.assertIs(r1, r2)

    def test_hybrid_loads_hybrid_handler(self):
        CONF.set_override('auth_type', 'hybrid')
        with mock.patch('mistral.auth.k8s_sa.K8sSAAuthHandler'), \
             mock.patch('mistral.auth.keycloak.KeycloakAuthHandler'):
            hybrid_instance = auth_module.HybridAuthHandler()
        mock_mgr = mock.Mock()
        mock_mgr.driver = hybrid_instance
        with mock.patch(
            'mistral.auth.driver.DriverManager', return_value=mock_mgr
        ) as mock_dm:
            handler = auth_module.get_auth_handler()
        mock_dm.assert_called_once_with(
            'mistral.auth', 'hybrid', invoke_on_load=True
        )
        self.assertIsInstance(handler, auth_module.HybridAuthHandler)


class HybridAuthHandlerTest(base.BaseTest):
    def _make_handler(self, k8s_init_ok=True):
        mock_k8s = mock.Mock()
        mock_kc = mock.Mock()
        k8s_side_effect = None if k8s_init_ok else Exception('no k8s')
        with mock.patch(
            'mistral.auth.k8s_sa.K8sSAAuthHandler',
            return_value=mock_k8s,
            side_effect=k8s_side_effect
        ), mock.patch(
            'mistral.auth.keycloak.KeycloakAuthHandler',
            return_value=mock_kc
        ):
            handler = auth_module.HybridAuthHandler()
        return handler, mock_k8s, mock_kc

    def test_uses_k8s_when_it_succeeds(self):
        handler, mock_k8s, mock_kc = self._make_handler()
        req = mock.Mock()

        handler.authenticate(req)

        mock_k8s.authenticate.assert_called_once_with(req)
        mock_kc.authenticate.assert_not_called()

    def test_falls_back_to_keycloak_on_k8s_unauthorized(self):
        handler, mock_k8s, mock_kc = self._make_handler()
        mock_k8s.authenticate.side_effect = exc.UnauthorizedException()
        req = mock.Mock()

        handler.authenticate(req)

        mock_k8s.authenticate.assert_called_once_with(req)
        mock_kc.authenticate.assert_called_once_with(req)

    def test_skips_k8s_when_init_fails_uses_keycloak(self):
        handler, _k8s, mock_kc = self._make_handler(k8s_init_ok=False)
        self.assertIsNone(handler._k8s_handler)

        req = mock.Mock()
        handler.authenticate(req)

        mock_kc.authenticate.assert_called_once_with(req)
