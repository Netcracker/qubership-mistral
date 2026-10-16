"""
Unit tests for M2M_AUTH_MODE / k8s-sa handling in KubernetesHelper
"""

import pytest

import mistral_constants as MC
from kubernetes_helper import KubernetesHelper


def _helper(m2m_mode='', auth_type='keycloak-oidc', auth_enable=True,
            k8s_sa=None):
    h = KubernetesHelper.__new__(KubernetesHelper)
    h._workspace = 'test-ns'
    auth = {'enable': auth_enable, 'type': auth_type}
    if k8s_sa is not None:
        auth['k8sSa'] = k8s_sa
    h._spec = {
        'mistral': {'m2mAuthMode': m2m_mode},
        'mistralCommonParams': {'auth': auth},
    }
    return h


@pytest.mark.parametrize('mode,auth_type,expected', [
    ('legacy', 'k8s-sa', 'keycloak-oidc'),
    ('hybrid', 'keycloak-oidc', 'hybrid'),
    ('k8s', 'keycloak-oidc', 'k8s-sa'),
    ('K8S', 'keycloak-oidc', 'k8s-sa'),
    ('', 'mitreid', 'mitreid'),
    ('unknown', 'keycloak-oidc', 'keycloak-oidc'),
])
def test_effective_auth_type(mode, auth_type, expected):
    assert _helper(mode, auth_type).get_effective_auth_type() == expected


@pytest.mark.parametrize('mode,enabled,expected', [
    ('legacy', True, False),
    ('hybrid', True, True),
    ('k8s', True, True),
    ('k8s', False, False),
])
def test_token_volume_only_for_k8s_and_hybrid(mode, enabled, expected):
    assert _helper(mode, auth_enable=enabled).is_k8s_sa_auth_enabled() \
        is expected


def test_audience_defaults_to_netcracker():
    h = _helper('k8s')

    assert h.get_k8s_sa_audience() == MC.K8S_SA_AUDIENCE == 'netcracker'


def test_configured_audience_drives_volume_and_mount():
    h = _helper('k8s', k8s_sa={'audience': 'my-aud'})

    vol = h._get_k8s_sa_audience_token_volume()
    mount = h._get_k8s_sa_audience_token_volume_mount()

    projection = vol.projected.sources[0].service_account_token
    assert projection.audience == 'my-aud'
    assert mount.name == vol.name
    assert mount.mount_path == f'{MC.K8S_SA_AUDIENCE_TOKENS_DIR}/my-aud'


def test_k8s_sa_envs_reference_configmap_keys():
    envs = KubernetesHelper._get_k8s_sa_envs()
    keys = {e.name: e.value_from.config_map_key_ref.key for e in envs}

    assert keys == {'K8S_SA_AUDIENCE': 'k8s-sa-audience'}
