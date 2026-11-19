from unittest import mock

import requests

from mistral.tests.unit import base
from mistral import nc_upgrade



def _resp(status, text=''):
    r = mock.Mock()
    r.status_code = status
    r.ok = 200 <= status < 400
    r.text = text
    return r


class DeleteOpenstackExchangeTest(base.BaseTest):
    def setUp(self):
        super(DeleteOpenstackExchangeTest, self).setUp()
        self.helper = nc_upgrade.RabbitMQHelper()
        self.helper._vhost = 'vh'
        p = mock.patch.object(nc_upgrade.time, 'sleep')
        p.start()
        self.addCleanup(p.stop)

    def _request(self, delete, marker):
        queues = {'DELETE': delete, 'GET': marker}

        def fake(url, method='PUT', json=None, timeout=None):
            q = queues[method]
            item = q.pop(0) if isinstance(q, list) else q
            if isinstance(item, Exception):
                raise item
            return item

        return mock.patch.object(self.helper, 'request', side_effect=fake)

    def test_deleted(self):
        with self._request(_resp(204), _resp(404)) as req:
            self.helper.delete_openstack_exchange()
        self.assertEqual(2, req.call_count)

    def test_not_found_with_stuck_marker_fails(self):
        with self._request(_resp(404), _resp(200)):
            with self.assertRaises(nc_upgrade.ExchangeDeleteError) as cm:
                self.helper.delete_openstack_exchange()
        self.assertIn('exchange-delete-in-progress', str(cm.exception))

    def test_retries_then_succeeds(self):
        with self._request(
                [requests.exceptions.Timeout('t'), _resp(500), _resp(204)],
                _resp(404)):
            self.helper.delete_openstack_exchange()

    def test_fails_with_reason(self):
        with self._request(_resp(500, 'stuck'), _resp(404)):
            with self.assertRaises(nc_upgrade.ExchangeDeleteError) as cm:
                self.helper.delete_openstack_exchange()
        self.assertIn('status 500', str(cm.exception))

    def test_command_exits_non_zero(self):
        with mock.patch.object(
                nc_upgrade.RabbitMQHelper, 'delete_existing_queues',
                side_effect=nc_upgrade.ExchangeDeleteError('boom')):
            with self.assertRaises(SystemExit) as cm:
                nc_upgrade.delete_existing_queues(None, None)
        self.assertEqual(1, cm.exception.code)
