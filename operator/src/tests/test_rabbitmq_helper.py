import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import rabbitmq_helper  # noqa: E402
from rabbitmq_helper import ExchangeDeleteError, RabbitMQHelper  # noqa: E402


def _resp(status, text=''):
    r = mock.Mock()
    r.status_code = status
    r.ok = 200 <= status < 400
    r.text = text
    return r


class DeleteOpenstackExchangeTest(unittest.TestCase):
    def setUp(self):
        self.helper = RabbitMQHelper(False, 'rabbit', 'vh', 'u', 'p', 'a', 'ap', 'pfx')
        patcher = mock.patch.object(rabbitmq_helper.time, 'sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def _request(self, delete, marker):
        """Fake request(): `delete`/`marker` are a response or a list of them."""
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
        self.assertEqual(req.call_count, 2)

    def test_not_found_without_marker_is_success(self):
        with self._request(_resp(404), _resp(404)):
            self.helper.delete_openstack_exchange()

    def test_not_found_with_stuck_marker_fails(self):
        with self._request(_resp(404), _resp(200)):
            with self.assertRaises(ExchangeDeleteError) as cm:
                self.helper.delete_openstack_exchange()
        self.assertIn('exchange-delete-in-progress', str(cm.exception))

    def test_marker_cleared_during_retries(self):
        with self._request(_resp(404), [_resp(200), _resp(200), _resp(404)]):
            self.helper.delete_openstack_exchange()

    def test_retries_then_succeeds(self):
        with self._request([requests.exceptions.Timeout('t'), _resp(500, 'boom'), _resp(204)], _resp(404)):
            self.helper.delete_openstack_exchange()

    def test_fails_with_reason(self):
        with self._request(_resp(500, 'stuck'), _resp(404)):
            with self.assertRaises(ExchangeDeleteError) as cm:
                self.helper.delete_openstack_exchange()
        self.assertIn('status 500', str(cm.exception))
        self.assertIn('stuck', str(cm.exception))

    def test_marker_check_error_fails(self):
        with self._request(_resp(204), _resp(500, 'oops')):
            with self.assertRaises(ExchangeDeleteError) as cm:
                self.helper.delete_openstack_exchange()
        self.assertIn('unable to check', str(cm.exception))

    def test_default_vhost_is_encoded(self):
        h = RabbitMQHelper(False, 'rabbit', rabbitmq_helper.DEFAULT_VHOST, 'u', 'p', 'a', 'ap', 'pfx')
        with mock.patch.object(h, 'request', side_effect=[_resp(204), _resp(404)]) as req:
            h.delete_openstack_exchange()
        req.assert_any_call(url='exchanges/%2f/openstack', method='DELETE')
        req.assert_any_call(
            url='parameters/exchange-delete-in-progress/%2f/openstack', method='GET')


if __name__ == '__main__':
    unittest.main()
