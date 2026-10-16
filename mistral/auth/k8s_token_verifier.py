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

"""Verification of Kubernetes ServiceAccount JWTs using JWKS.

The verifier:

1. discovers the JWKS URL from ``<issuer>/.well-known/openid-configuration``;
2. downloads and caches the public signing keys (JWKS);
3. verifies the signature, ``exp``, ``iss``, ``aud`` and ``iat`` locally.

* JWKS is refreshed every ``refresh_interval`` seconds (default 24h);
* an unknown ``kid`` triggers a refresh, rate limited to one per
  ``unknown_kid_refresh_interval`` seconds (default 5 minutes);
* OIDC/JWKS HTTP calls carry the pod's own SA token as a Bearer token
  (unless ``anonymous`` is set, which GKE requires) and are retried up to
  5 times with exponential backoff (500ms .. 15s) plus jitter on network
  errors and 5xx responses;
* ``exp`` is required, ``leeway`` is 30 seconds, and a token whose ``iat``
  lies in the future (beyond the leeway) is rejected.
"""

import os
import random
import tempfile
import threading
import time
from urllib import parse

import certifi
import jwt
from oslo_log import log as logging
import requests


LOG = logging.getLogger(__name__)

WELL_KNOWN_PATH = '/.well-known/openid-configuration'

# Only standard asymmetric algorithms are accepted.
ALLOWED_ALGORITHMS = ('RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512')

LEEWAY_SEC = 30

DEFAULT_REFRESH_INTERVAL = 24 * 60 * 60
DEFAULT_UNKNOWN_KID_REFRESH_INTERVAL = 5 * 60

RETRY_MAX_ATTEMPTS = 5
RETRY_INITIAL_DELAY = 0.5
RETRY_MAX_DELAY = 15.0
RETRY_JITTER = 0.1

HTTP_TIMEOUT = 10

# The Kubernetes API server serves /openid/v1/jwks only as
# application/jwk-set+json and answers HTTP 406 to 'Accept: application/json'.
ACCEPT = 'application/jwk-set+json, application/json'
GKE_PROBE_TIMEOUT = 5


class TokenVerificationError(Exception):
    """The token is invalid, or it could not be verified.
    """


class _RetryableError(Exception):
    pass


def get_provider_url(issuer):
    """Handles issuers with and without a trailing slash, as well as issuers
    with a path (AKS / EKS style).
    """
    parts = parse.urlsplit(issuer)
    path = parts.path.rstrip('/') + WELL_KNOWN_PATH

    return parse.urlunsplit(parts._replace(path=path))


def read_token_file(path):
    try:
        with open(path, 'r') as f:
            token = f.read().strip()
    except OSError as e:
        raise TokenVerificationError(
            "Failed to read ServiceAccount token from %s: %s" % (path, e)
        )

    if not token:
        raise TokenVerificationError(
            "ServiceAccount token file %s is empty" % path
        )

    return token


def decode_unverified(token):
    """Returns the claims of the token WITHOUT verifying anything.

    Only used for reading Mistral's own, locally mounted token (to learn the
    trusted issuer / audience).
    """
    try:
        return jwt.decode(
            token,
            options={
                'verify_signature': False,
                'verify_exp': False,
                'verify_aud': False,
            },
            algorithms=list(ALLOWED_ALGORITHMS)
        )
    except jwt.InvalidTokenError as e:
        raise TokenVerificationError("Invalid JWT: %s" % e)


def is_gke(timeout=GKE_PROBE_TIMEOUT):
    """Tells whether the pod runs on GKE, using the GCE metadata server.
    """
    try:
        resp = requests.get(
            'http://169.254.169.254/computeMetadata/v1/',
            headers={'Metadata-Flavor': 'Google'},
            timeout=timeout
        )
    except requests.RequestException:
        return False

    return (resp.status_code == 200 and
            resp.headers.get('Metadata-Flavor') == 'Google')


def build_ca_bundle(ca_file):
    """Returns a ``verify`` value for ``requests``.

    The cluster CA is *added* to the default (certifi) bundle rather than
    replacing it, because on EKS / AKS the issuer is a public HTTPS endpoint,
    while on a plain cluster it is the API server signed by the cluster CA.
    """
    if not ca_file or not os.path.isfile(ca_file):
        return True

    try:
        with open(certifi.where(), 'rb') as f:
            bundle = f.read()

        with open(ca_file, 'rb') as f:
            cluster_ca = f.read()

        fd, path = tempfile.mkstemp(prefix='mistral-k8s-ca-', suffix='.pem')

        with os.fdopen(fd, 'wb') as out:
            out.write(bundle)
            out.write(b'\n')
            out.write(cluster_ca)

        return path
    except OSError as e:
        LOG.warning(
            "Could not build CA bundle with %s, using cluster CA only: %s",
            ca_file, e
        )

        return ca_file


class K8sTokenVerifier(object):
    """Verifies Kubernetes ServiceAccount tokens against the issuer's JWKS."""

    def __init__(self, issuer, audience, token_func, jwks_url=None,
                 verify=True, anonymous=False,
                 refresh_interval=DEFAULT_REFRESH_INTERVAL,
                 unknown_kid_refresh_interval=(
                     DEFAULT_UNKNOWN_KID_REFRESH_INTERVAL),
                 session=None, sleep=time.sleep):
        """
        :param issuer: Trusted ``iss`` value.
        :param audience: Expected audience(s): a string or a list of
            strings. The token must contain at least one of them.
        :param token_func: Callable returning the pod's current SA token,
            used to authenticate OIDC discovery / JWKS requests.
        :param jwks_url: Optional JWKS URL, skips OIDC discovery.
        :param verify: ``verify`` argument for ``requests``.
        :param anonymous: Do not send the SA token (required on GKE).
        """
        if not issuer:
            raise ValueError("issuer must not be empty")

        if not audience:
            raise ValueError("audience must not be empty")

        self._issuer = issuer
        self._audience = audience
        self._token_func = token_func
        self._jwks_url = jwks_url
        self._anonymous = anonymous
        self._refresh_interval = refresh_interval
        self._unknown_kid_refresh_interval = unknown_kid_refresh_interval
        self._sleep = sleep

        self._session = session or requests.Session()
        self._session.verify = verify

        self._lock = threading.Lock()
        self._keys = None
        self._loaded_at = 0.0
        self._last_periodic_attempt = float('-inf')
        self._last_unknown_kid_refresh = float('-inf')

    def verify(self, raw_token):
        try:
            header = jwt.get_unverified_header(raw_token)
        except jwt.InvalidTokenError as e:
            raise TokenVerificationError("Malformed token: %s" % e)

        alg = header.get('alg')

        if alg not in ALLOWED_ALGORITHMS:
            raise TokenVerificationError(
                "Unsupported token algorithm: %r" % alg
            )

        kid = header.get('kid')

        if not kid:
            raise TokenVerificationError("Token header has no 'kid'")

        key = self._get_signing_key(kid)

        try:
            claims = jwt.decode(
                raw_token,
                key=key,
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                leeway=LEEWAY_SEC,
                options={'require': ['exp', 'iat', 'iss', 'aud']}
            )
        except jwt.InvalidTokenError as e:
            raise TokenVerificationError(
                "Token validation failed: %s: %s" % (type(e).__name__, e)
            )

        self._validate_issued_at(claims)

        return claims

    @staticmethod
    def _validate_issued_at(claims):
        issued_at = claims['iat']

        if isinstance(issued_at, bool) or not isinstance(
                issued_at, (int, float)):
            raise TokenVerificationError("Claim 'iat' is not a number")

        if time.time() < issued_at - LEEWAY_SEC:
            raise TokenVerificationError(
                "Token is used before issued: 'iat' is more than %d sec "
                "in the future" % LEEWAY_SEC
            )

    def _get_signing_key(self, kid):
        with self._lock:
            now = time.monotonic()

            if self._keys is None:
                self._refresh_keys()
            elif (now - self._loaded_at >= self._refresh_interval and
                  now - self._last_periodic_attempt >=
                  self._unknown_kid_refresh_interval):
                self._last_periodic_attempt = now

                try:
                    self._refresh_keys()
                except TokenVerificationError as e:
                    LOG.warning(
                        "JWKS refresh failed, using cached keys: %s", e
                    )

            key = self._keys.get(kid)

            if key is None and (
                    now - self._last_unknown_kid_refresh >=
                    self._unknown_kid_refresh_interval):
                LOG.info("Unknown key id '%s', refreshing JWKS", kid)

                self._last_unknown_kid_refresh = now
                self._refresh_keys()
                key = self._keys.get(kid)

        if key is None:
            raise TokenVerificationError("No signing key with kid '%s'" % kid)

        return key

    def _refresh_keys(self):
        jwks_url = self._jwks_url or self._discover_jwks_url()
        data = self._get_json(jwks_url)

        keys = {}

        for jwk in (data.get('keys') or []) if isinstance(data, dict) else []:
            if not isinstance(jwk, dict) or not jwk.get('kid'):
                continue

            if jwk.get('use', 'sig') != 'sig':
                continue

            try:
                keys[jwk['kid']] = jwt.PyJWK(jwk).key
            except Exception as e:
                LOG.warning(
                    "Skipping unsupported JWK kid=%s: %s", jwk['kid'], e
                )

        if not keys:
            raise TokenVerificationError(
                "No usable signing keys in JWKS from %s" % jwks_url
            )

        self._keys = keys
        self._loaded_at = time.monotonic()

        LOG.debug("Loaded %d signing key(s) from %s", len(keys), jwks_url)

    def _discover_jwks_url(self):
        provider_url = get_provider_url(self._issuer)
        provider = self._get_json(provider_url)
        jwks_uri = provider.get('jwks_uri') if isinstance(
            provider, dict) else None

        if not jwks_uri:
            raise TokenVerificationError(
                "OIDC discovery document at %s has no 'jwks_uri'"
                % provider_url
            )

        # Cache it: the JWKS location does not change between refreshes.
        self._jwks_url = jwks_uri

        return jwks_uri

    def _get_json(self, url):
        delay = RETRY_INITIAL_DELAY

        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                return self._get_json_once(url)
            except _RetryableError as e:
                if attempt == RETRY_MAX_ATTEMPTS:
                    raise TokenVerificationError(
                        "GET %s failed after %d attempts: %s"
                        % (url, attempt, e)
                    )

                wait = min(delay, RETRY_MAX_DELAY)
                wait = max(0.0, wait + random.uniform(
                    -RETRY_JITTER, RETRY_JITTER))

                LOG.warning(
                    "GET %s failed (attempt %d/%d): %s; retrying in %.2fs",
                    url, attempt, RETRY_MAX_ATTEMPTS, e, wait
                )

                self._sleep(wait)
                delay *= 2

    def _get_json_once(self, url):
        headers = {'Accept': ACCEPT}

        if not self._anonymous:
            headers['Authorization'] = 'Bearer %s' % self._token_func()

        try:
            resp = self._session.get(
                url, headers=headers, timeout=HTTP_TIMEOUT
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            raise _RetryableError(str(e))
        except requests.RequestException as e:
            raise TokenVerificationError("GET %s failed: %s" % (url, e))

        if resp.status_code >= 500:
            raise _RetryableError("HTTP %d" % resp.status_code)

        if resp.status_code != 200:
            raise TokenVerificationError(
                "GET %s returned HTTP %d" % (url, resp.status_code)
            )

        try:
            return resp.json()
        except ValueError as e:
            raise TokenVerificationError(
                "GET %s returned invalid JSON: %s" % (url, e)
            )
