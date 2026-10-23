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

import base64
import json
import os
import shutil
import tempfile
import time
from unittest import mock

from oslo_config import cfg

from mistral import auth
from mistral import exceptions as exc
from mistral.services import secure_request as sr
from mistral.tests.unit import base


def _jwt(exp):
    def b64(d):
        raw = json.dumps(d).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    return '.'.join([b64({'alg': 'RS256'}), b64({'exp': exp}), 'sig'])


class SecureRequestAuthTypeTest(base.BaseTest):
    """Outbound token acquisition per auth type (actions, notifications)."""

    def setUp(self):
        super().setUp()
        self._reset_token()
        self.addCleanup(self._reset_token)

        # Default location, i.e. where the operator mounts the token
        self.default_tokens_dir = auth.K8S_SA_AUDIENCE_TOKENS_DIR

        tokens_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tokens_dir, True)
        self.audience = cfg.CONF.k8s_sa.audience
        self.token_file = os.path.join(tokens_dir, self.audience, 'token')
        os.makedirs(os.path.dirname(self.token_file))
        patcher = mock.patch.object(
            auth, 'K8S_SA_AUDIENCE_TOKENS_DIR', tokens_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _reset_token():
        sr.TOKEN.update(access_token='', token_type='', expires_in='',
                        expires_at='')

    def _write_token(self, token):
        with open(self.token_file, 'w') as f:
            f.write(token + '\n')

    def test_default_token_location_matches_operator_mount(self):
        # operator: MC.K8S_SA_AUDIENCE_TOKENS_DIR/<audience>/token
        self.assertEqual('/var/run/secrets/tokens', self.default_tokens_dir)

        with mock.patch.object(
                auth, 'K8S_SA_AUDIENCE_TOKENS_DIR', self.default_tokens_dir):
            path = sr._get_k8s_sa_audience_token_path()

        # os.path.join uses the platform separator; the pod is always Linux,
        # so compare in POSIX form to keep the test portable.
        self.assertEqual(
            '/var/run/secrets/tokens/%s/token' % self.audience,
            path.replace(os.sep, '/')
        )

    def test_k8s_sa_uses_projected_token_and_never_calls_keycloak(self):
        cfg.CONF.set_default('auth_type', 'k8s-sa')
        token = _jwt(time.time() + 600)
        self._write_token(token)

        with mock.patch.object(sr, '_auth_using_keycloak') as keycloak:
            headers = sr.set_auth_token({'X-Test': '1'})

        keycloak.assert_not_called()
        self.assertEqual('Bearer ' + token, headers['Authorization'])
        self.assertEqual('1', headers['X-Test'])

    def test_k8s_sa_caches_token_until_it_is_about_to_expire(self):
        cfg.CONF.set_default('auth_type', 'k8s-sa')
        first = _jwt(time.time() + 600)
        self._write_token(first)
        sr.set_auth_token({})

        self._write_token(_jwt(time.time() + 1200))
        headers = sr.set_auth_token({})

        self.assertEqual('Bearer ' + first, headers['Authorization'])

    def test_k8s_sa_expiry_is_taken_from_token(self):
        cfg.CONF.set_default('auth_type', 'k8s-sa')
        self._write_token(_jwt(time.time() + 100))

        sr.set_auth_token({})

        self.assertLessEqual(sr.TOKEN['expires_in'], 100)
        self.assertGreater(sr.TOKEN['expires_in'], 90)

    def test_k8s_sa_missing_projected_token_mount_is_unauthorized(self):
        cfg.CONF.set_default('auth_type', 'k8s-sa')

        with mock.patch.object(sr, '_auth_using_keycloak') as keycloak:
            self.assertRaises(exc.UnauthorizedException, sr.set_auth_token, {})

        keycloak.assert_not_called()

    def test_hybrid_prefers_projected_token(self):
        cfg.CONF.set_default('auth_type', 'hybrid')
        token = _jwt(time.time() + 600)
        self._write_token(token)

        with mock.patch.object(sr, '_auth_using_keycloak') as keycloak:
            headers = sr.set_auth_token({})

        keycloak.assert_not_called()
        self.assertEqual('Bearer ' + token, headers['Authorization'])

    def test_hybrid_falls_back_to_keycloak_without_token_file(self):
        cfg.CONF.set_default('auth_type', 'hybrid')

        with mock.patch.object(
                sr, '_auth_using_keycloak',
                return_value={'access_token': 'kc', 'token_type': 'Bearer',
                              'expires_in': 300}) as keycloak:
            headers = sr.set_auth_token({})

        keycloak.assert_called_once()
        self.assertEqual('Bearer kc', headers['Authorization'])

    def test_keycloak_oidc_is_unchanged(self):
        cfg.CONF.set_default('auth_type', 'keycloak-oidc')

        with mock.patch.object(
                sr, '_auth_using_keycloak',
                return_value={'access_token': 'kc', 'token_type': 'Bearer',
                              'expires_in': 300}):
            headers = sr.set_auth_token({})

        self.assertEqual('Bearer kc', headers['Authorization'])

    def test_unknown_auth_type_still_raises(self):
        cfg.CONF.set_default('auth_type', 'keystone')

        self.assertRaises(ValueError, sr.set_auth_token, {})
