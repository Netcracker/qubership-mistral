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

import os
import tempfile
import time
from unittest import mock

import jwt
from oslo_config import cfg

from mistral import auth
import mistral.services.secure_request as sr
from mistral.tests.unit import base

CONF = cfg.CONF

_FAKE_TOKEN = {
    'access_token': 'test-token',
    'token_type': 'Bearer',
    'expires_in': 3600,
}


class RefreshDispatchTest(base.BaseTest):
    """Tests that __refresh() picks the right auth helper based on auth_type."""

    def setUp(self):
        super().setUp()
        # Force token to be considered expired so __refresh() is always called.
        sr.TOKEN['expires_at'] = 0
        sr.TOKEN['access_token'] = ''

    def tearDown(self):
        super().tearDown()
        CONF.clear_override('auth_type')

    def _patch_helpers(self, k8s_result=None, keycloak_result=None,
                       mitreid_result=None, k8s_side_effect=None):
        patches = [
            mock.patch(
                'mistral.services.secure_request._auth_using_k8s_sa',
                return_value=k8s_result or _FAKE_TOKEN,
                side_effect=k8s_side_effect
            ),
            mock.patch(
                'mistral.services.secure_request._auth_using_keycloak',
                return_value=keycloak_result or _FAKE_TOKEN
            ),
            mock.patch(
                'mistral.services.secure_request._auth_using_mitreid',
                return_value=mitreid_result or _FAKE_TOKEN
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return (
            mock.patch(
                'mistral.services.secure_request._auth_using_k8s_sa'
            ).start,
        )

    def test_keycloak_oidc_calls_keycloak(self):
        CONF.set_override('auth_type', 'keycloak-oidc')
        with mock.patch('mistral.services.secure_request._auth_using_keycloak',
                        return_value=_FAKE_TOKEN) as mock_kc, \
             mock.patch('mistral.services.secure_request._auth_using_k8s_sa',
                        return_value=_FAKE_TOKEN) as mock_k8s:
            sr.set_auth_token({})

        mock_kc.assert_called_once()
        mock_k8s.assert_not_called()

    def test_k8s_sa_calls_k8s(self):
        CONF.set_override('auth_type', 'k8s-sa')
        with mock.patch('mistral.services.secure_request._auth_using_k8s_sa',
                        return_value=_FAKE_TOKEN) as mock_k8s, \
             mock.patch('mistral.services.secure_request._auth_using_keycloak',
                        return_value=_FAKE_TOKEN) as mock_kc:
            sr.set_auth_token({})

        mock_k8s.assert_called_once()
        mock_kc.assert_not_called()

    def test_hybrid_uses_k8s_when_available(self):
        CONF.set_override('auth_type', 'hybrid')
        with mock.patch('mistral.services.secure_request._auth_using_k8s_sa',
                        return_value=_FAKE_TOKEN) as mock_k8s, \
             mock.patch('mistral.services.secure_request._auth_using_keycloak',
                        return_value=_FAKE_TOKEN) as mock_kc:
            sr.set_auth_token({})

        mock_k8s.assert_called_once()
        mock_kc.assert_not_called()

    def test_hybrid_falls_back_to_keycloak_on_k8s_failure(self):
        CONF.set_override('auth_type', 'hybrid')
        with mock.patch('mistral.services.secure_request._auth_using_k8s_sa',
                        side_effect=Exception('no k8s token')) as mock_k8s, \
             mock.patch('mistral.services.secure_request._auth_using_keycloak',
                        return_value=_FAKE_TOKEN) as mock_kc:
            sr.set_auth_token({})

        mock_k8s.assert_called_once()
        mock_kc.assert_called_once()

    def test_unsupported_auth_type_raises(self):
        CONF.set_override('auth_type', 'unknown-type')
        self.assertRaises(ValueError, sr.set_auth_token, {})


class K8sSaOutboundTokenTest(base.BaseTest):
    """Outbound requests use the projected token of the [k8s_sa] audience."""

    def setUp(self):
        super().setUp()

        self.tokens_dir = tempfile.mkdtemp()
        patcher = mock.patch.object(
            auth, 'K8S_SA_AUDIENCE_TOKENS_DIR', self.tokens_dir
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_token(self, audience, token):
        os.makedirs(os.path.join(self.tokens_dir, audience))

        with open(os.path.join(self.tokens_dir, audience, 'token'), 'w') as f:
            f.write(token + '\n')

    def test_uses_netcracker_audience_token(self):
        exp = int(time.time()) + 600
        token = jwt.encode(
            {'aud': ['netcracker'], 'exp': exp}, 'k', algorithm='HS256'
        )
        self._write_token('netcracker', token)

        # The default SA token must not be used for outbound requests.
        with mock.patch.object(auth, 'K8S_SA_TOKEN_PATH', '/does/not/exist'):
            result = sr._auth_using_k8s_sa()

        self.assertEqual(token, result['access_token'])
        self.assertEqual('Bearer', result['token_type'])
        self.assertTrue(0 < result['expires_in'] <= 600)

    def test_audience_option_selects_the_token(self):
        self._write_token('netcracker', 'default-aud-token')
        self._write_token('other', 'other-aud-token')
        CONF.set_override('audience', 'other', group='k8s_sa')
        self.addCleanup(CONF.clear_override, 'audience', group='k8s_sa')

        self.assertEqual(
            'other-aud-token', sr._auth_using_k8s_sa()['access_token']
        )

    def test_missing_audience_token_raises(self):
        # Lets hybrid mode fall back to keycloak-oidc.
        self.assertRaises(OSError, sr._auth_using_k8s_sa)
