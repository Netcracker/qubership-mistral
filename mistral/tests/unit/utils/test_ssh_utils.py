""" unit tests for allowed_proxy_commands """

from unittest import mock

from mistral import exceptions as exc
from mistral.tests.unit import base
from mistral.utils import ssh_utils


class ProxyCommandAllowListTest(base.BaseTest):
    """Tests the [action_std_ssh] allowed_proxy_commands allow-list.

    A caller-supplied proxy_command is run as a local subprocess on the
    executor host before SSH authentication, so it is a remote code
    execution vector. Only commands explicitly allow-listed by an
    administrator may be used; the default (empty list) rejects any
    proxy_command. Matching is by exact string.
    """

    def _run_with_gateway(self, proxy_command):
        """Call execute_command_via_gateway, isolating it from paramiko.

        The allow-list check happens before any real SSH connection, so
        only _connect and the missing gateway client are mocked; the
        private key resolution returns None when no key is supplied.
        """
        with mock.patch.object(
            ssh_utils, '_connect', return_value=mock.MagicMock()
        ), mock.patch.object(
            ssh_utils, '_execute_command', return_value=(0, 'ok')
        ), mock.patch.object(
            ssh_utils.paramiko, 'ProxyCommand'
        ) as mock_proxy_command, mock.patch.object(
            ssh_utils.paramiko, 'SSHClient'
        ):
            result = ssh_utils.execute_command_via_gateway(
                cmd='echo ok',
                host='target',
                username='user',
                private_key_filename=None,
                gateway_host='gateway',
                proxy_command=proxy_command,
            )

        return result, mock_proxy_command

    def test_empty_allow_list_rejects_proxy_command(self):
        # The default configuration has an empty allow-list, which must
        # reject any proxy_command instead of running it.
        self.assertRaises(
            exc.ActionException,
            self._run_with_gateway,
            'nc target 22',
        )

    def test_unlisted_proxy_command_rejected_when_allow_list_populated(self):
        self.override_config(
            'allowed_proxy_commands',
            ['nc trusted-host 22'],
            group='action_std_ssh',
        )

        self.assertRaises(
            exc.ActionException,
            self._run_with_gateway,
            'nc other-host 22',
        )

    def test_near_match_is_rejected(self):
        # Matching is exact: an appended argument (argument smuggling) or a
        # one-character difference must not pass the allow-list.
        allowed = 'nc trusted-host 22'
        self.override_config(
            'allowed_proxy_commands',
            [allowed],
            group='action_std_ssh',
        )

        for near_match in (
            allowed + ' ; rm -rf /',
            allowed + ' extra',
            allowed.replace('trusted-host', 'trusted-hosT'),
        ):
            self.assertRaises(
                exc.ActionException,
                self._run_with_gateway,
                near_match,
            )

    def test_exact_match_is_allowed(self):
        proxy_command = 'nc trusted-host 22'
        self.override_config(
            'allowed_proxy_commands',
            [proxy_command],
            group='action_std_ssh',
        )

        result, mock_proxy_command = self._run_with_gateway(proxy_command)

        self.assertEqual((0, 'ok'), result)
        mock_proxy_command.assert_called_once_with(proxy_command)

    def test_no_proxy_command_does_not_use_allow_list(self):
        # Without a proxy_command the allow-list is irrelevant: nothing is
        # executed locally and the connection proceeds without a proxy.
        with mock.patch.object(
            ssh_utils.paramiko, 'ProxyCommand'
        ) as mock_proxy_command:
            result, _ = self._run_with_gateway(None)

        self.assertEqual((0, 'ok'), result)
        mock_proxy_command.assert_not_called()
