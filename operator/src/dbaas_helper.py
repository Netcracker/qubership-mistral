"""
DBaaS REST API client for database lifecycle management.
"""

import logging
import requests

import mistral_constants as MC
from pg_connection import PgConnectionInfo

logger = logging.getLogger(__name__)

_MICROSERVICE_NAME = "mistral-operator"
_DB_TYPE = "postgresql"

_M2M_LEGACY = "legacy"
_M2M_HYBRID = "hybrid"
_M2M_K8S = "k8s"

# The aggregator answers 401 when it does not accept Bearer tokens (its own
# M2M_AUTH_MODE is "legacy") and 401/403 when the ServiceAccount has no role
# for the endpoint (e.g. migration needs MIGRATION_CLIENT).
_TOKEN_REJECTED = (401, 403)


class DBaaSHelper:
    """Client for the DBaaS aggregator.

    ``m2m_auth_mode`` selects how requests are authenticated:

    * ``legacy`` (default): HTTP basic auth with the DBaaS user.
    * ``k8s``: Bearer ServiceAccount token with the ``dbaas`` audience only.
    * ``hybrid``: the ServiceAccount token first; basic auth if the token
      cannot be read or the aggregator rejects it (401/403).
    """

    def __init__(self, aggregator_url, dbaas_user, dbaas_password, namespace,
                 m2m_auth_mode=None, token_path=None):
        self._base = aggregator_url.rstrip("/")
        self._auth = (dbaas_user, dbaas_password)
        self._namespace = namespace

        mode = (m2m_auth_mode or "").strip().lower()
        self._m2m_mode = mode if mode in (_M2M_HYBRID, _M2M_K8S) \
            else _M2M_LEGACY
        self._token_path = token_path or (
            f"{MC.K8S_SA_AUDIENCE_TOKENS_DIR}/{MC.DBAAS_AUDIENCE}/token"
        )

    def _read_token(self):
        # Read on every call: the kubelet rotates the projected token.
        with open(self._token_path, "r") as f:
            token = f.read().strip()
        if not token:
            raise ValueError(f"DBaaS token file {self._token_path} is empty")
        return token

    def _send(self, method, url, body):
        send = getattr(requests, method)

        if self._m2m_mode != _M2M_LEGACY:
            try:
                token = self._read_token()
            except (OSError, ValueError) as e:
                if self._m2m_mode == _M2M_K8S:
                    raise
                logger.warning(
                    "DBaaS: ServiceAccount token is not available (%s), "
                    "falling back to basic auth", e
                )
            else:
                resp = send(
                    url, json=body,
                    headers={"Authorization": f"Bearer {token}"}
                )
                if (self._m2m_mode == _M2M_K8S
                        or resp.status_code not in _TOKEN_REJECTED):
                    return resp
                logger.warning(
                    "DBaaS rejected the ServiceAccount token (HTTP %s), "
                    "falling back to basic auth", resp.status_code
                )

        return send(url, json=body, auth=self._auth)

    def _classifier(self):
        return {
            "microserviceName": _MICROSERVICE_NAME,
            "scope": "service",
            "namespace": self._namespace,
        }

    def get_by_classifier(self):
        url = (
            f"{self._base}/api/v3/dbaas/{self._namespace}"
            "/databases/get-by-classifier/postgresql"
        )
        body = {
            "classifier": self._classifier(),
            "originService": _MICROSERVICE_NAME,
        }
        resp = self._send("post", url, body)
        if resp.status_code == 404:
            return None
        if resp.status_code == 200:
            return resp.json()
        logger.error(
            "DBaaS get_by_classifier failed: %s %s", resp.status_code, resp.text
        )
        resp.raise_for_status()

    def create_db(self):
        url = f"{self._base}/api/v3/dbaas/{self._namespace}/databases"
        body = {
            "classifier": self._classifier(),
            "type": _DB_TYPE,
            "originService": _MICROSERVICE_NAME,
        }
        resp = self._send("put", url, body)
        if resp.status_code in (200, 201):
            logger.info("DBaaS: database created/retrieved successfully")
            return resp.json()
        logger.error("DBaaS create_db failed: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()

    def register_external_db(self, pg:PgConnectionInfo):
        url = (
            f"{self._base}/api/v3/dbaas/{self._namespace}"
            "/databases/registration/externally_manageable"
        )
        connection_url = f"jdbc:postgresql://{pg.host}:{pg.port}/{pg.db_name}"
        body = {
            "classifier": self._classifier(),
            "connectionProperties": [
                {
                    "host": pg.host,
                    "port": pg.port,
                    "url": connection_url,
                    "role": "admin",
                    "name": pg.db_name,
                    "username": pg.user,
                    "password": pg.password,
                }
            ],
            "dbName": pg.db_name,
            "type": _DB_TYPE,
            "updateConnectionProperties": False,
        }
        resp = self._send("put", url, body)
        if resp.status_code in (200, 201):
            logger.info("DBaaS: external database registered successfully")
            return resp.json()
        logger.error(
            "DBaaS register_external_db failed: %s %s", resp.status_code, resp.text
        )
        resp.raise_for_status()

    def migrate_external_to_internal(
        self, pg:PgConnectionInfo
    ):
        url = f"{self._base}/api/v3/dbaas/migration/databases"
        connection_url = f"jdbc:postgresql://{pg.host}:{pg.port}/{pg.db_name}"
        body = [
            {
                "backupDisabled": False,
                "classifier": self._classifier(),
                "connectionProperties": [
                    {
                        "host": pg.host,
                        "port": pg.port,
                        "url": connection_url,
                        "role": "admin",
                        "name": pg.db_name,
                        "username": pg.user,
                        "password": pg.password,
                    }
                ],
                "name": pg.db_name,
                "namespace": self._namespace,
                "dbHost": pg.host,
                "resources": [
                    {
                        "kind": "user",
                        "name": pg.user,
                    }
                ],
                "type": _DB_TYPE,
            }
        ]
        resp = self._send("put", url, body)
        if resp.status_code == 200:
            logger.info("DBaaS: database migrated from external to internal")
        else:
            logger.error(
                "DBaaS migrate_external_to_internal failed: %s %s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
