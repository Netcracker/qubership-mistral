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

import base64
import json
import re

from oslo_config import cfg
from oslo_log import log as logging

from kubernetes import client, config

from mistral._i18n import _
from mistral import auth
from mistral.auth import project_rules as auth_project_rules
from mistral import exceptions as exc


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

TOKEN_HEADER_KEY = 'Authorization'
AUTH_HEADER_PATTERN = re.compile(r'^\w+\s(.*)$')


def extract_token_from_header(headers):
    header_with_token = headers.get(TOKEN_HEADER_KEY)

    if not header_with_token:
        token = headers.get('X-Auth-Token')

        if token:
            return token

        raise exc.UnauthorizedException(
            message='There is no token in headers(X-Auth-Token,Authorization)'
        )

    header_pattern_match = AUTH_HEADER_PATTERN.match(header_with_token)

    if header_pattern_match is None:
        raise exc.UnauthorizedException(
            'Does not match pattern ' + AUTH_HEADER_PATTERN.pattern
        )

    groups = header_pattern_match.groups()

    if len(groups) != 1:
        raise exc.UnauthorizedException(
            'Not found the token in the header. '
            'Authorization header: {}'.format(header_with_token)
        )

    return groups[0]


class K8sSAAuthHandler(auth.AuthHandler):
    """Authenticates requests using Kubernetes ServiceAccount tokens.

    Instead of validating the JWT itself, this handler delegates
    validation to the Kubernetes API server via the TokenReview API.
    """

    def __init__(self):
        super(K8sSAAuthHandler, self).__init__()

        try:
            config.load_incluster_config()
            LOG.info("Loaded in-cluster Kubernetes config")
        except Exception:
            config.load_kube_config()
            LOG.info("Loaded kubeconfig for Kubernetes")

        self.api = client.AuthenticationV1Api()

    def authenticate(self, req):
        LOG.info("K8sSAAuthHandler.authenticate() called")
        headers = req.headers
        token = extract_token_from_header(headers)

        response = self._review_token(token)

        if not response.status or not response.status.authenticated:
            LOG.warning("K8s token authentication failed")
            raise exc.UnauthorizedException(message="Invalid K8s SA token")

        user = response.status.user
        namespace, sa_name = self._parse_namespce_and_username(user.username)
        roles = self._map_roles(sa_name)

        claims = self._extract_claims(response.status, namespace, sa_name, token)

        project_id = auth_project_rules.resolve_project_id_from_config(claims)

        req.headers["X-Identity-Status"] = "Confirmed"
        req.headers["X-Project-Id"] = project_id or CONF.default_project_id
        req.headers["X-User-Id"] = sa_name
        req.headers["X-Roles"] = ','.join(roles)

        LOG.debug(
            "Authenticated K8s SA token: namespace=%s, sa=%s, "
            "roles=%s, project_id=%s",
            namespace, sa_name, roles, project_id
        )

    def _review_token(self, token):
        try:
            review = client.V1TokenReview(
                spec=client.V1TokenReviewSpec(
                    token=token,
                    audiences=[CONF.k8s_sa.audience],
                )
            )

            return self.api.create_token_review(review)

        except Exception as e:
            LOG.exception("Error calling Kubernetes TokenReview API: %s", str(e))
            raise exc.UnauthorizedException(
                message=_("Failed to validate token with Kubernetes")
            )

    def _extract_claims(self, status, namespace, sa_name, token):
        claims = {}

        # Decode JWT payload without verification -- K8s already validated it.
        try:
            payload_part = token.split('.')[1]
            # Pad to a multiple of 4 for base64 decoding.
            payload_part += '=' * (-len(payload_part) % 4)
            claims.update(json.loads(base64.urlsafe_b64decode(payload_part)))
        except Exception as e:
            LOG.warning("Could not decode JWT payload for claims: %s", e)

        # Overlay with authoritative values from the TokenReview response.
        claims['namespace'] = namespace
        claims['service_account'] = sa_name
        claims['username'] = status.user.username
        claims['groups'] = list(status.user.groups or [])

        extra = getattr(status.user, 'extra', None) or {}
        for key, values in extra.items():
            claims[key] = values
            short_key = key.split('/')[-1]
            if short_key not in claims:
                claims[short_key] = values

        LOG.debug("Auth claims for rule evaluation: %s", claims)
        return claims

    def _parse_namespce_and_username(self, username):
        """
        Expected format:
        system:serviceaccount:<namespace>:<name>
        """
        parts = username.split(":")

        if len(parts) < 4:
            LOG.error("Invalid username format from K8s: %s", username)
            raise exc.UnauthorizedException(
                message="Invalid service account identity"
            )

        return parts[2], parts[3]

    # TODO: modify later
    def _map_roles(self, sa_name):
        if sa_name in CONF.k8s_sa.admin_service_accounts:
            return ["admin"]

        return ["member"]
