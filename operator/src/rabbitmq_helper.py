"""
Module to handle all the kubernetes operations
"""

import logging
import time

import requests
from requests import auth

from mistral_constants import DEFAULT_VHOST

LOG = logging.getLogger(__name__)

OPENSTACK_EXCHANGE = 'openstack'
EXCHANGE_DELETE_ATTEMPTS = 3
EXCHANGE_DELETE_RETRY_DELAY = 5
REQUEST_TIMEOUT = 30


class ExchangeDeleteError(Exception):
    """Raised when the openstack exchange could not be deleted."""


class RabbitMQHelper(object):
    def __init__(self, rabbit_tls_enabled, rabbit_host, rabbit_vhost, rabbit_user, rabbit_password, admin_user,
                 admin_password, queue_name_prefix):
        self._tls_enabled = rabbit_tls_enabled
        self._host = rabbit_host
        self._vhost = rabbit_vhost
        self._user = rabbit_user
        self._password = rabbit_password
        self._admin_user = admin_user
        self._admin_password = admin_password
        self._queue_name_prefix = queue_name_prefix

    def create_rabbit_vhost(self):
        if self._vhost == DEFAULT_VHOST:
            LOG.info('Default vhost is used. Skip a vhost creation')
            return

        res = self.request(
            "vhosts/{vhost}".format(vhost=self._vhost)
        )
        res.raise_for_status()
        LOG.info('Created {} rabbit vhost'.format(self._vhost))

    def create_rabbit_user(self):
        if self._admin_user == self._user:
            LOG.info('Admin user equals user. Skip a user creation')
            return

        body = {
            'password': self._password,
            'tags': ''
        }
        res = self.request(
            url='users/' + self._user,
            json=body
        )
        res.raise_for_status()
        LOG.info('Created {} rabbit user'.format(self._user))

    def add_rabbit_permissions(self):
        if self._vhost == DEFAULT_VHOST and self._user == self._admin_user:
            LOG.info('Default user and vhost are used. Skip a set permissions')
            return

        vhost = '%2f' if self._vhost == DEFAULT_VHOST else self._vhost
        body = {
            "configure": ".*", "write": ".*", "read": ".*"
        }
        res = self.request(
            url='permissions/{vhost}/{user}'.format(
                vhost=vhost, user=self._user),
            json=body
        )
        res.raise_for_status()
        LOG.info(
            'Add {} permissions to {} vhost'.format(self._user, vhost))

    def delete_existing_queues(self):
        vhost = '%2f' if self._vhost == DEFAULT_VHOST else self._vhost
        res = self.request(
            url='queues/{vhost}'.format(vhost=vhost),
            method='GET'
        )

        res.raise_for_status()

        queues_to_delete = []

        LOG.info(
            "Searching for existing mistral "
            "queues in {} vhost with {} prefix".format(
                vhost, self._queue_name_prefix
            )
        )

        def _is_mistral_queue(name):
            if not name.startswith(self._queue_name_prefix):
                return False
            if 'mistral' not in name:
                return False
            return True

        for queue in res.json():
            if _is_mistral_queue(queue['name']):
                queues_to_delete.append(queue['name'])

        if not queues_to_delete:
            LOG.info('There are no queues to delete.')
            self.delete_openstack_exchange()
            return

        LOG.info('Founded queues to delete: {}'.format(str(queues_to_delete)))

        for queue in queues_to_delete:
            res = self.request(
                url='queues/{vhost}/{name}'.format(
                    vhost=vhost, name=queue
                ),
                method='DELETE'
            )
            res.raise_for_status()

        LOG.info('Queues were deleted.')

        self.delete_openstack_exchange()

    def _delete_in_progress_marker_exists(self, vhost):
        """Check RabbitMQ's exchange-delete-in-progress marker.

        A stuck marker makes RabbitMQ ignore every exchange.declare for the
        exchange ("exchange.delete in progress"), although the exchange is
        already missing from the exchanges list and DELETE returns 404.

        The marker is an internal runtime parameter (component
        "exchange-delete-in-progress", registered by rabbit_exchange_parameters
        in RabbitMQ 3.x/4.x). rabbit_exchange:declare looks up exactly this
        parameter, and rabbit_exchange:delete sets it first and clears it in
        its "after" clause. It is not listed in the public docs, but it is
        served by the generic /api/parameters/<component>/<vhost>/<name>
        endpoint, so a 404 here means the row that declare checks is absent.
        """
        res = self.request(
            url='parameters/exchange-delete-in-progress/{vhost}/{name}'.format(
                vhost=vhost, name=OPENSTACK_EXCHANGE),
            method='GET'
        )
        if res.status_code == 404:
            return False
        if res.ok:
            return True
        raise ExchangeDeleteError(
            'unable to check exchange-delete-in-progress marker, RabbitMQ '
            'responded with status {}: {}'.format(
                res.status_code, (res.text or '')[:500]))

    def delete_openstack_exchange(self):
        """Delete the openstack exchange and make sure it is really gone.

        The delete is considered successful only if RabbitMQ reports the
        exchange as deleted (2xx) or missing (404) AND no
        exchange-delete-in-progress marker is left for it. Any other outcome
        (non-2xx response, timeout, connection error, stuck marker) is retried
        and, if it persists, ExchangeDeleteError is raised with the reason of
        the last failure.
        """
        vhost = '%2f' if self._vhost == DEFAULT_VHOST else self._vhost
        url = 'exchanges/{vhost}/{name}'.format(
            vhost=vhost, name=OPENSTACK_EXCHANGE)
        reason = None

        for attempt in range(1, EXCHANGE_DELETE_ATTEMPTS + 1):
            LOG.info(
                'Delete %s exchange in %s vhost (attempt %d/%d)',
                OPENSTACK_EXCHANGE, vhost, attempt, EXCHANGE_DELETE_ATTEMPTS)
            reason = None
            try:
                res = self.request(url=url, method='DELETE')
                if res.status_code == 404:
                    LOG.info('%s exchange does not exist', OPENSTACK_EXCHANGE)
                elif res.ok:
                    LOG.info('%s exchange was deleted', OPENSTACK_EXCHANGE)
                else:
                    reason = 'RabbitMQ responded with status {}: {}'.format(
                        res.status_code, (res.text or '')[:500])

                if reason is None:
                    if not self._delete_in_progress_marker_exists(vhost):
                        return
                    reason = (
                        'exchange is missing, but its '
                        'exchange-delete-in-progress marker is still set, so '
                        'RabbitMQ ignores exchange.declare for it. Clear it '
                        'with: DELETE /api/parameters/'
                        'exchange-delete-in-progress/{}/{}'.format(
                            vhost, OPENSTACK_EXCHANGE))
            except requests.exceptions.RequestException as e:
                reason = 'request to RabbitMQ failed: {}: {}'.format(
                    type(e).__name__, e)
            except ExchangeDeleteError as e:
                reason = str(e)

            LOG.warning(
                'Failed to delete %s exchange (attempt %d/%d): %s',
                OPENSTACK_EXCHANGE, attempt, EXCHANGE_DELETE_ATTEMPTS, reason)
            if attempt < EXCHANGE_DELETE_ATTEMPTS:
                time.sleep(EXCHANGE_DELETE_RETRY_DELAY)

        message = (
            'Failed to delete {name} exchange in {vhost} vhost on {host} '
            'after {n} attempts. Last error: {reason}'.format(
                name=OPENSTACK_EXCHANGE, vhost=vhost, host=self._host,
                n=EXCHANGE_DELETE_ATTEMPTS, reason=reason))
        LOG.error(message)
        raise ExchangeDeleteError(message)

    def request(self, url, method='PUT', json=None, timeout=REQUEST_TIMEOUT):
        scheme = "https" if self._tls_enabled else "http"
        port = 15671 if self._tls_enabled else 15672
        res = requests.request(
            url=f"{scheme}://{self._host}:{port}/api/{url}",
            method=method,
            auth=auth.HTTPBasicAuth(self._admin_user, self._admin_password),
            json=json,
            verify=False if self._tls_enabled else True,
            timeout=timeout)

        return res
