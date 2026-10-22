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

import json
import os
import tempfile
import threading
import time
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from jwt.algorithms import RSAAlgorithm
from oslo_config import cfg
import requests_mock

from mistral import auth
from mistral.auth import k8s_sa
from mistral.auth import k8s_token_verifier as verifier
from mistral import exceptions as exc
from mistral.tests.unit import base

CONF = cfg.CONF

ISSUER = 'https://kubernetes.default.svc'
AUDIENCE = 'netcracker'
KUBE_AUDIENCE = 'https://kubernetes.default.svc.cluster.local'
DISCOVERY_URL = ISSUER + '/.well-known/openid-configuration'
JWKS_URL = ISSUER + '/openid/v1/jwks'
SUBJECT = 'system:serviceaccount:team-a:builder'


class _Key(object):
    def __init__(self, kid):
        self.kid = kid
        self.private = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )

    def jwk(self):
        data = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        data.update({'kid': self.kid, 'use': 'sig', 'alg': 'RS256'})

        return data

    def sign(self, claims, alg='RS256', headers=None):
        hdrs = {'kid': self.kid}
        hdrs.update(headers or {})

        return jwt.encode(claims, self.private, algorithm=alg, headers=hdrs)


def _claims(**overrides):
    now = int(time.time())
    claims = {
        'iss': ISSUER,
        'aud': [AUDIENCE],
        'sub': SUBJECT,
        'iat': now,
        'nbf': now,
        'exp': now + 3600,
        'kubernetes.io': {
            'namespace': 'team-a',
            'serviceaccount': {'name': 'builder', 'uid': 'sa-uid'},
            'pod': {'name': 'builder-0', 'uid': 'pod-uid'},
        },
    }
    claims.update(overrides)

    return {k: v for k, v in claims.items() if v is not None}


class _VerifierTestBase(base.BaseTest):
    def setUp(self):
        super(_VerifierTestBase, self).setUp()

        self.key = _Key('key-1')
        self.sleeps = []

        self.mock = requests_mock.Mocker()
        self.mock.start()
        self.addCleanup(self.mock.stop)

        self.mock.get(DISCOVERY_URL, json={'jwks_uri': JWKS_URL})
        self.jwks = self.mock.get(JWKS_URL, json={'keys': [self.key.jwk()]})

    def _verifier(self, **kwargs):
        params = dict(
            issuer=ISSUER,
            audience=[AUDIENCE],
            token_func=lambda: 'own-sa-token',
            sleep=self.sleeps.append,
        )
        params.update(kwargs)

        v = verifier.K8sTokenVerifier(**params)

        self.addCleanup(self._wait_for_refresh_to_finish, v)

        return v

    def _wait_for_refresh_to_finish(self, v, timeout=5):
        if v._refresh_lock.acquire(timeout=timeout):
            v._refresh_lock.release()


class K8sTokenVerifierTest(_VerifierTestBase):
    def test_valid_token(self):
        claims = self._verifier().verify(self.key.sign(_claims()))

        self.assertEqual(SUBJECT, claims['sub'])
        self.assertEqual(
            'builder-0', claims['kubernetes.io']['pod']['name']
        )

    def test_discovery_and_jwks_requests_carry_own_token(self):
        self._verifier().verify(self.key.sign(_claims()))

        for req in self.mock.request_history:
            self.assertEqual(
                'Bearer own-sa-token', req.headers['Authorization']
            )

    def test_requests_accept_jwk_set_media_type(self):
        # The Kubernetes API server answers 406 to a JSON-only Accept header
        # for /openid/v1/jwks.
        self._verifier().verify(self.key.sign(_claims()))

        for req in self.mock.request_history:
            self.assertIn('application/jwk-set+json', req.headers['Accept'])
            self.assertIn('application/json', req.headers['Accept'])

    def test_anonymous_requests_have_no_authorization(self):
        self._verifier(anonymous=True).verify(self.key.sign(_claims()))

        self.assertEqual(2, self.mock.call_count)

        for req in self.mock.request_history:
            self.assertNotIn('Authorization', req.headers)

    def test_explicit_jwks_url_skips_discovery(self):
        self._verifier(jwks_url=JWKS_URL).verify(self.key.sign(_claims()))

        self.assertEqual(
            [JWKS_URL], [r.url for r in self.mock.request_history]
        )

    def test_keys_are_cached(self):
        v = self._verifier()
        token = self.key.sign(_claims())

        v.verify(token)
        v.verify(token)

        self.assertEqual(1, self.jwks.call_count)

    def test_expired_token(self):
        token = self.key.sign(_claims(exp=int(time.time()) - 3600))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_slightly_expired_token_is_within_leeway(self):
        token = self.key.sign(_claims(exp=int(time.time()) - 10))

        self.assertEqual(
            SUBJECT, self._verifier().verify(token)['sub']
        )

    def test_missing_exp(self):
        token = self.key.sign(_claims(exp=None))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_wrong_audience(self):
        token = self.key.sign(_claims(aud=['someone-else']))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_missing_audience(self):
        token = self.key.sign(_claims(aud=None))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_any_of_configured_audiences_is_accepted(self):
        v = self._verifier(audience=['other', AUDIENCE])

        self.assertEqual(SUBJECT, v.verify(self.key.sign(_claims()))['sub'])

    def test_wrong_issuer(self):
        token = self.key.sign(_claims(iss='https://evil.example.com'))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_issued_in_the_future(self):
        now = int(time.time())
        token = self.key.sign(_claims(iat=now + 600, nbf=now, exp=now + 4000))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_missing_iat(self):
        token = self.key.sign(_claims(iat=None))

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_token_signed_with_foreign_key(self):
        foreign = _Key('key-1')  # same kid, different key material

        self.assertRaises(
            verifier.TokenVerificationError,
            self._verifier().verify,
            foreign.sign(_claims())
        )

    def test_hmac_token_is_rejected(self):
        token = jwt.encode(
            _claims(), 'secret', algorithm='HS256', headers={'kid': 'key-1'}
        )

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_alg_none_is_rejected(self):
        token = jwt.encode(
            _claims(), None, algorithm='none', headers={'kid': 'key-1'}
        )

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_token_without_kid(self):
        token = jwt.encode(_claims(), self.key.private, algorithm='RS256')

        self.assertRaises(
            verifier.TokenVerificationError, self._verifier().verify, token
        )

    def test_garbage_token(self):
        self.assertRaises(
            verifier.TokenVerificationError,
            self._verifier().verify,
            'not-a-jwt'
        )

    def test_unknown_kid_refreshes_keys_once(self):
        v = self._verifier()
        v.verify(self.key.sign(_claims()))
        self.assertEqual(1, self.jwks.call_count)

        # Key rotation: a new key appears in the JWKS.
        rotated = _Key('key-2')
        self.jwks = self.mock.get(
            JWKS_URL, json={'keys': [self.key.jwk(), rotated.jwk()]}
        )

        self.assertEqual(
            SUBJECT, v.verify(rotated.sign(_claims()))['sub']
        )
        self.assertEqual(1, self.jwks.call_count)

    def test_unknown_kid_refresh_is_rate_limited(self):
        v = self._verifier()
        v.verify(self.key.sign(_claims()))

        unknown = _Key('unknown')
        before = self.jwks.call_count

        for _i in range(3):
            self.assertRaises(
                verifier.TokenVerificationError,
                v.verify,
                unknown.sign(_claims())
            )

        # Only the first unknown kid may trigger a refresh.
        self.assertEqual(before + 1, self.jwks.call_count)

    def test_stale_keys_are_used_when_refresh_fails(self):
        v = self._verifier(refresh_interval=1, unknown_kid_refresh_interval=1)
        token = self.key.sign(_claims())
        v.verify(token)

        self.jwks = self.mock.get(JWKS_URL, status_code=500)

        with mock.patch.object(
                verifier.time, 'monotonic', return_value=time.monotonic() + 10
        ):
            self.assertEqual(SUBJECT, v.verify(token)['sub'])

    def test_retries_on_5xx_then_succeeds(self):
        self.mock.get(
            DISCOVERY_URL,
            [{'status_code': 503},
             {'status_code': 502},
             {'json': {'jwks_uri': JWKS_URL}}]
        )

        claims = self._verifier().verify(self.key.sign(_claims()))

        self.assertEqual(SUBJECT, claims['sub'])
        self.assertEqual(2, len(self.sleeps))
        # Exponential backoff: ~0.5s, ~1s (jitter +-100ms).
        self.assertAlmostEqual(0.5, self.sleeps[0], delta=0.11)
        self.assertAlmostEqual(1.0, self.sleeps[1], delta=0.11)

    def test_gives_up_after_5_attempts(self):
        self.mock.get(DISCOVERY_URL, status_code=500)

        self.assertRaises(
            verifier.TokenVerificationError,
            self._verifier().verify,
            self.key.sign(_claims())
        )

        discovery_calls = [
            r for r in self.mock.request_history if r.url == DISCOVERY_URL
        ]

        self.assertEqual(5, len(discovery_calls))
        self.assertEqual(4, len(self.sleeps))

    def test_no_retry_on_4xx(self):
        self.mock.get(DISCOVERY_URL, status_code=403)

        self.assertRaises(
            verifier.TokenVerificationError,
            self._verifier().verify,
            self.key.sign(_claims())
        )

        self.assertEqual(1, self.mock.call_count)
        self.assertEqual([], self.sleeps)

    def test_jwks_without_usable_keys(self):
        self.mock.get(JWKS_URL, json={'keys': []})

        self.assertRaises(
            verifier.TokenVerificationError,
            self._verifier().verify,
            self.key.sign(_claims())
        )

    def test_get_provider_url(self):
        self.assertEqual(
            'http://h:8080/.well-known/openid-configuration',
            verifier.get_provider_url('http://h:8080')
        )
        self.assertEqual(
            'http://h:8080/.well-known/openid-configuration',
            verifier.get_provider_url('http://h:8080/')
        )
        # Azure (trailing slash) and AWS (no trailing slash) style issuers.
        self.assertEqual(
            'http://h/a/b/.well-known/openid-configuration',
            verifier.get_provider_url('http://h/a/b/')
        )
        self.assertEqual(
            'http://h/a/b/.well-known/openid-configuration',
            verifier.get_provider_url('http://h/a/b')
        )

    def test_is_gke(self):
        resp = mock.Mock(status_code=200, headers={'Metadata-Flavor': 'Google'})

        with mock.patch.object(verifier.requests, 'get', return_value=resp):
            self.assertTrue(verifier.is_gke())

        resp = mock.Mock(status_code=200, headers={})

        with mock.patch.object(verifier.requests, 'get', return_value=resp):
            self.assertFalse(verifier.is_gke())

        with mock.patch.object(verifier.requests, 'get',
                               side_effect=verifier.requests.ConnectionError):
            self.assertFalse(verifier.is_gke())

    def test_build_ca_bundle(self):
        self.assertIs(True, verifier.build_ca_bundle(None))
        self.assertIs(True, verifier.build_ca_bundle('/does/not/exist'))

        with tempfile.NamedTemporaryFile('w', suffix='.crt',
                                         delete=False) as f:
            f.write('CLUSTER-CA')

        self.addCleanup(os.remove, f.name)

        path = verifier.build_ca_bundle(f.name)

        self.addCleanup(os.remove, path)

        with open(path) as bundle:
            content = bundle.read()

        self.assertTrue(content.endswith('CLUSTER-CA'))
        # The default public CAs are kept, not replaced.
        self.assertIn('BEGIN CERTIFICATE', content)


class K8sTokenVerifierLockingTest(_VerifierTestBase):
    """A slow or failing JWKS refresh must not stall the other requests."""

    TIMEOUT = 5

    def setUp(self):
        super(K8sTokenVerifierLockingTest, self).setUp()

        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads = []
        self.addCleanup(self.release.set)

    def _slow_sleep(self, _seconds):
        # Stands for the retry back-off of a failing refresh.
        self.entered.set()
        self.release.wait(self.TIMEOUT)

    def _slow_jwks(self):
        body = json.dumps({'keys': [self.key.jwk()]})

        def respond(_request, _context):
            self.entered.set()
            self.release.wait(self.TIMEOUT)

            return body

        self.jwks = self.mock.get(JWKS_URL, text=respond)

    def _start(self, func):
        thread = threading.Thread(target=func, daemon=True)
        thread.start()
        self.threads.append(thread)

        return thread

    def _join_all(self):
        for thread in self.threads:
            thread.join(self.TIMEOUT)
            self.assertFalse(thread.is_alive())

    def test_cached_keys_are_read_without_any_lock(self):
        v = self._verifier()
        token = self.key.sign(_claims())
        v.verify(token)
        results = []

        # Both locks are taken, as if a refresh was in progress.
        with v._lock, v._refresh_lock:
            self._start(lambda: results.append(v.verify(token)['sub']))
            self._join_all()

        self.assertEqual([SUBJECT], results)

    def test_stuck_periodic_refresh_does_not_block_requests(self):
        v = self._verifier(
            refresh_interval=1,
            unknown_kid_refresh_interval=1,
            sleep=self._slow_sleep
        )
        token = self.key.sign(_claims())
        v.verify(token)

        # The API server fails now: the refresh sits in its retry back-off.
        self.jwks = self.mock.get(JWKS_URL, status_code=500)

        with mock.patch.object(
                verifier.time, 'monotonic', return_value=time.monotonic() + 10
        ):
            started = time.monotonic()
            claims = [v.verify(token) for _i in range(4)]

            self.assertTrue(self.entered.wait(self.TIMEOUT))

        # Served from the cache straight away, with a single refresh running.
        self.assertLess(time.monotonic() - started, self.TIMEOUT)
        self.assertEqual([SUBJECT] * 4, [c['sub'] for c in claims])
        self.assertEqual(1, self.jwks.call_count)

        self.release.set()
        self._wait_for_refresh_to_finish(v)

    def test_requests_waiting_for_the_first_load_reuse_its_keys(self):
        self._slow_jwks()
        v = self._verifier()
        token = self.key.sign(_claims())
        results = []

        self._start(lambda: results.append(v.verify(token)['sub']))
        self.assertTrue(self.entered.wait(self.TIMEOUT))
        self._start(lambda: results.append(v.verify(token)['sub']))
        time.sleep(0.1)
        self.release.set()
        self._join_all()

        self.assertEqual([SUBJECT, SUBJECT], results)
        self.assertEqual(1, self.jwks.call_count)

    def test_failed_first_load_is_not_retried_by_every_waiting_request(self):
        self.mock.get(DISCOVERY_URL, status_code=500)
        v = self._verifier(sleep=self._slow_sleep)
        token = self.key.sign(_claims())
        errors = []

        def call():
            try:
                v.verify(token)
            except verifier.TokenVerificationError as e:
                errors.append(str(e))

        self._start(call)
        self.assertTrue(self.entered.wait(self.TIMEOUT))
        self._start(call)
        self._start(call)
        time.sleep(0.1)
        self.release.set()
        self._join_all()

        discovery_calls = [
            r for r in self.mock.request_history if r.url == DISCOVERY_URL
        ]

        # One retry sequence (5 attempts) for all three requests.
        self.assertEqual(5, len(discovery_calls))
        self.assertEqual(3, len(errors))
        self.assertEqual(
            2, len([e for e in errors if 'retrying later' in e])
        )

    def test_first_load_is_retried_after_the_retry_interval(self):
        self.mock.get(DISCOVERY_URL, status_code=500)
        v = self._verifier(failed_load_retry_interval=5)
        token = self.key.sign(_claims())

        self.assertRaises(verifier.TokenVerificationError, v.verify, token)
        self.assertRaises(verifier.TokenVerificationError, v.verify, token)

        def discovery():
            return len([
                r for r in self.mock.request_history
                if r.url == DISCOVERY_URL
            ])

        self.assertEqual(5, discovery())

        with mock.patch.object(
                verifier.time, 'monotonic', return_value=time.monotonic() + 10
        ):
            self.assertRaises(verifier.TokenVerificationError, v.verify, token)

        self.assertEqual(10, discovery())

    def test_first_load_recovers_once_the_api_server_is_back(self):
        self.mock.get(DISCOVERY_URL, status_code=500)
        v = self._verifier(failed_load_retry_interval=5)
        token = self.key.sign(_claims())

        self.assertRaises(verifier.TokenVerificationError, v.verify, token)

        self.mock.get(DISCOVERY_URL, json={'jwks_uri': JWKS_URL})

        with mock.patch.object(
                verifier.time, 'monotonic', return_value=time.monotonic() + 10
        ):
            self.assertEqual(SUBJECT, v.verify(token)['sub'])

    def test_unknown_kid_uses_the_keys_of_a_running_refresh(self):
        v = self._verifier(
            refresh_interval=1, unknown_kid_refresh_interval=1
        )
        v.verify(self.key.sign(_claims()))
        rotated = _Key('key-2')

        # The periodic refresh loads the rotated key slowly ...
        body = json.dumps({'keys': [self.key.jwk(), rotated.jwk()]})

        def respond(_request, _context):
            self.entered.set()
            self.release.wait(self.TIMEOUT)

            return body

        self.jwks = self.mock.get(JWKS_URL, text=respond)

        with mock.patch.object(
                verifier.time, 'monotonic', return_value=time.monotonic() + 10
        ):
            v.verify(self.key.sign(_claims()))
            self.assertTrue(self.entered.wait(self.TIMEOUT))

            # ... and a request with the new key waits for it instead of
            # fetching the JWKS a second time.
            results = []
            self._start(
                lambda: results.append(v.verify(rotated.sign(_claims())))
            )
            time.sleep(0.1)
            self.release.set()
            self._join_all()

        self.assertEqual(1, len(results))
        self.assertEqual(1, self.jwks.call_count)


class K8sSAAuthHandlerTest(_VerifierTestBase):
    def setUp(self):
        super(K8sSAAuthHandlerTest, self).setUp()

        # The pod's default SA token has the cluster's default audience.
        own = self.key.sign(_claims(
            sub='system:serviceaccount:mistral:default',
            aud=[KUBE_AUDIENCE]
        ))
        fd, self.token_path = tempfile.mkstemp()

        with os.fdopen(fd, 'w') as f:
            f.write(own + '\n')

        self.addCleanup(os.remove, self.token_path)

        self._patch_auth('K8S_SA_TOKEN_PATH', self.token_path)
        self._patch_auth('K8S_SA_CA_PATH', '/does/not/exist')
        patcher = mock.patch.object(verifier, 'is_gke', return_value=False)
        self.is_gke = patcher.start()
        self.addCleanup(patcher.stop)
        CONF.set_override('default_project_id', 'default-project')

        self.addCleanup(CONF.clear_override, 'default_project_id')

    def _patch_auth(self, name, value):
        patcher = mock.patch.object(auth, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _request(self, token):
        req = mock.Mock()
        req.headers = {'Authorization': 'Bearer ' + token}

        return req

    def test_authenticate_sets_identity_headers(self):
        handler = k8s_sa.K8sSAAuthHandler()
        req = self._request(self.key.sign(_claims()))

        with mock.patch(
                'mistral.auth.project_rules.resolve_project_id_from_config',
                return_value='proj-a'
        ) as resolve:
            handler.authenticate(req)

        self.assertEqual('Confirmed', req.headers['X-Identity-Status'])
        self.assertEqual('proj-a', req.headers['X-Project-Id'])
        self.assertEqual('builder', req.headers['X-User-Id'])

        claims = resolve.call_args[0][0]

        self.assertEqual('team-a', claims['namespace'])
        self.assertEqual('builder', claims['service_account'])
        self.assertEqual(SUBJECT, claims['username'])
        self.assertIn('system:serviceaccounts:team-a', claims['groups'])
        self.assertEqual(['builder-0'], claims['pod-name'])
        self.assertEqual(
            ['builder-0'], claims['authentication.kubernetes.io/pod-name']
        )

    def test_default_project_id_when_no_rule_matches(self):
        handler = k8s_sa.K8sSAAuthHandler()
        req = self._request(self.key.sign(_claims()))

        with mock.patch(
                'mistral.auth.project_rules.resolve_project_id_from_config',
                return_value=None
        ):
            handler.authenticate(req)

        self.assertEqual('default-project', req.headers['X-Project-Id'])

    def test_issuer_from_own_token_and_audience_is_netcracker(self):
        handler = k8s_sa.K8sSAAuthHandler()

        self.assertEqual(ISSUER, handler._verifier._issuer)
        # NOT the audience of the pod's own default token.
        self.assertEqual(['netcracker'], handler._verifier._audience)

    def test_default_cluster_audience_is_rejected(self):
        handler = k8s_sa.K8sSAAuthHandler()
        req = self._request(self.key.sign(_claims(aud=[KUBE_AUDIENCE])))

        self.assertRaises(
            exc.UnauthorizedException, handler.authenticate, req
        )
        self.assertNotIn('X-Identity-Status', req.headers)

    def test_netcracker_among_several_audiences_is_accepted(self):
        handler = k8s_sa.K8sSAAuthHandler()
        req = self._request(
            self.key.sign(_claims(aud=['other', 'netcracker']))
        )

        with mock.patch(
                'mistral.auth.project_rules.resolve_project_id_from_config',
                return_value='p'
        ):
            handler.authenticate(req)

        self.assertEqual('Confirmed', req.headers['X-Identity-Status'])

    def test_audience_can_be_overridden(self):
        CONF.set_override('audience', 'a1', group='k8s_sa')
        self.addCleanup(CONF.clear_override, 'audience', group='k8s_sa')

        handler = k8s_sa.K8sSAAuthHandler()

        self.assertEqual(['a1'], handler._verifier._audience)

    def test_invalid_token_is_unauthorized_without_details(self):
        handler = k8s_sa.K8sSAAuthHandler()
        req = self._request(self.key.sign(_claims(aud=['nope'])))

        e = self.assertRaises(
            exc.UnauthorizedException, handler.authenticate, req
        )

        self.assertIn('Invalid K8s SA token', str(e))
        self.assertNotIn('X-Identity-Status', req.headers)

    def test_unreachable_jwks_is_unauthorized(self):
        self.mock.get(DISCOVERY_URL, status_code=500)
        handler = k8s_sa.K8sSAAuthHandler()
        handler._verifier._sleep = lambda _s: None

        self.assertRaises(
            exc.UnauthorizedException,
            handler.authenticate,
            self._request(self.key.sign(_claims()))
        )

    def test_subject_must_be_a_service_account(self):
        handler = k8s_sa.K8sSAAuthHandler()

        for sub in ('system:node:worker-1', 'system:serviceaccount:ns',
                    'system:serviceaccount:ns:sa:extra', 'alice', None):
            req = self._request(self.key.sign(_claims(sub=sub)))

            self.assertRaises(
                exc.UnauthorizedException, handler.authenticate, req
            )

    def test_anonymous_is_detected(self):
        for on_gke in (True, False):
            self.is_gke.return_value = on_gke

            with mock.patch.object(verifier, 'K8sTokenVerifier') as v:
                k8s_sa.K8sSAAuthHandler()

            self.assertIs(on_gke, v.call_args[1]['anonymous'])

    def test_init_fails_with_empty_audience(self):
        CONF.set_override('audience', '', group='k8s_sa')
        self.addCleanup(CONF.clear_override, 'audience', group='k8s_sa')

        self.assertRaises(exc.MistralException, k8s_sa.K8sSAAuthHandler)

    def test_init_fails_without_own_token(self):
        self._patch_auth('K8S_SA_TOKEN_PATH', '/does/not/exist')

        self.assertRaises(exc.MistralException, k8s_sa.K8sSAAuthHandler)
