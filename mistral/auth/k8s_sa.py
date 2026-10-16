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

from oslo_config import cfg
from oslo_log import log as logging

from mistral._i18n import _
from mistral import auth
from mistral.auth import k8s_token_verifier as verifier
from mistral.auth import project_rules as auth_project_rules
from mistral import exceptions as exc


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

_SA_USERNAME_PREFIX = 'system:serviceaccount:'


class K8sSAAuthHandler(auth.AuthHandler):
    """Authenticates requests using Kubernetes ServiceAccount tokens.

    The JWT is verified locally against the public keys (JWKS) published by
    the cluster's OIDC issuer. The issuer is contacted only to discover and
    refresh those keys (at first use, periodically, and when a token is
    signed with an unknown key id), not on every API call.

    Only tokens whose ``aud`` contains ``[k8s_sa] audience`` (``netcracker``
    by default) are accepted. The
    trusted issuer is taken from the pod's default ServiceAccount token and the
    JWKS location is discovered from it.
    """

    def __init__(self):
        super(K8sSAAuthHandler, self).__init__()

        audience = CONF.k8s_sa.audience
        token_path = auth.K8S_SA_TOKEN_PATH

        def own_token():
            return verifier.read_token_file(token_path)

        try:
            own_claims = verifier.decode_unverified(own_token())
        except verifier.TokenVerificationError as e:
            # Fails fast; HybridAuthHandler turns this into "k8s-sa disabled".
            raise exc.MistralException(
                "Cannot initialize K8s SA authentication: %s" % e
            )

        issuer = own_claims.get('iss')

        if not issuer:
            raise exc.MistralException(
                "Cannot initialize K8s SA authentication: "
                "the ServiceAccount token has no 'iss' claim."
            )

        if not audience:
            raise exc.MistralException(
                "Cannot initialize K8s SA authentication: "
                "[k8s_sa] audience must not be empty."
            )

        self._verifier = verifier.K8sTokenVerifier(
            issuer=issuer,
            audience=[audience],
            token_func=own_token,
            verify=verifier.build_ca_bundle(auth.K8S_SA_CA_PATH),
            # GKE's OIDC endpoints must be called anonymously.
            anonymous=verifier.is_gke(),
        )

        LOG.info(
            "K8s SA auth initialized: issuer=%s, audience=%s", issuer, audience
        )

    def authenticate(self, req):
        LOG.info("K8sSAAuthHandler.authenticate() called")
        headers = req.headers
        token = auth.extract_token_from_header(headers)

        try:
            token_claims = self._verifier.verify(token)
        except verifier.TokenVerificationError as e:
            LOG.warning("K8s token authentication failed: %s", e)
            raise exc.UnauthorizedException(message="Invalid K8s SA token")

        namespace, sa_name = self._parse_namespace_and_username(
            token_claims.get('sub')
        )

        claims = self._extract_claims(token_claims, namespace, sa_name)

        project_id = auth_project_rules.resolve_project_id_from_config(claims)

        req.headers["X-Identity-Status"] = "Confirmed"
        req.headers["X-Project-Id"] = project_id or CONF.default_project_id
        req.headers["X-User-Id"] = sa_name

        LOG.debug(
            "Authenticated K8s SA token: namespace=%s, sa=%s, project_id=%s",
            namespace, sa_name, project_id
        )

    def _extract_claims(self, token_claims, namespace, sa_name):
        """Builds the claim set used for project rule evaluation.

        ``token_claims`` are already signature-verified.
        """
        claims = dict(token_claims)

        claims['namespace'] = namespace
        claims['service_account'] = sa_name
        claims['username'] = token_claims['sub']
        claims['groups'] = [
            'system:serviceaccounts',
            'system:serviceaccounts:%s' % namespace,
            'system:authenticated',
        ]

        # Pod binding, from the ``kubernetes.io`` claim of the bound token.
        k8s_claim = token_claims.get('kubernetes.io')
        pod = k8s_claim.get('pod') if isinstance(k8s_claim, dict) else None

        if isinstance(pod, dict):
            for short_key, value in (('pod-name', pod.get('name')),
                                     ('pod-uid', pod.get('uid'))):
                if value:
                    claims['authentication.kubernetes.io/' + short_key] = [
                        value
                    ]
                    claims.setdefault(short_key, [value])

        LOG.debug("Auth claims for rule evaluation: %s", claims)

        return claims

    def _parse_namespace_and_username(self, username):
        """
        Expected format:
        system:serviceaccount:<namespace>:<name>
        """
        parts = username.split(":") if isinstance(username, str) else []

        if (len(parts) != 4 or
                not username.startswith(_SA_USERNAME_PREFIX) or
                not parts[2] or not parts[3]):
            LOG.error("Invalid subject format in K8s token: %s", username)
            raise exc.UnauthorizedException(
                message=_("Invalid service account identity")
            )

        return parts[2], parts[3]
