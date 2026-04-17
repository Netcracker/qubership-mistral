from oslo_log import log as logging
from oslo_config import cfg
import re

from kubernetes import client, config

from mistral._i18n import _
from mistral import auth
from mistral import exceptions as exc


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

TOKEN_HEADER_KEY = 'Authorization'
AUTH_HEADER_PATTERN = re.compile(r'^\w+\s(.*)$')
DEFAULT_PROJECT_ID = "<default-project>"

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

    def __init__(self):
        super(K8sSAAuthHandler, self).__init__()

        try:
            # If running inside K8s
            config.load_incluster_config()
            LOG.info("Loaded in-cluster Kubernetes config")
        except Exception:
            # fallback for local/dev
            config.load_kube_config()
            LOG.info("Loaded kubeconfig for Kubernetes")

        self.api = client.AuthenticationV1Api()

    def authenticate(self, req):
        LOG.info("K8sSAAuthHandler.authenticate() called")
        LOG.info("Incoming headers: %s", req.headers)
        headers = req.headers
        token = extract_token_from_header(headers)


        response = self._review_token(token)
        LOG.info("TokenReview response: %s", response)

        if not response.status or not response.status.authenticated:
            LOG.warning("K8s token authentication failed")
            raise exc.UnauthorizedException(message="Invalid K8s SA token")

        user = response.status.user

        namespace, sa_name = self._parse_username(user.username)
        roles = self._map_roles(user.groups)

        # TODO: change header
        req.headers["X-Identity-Status"] = "Confirmed"
        req.headers["X-Project-Id"] = DEFAULT_PROJECT_ID
        req.headers["X-User-Id"] = sa_name
        req.headers["X-Roles"] = ','.join(roles)

        LOG.debug(
            "Authenticated K8s SA token: namespace=%s, sa=%s, roles=%s",
            namespace, sa_name, roles
        )

    def _review_token(self, token):
        try:
            review = client.V1TokenReview(
                spec=client.V1TokenReviewSpec(token=token)
            )

            return self.api.create_token_review(review)

        except Exception as e:
            LOG.exception("Error calling Kubernetes TokenReview API: %s", str(e))
            raise exc.UnauthorizedException(
                message=_("Failed to validate token with Kubernetes")
            )

    def _parse_username(self, username):
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

    # TODO: change as per requirement
    def _map_roles(self, groups):
        """
        Map K8s groups to Mistral roles
        """
        if not groups:
            return ["member"]

        if "system:masters" in groups:
            return ["admin"]

        return ["member"]
