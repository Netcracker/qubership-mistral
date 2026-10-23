"""
Unit tests for M2M_AUTH_MODE / k8s-sa handling in KubernetesHelper
"""

import os

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
])
def test_effective_auth_type(mode, auth_type, expected):
    assert _helper(mode, auth_type).get_effective_auth_type() == expected


@pytest.mark.parametrize('mode', ['unknown', 'not-a-mode', 'k8s-sa'])
def test_invalid_m2m_auth_mode_falls_back_to_legacy(mode):
    """An unrecognized M2M_AUTH_MODE value falls back to legacy mode."""
    assert _helper(mode).get_effective_auth_type() == 'keycloak-oidc'


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


# ---------------------------------------------------------------------------
# Pod specs. Outbound calls (actions, webhook notifications) use the projected
# SA token in k8s/hybrid mode, so pure k8s mode needs no IDP client credentials.
# ---------------------------------------------------------------------------

class _Spec(dict):
    """CR spec that returns an empty section for keys the test doesn't set."""

    def __missing__(self, key):
        value = self[key] = _Spec()
        return value


def _wrap(obj):
    if isinstance(obj, dict):
        return _Spec({k: _wrap(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_wrap(v) for v in obj]
    return obj


def _deployment_helper(m2m_mode, cloudcore=False):
    from unittest import mock

    import yaml
    from kubernetes import client

    cr = os.path.join(os.path.dirname(__file__), '..', '..', 'deploy',
                      'cr.yaml')
    with open(cr, encoding='utf-8') as f:
        spec = _wrap(yaml.safe_load(f)['spec'])
    spec['mistral']['m2mAuthMode'] = m2m_mode
    spec['mistral']['cloudCoreIntegrationEnabled'] = cloudcore
    spec['mistralCommonParams']['auth'] = _wrap(
        {'enable': True, 'type': 'keycloak-oidc'})

    h = KubernetesHelper.__new__(KubernetesHelper)
    h._workspace = 'test-ns'
    h._spec = spec
    h._api_client = client.ApiClient()
    h._v1_apps_api = mock.MagicMock()
    h._v1_apps_api.list_namespaced_secret.return_value.items = []
    return h


def _pod_specs(h):
    """Pod specs of every Mistral service plus the robot tests pod."""
    specs = {
        name: h.generate_deployment_config_body(
            name, server).spec.template.spec
        for name, server in MC.SERVICES_NAME_TO_SERVER.items()
    }
    specs['robot'] = h.generate_robot_tests_pod_template_body(
    ).spec.template.spec
    return specs


def _projected_audiences(pod_spec):
    return [
        src.service_account_token.audience
        for vol in pod_spec.volumes
        if vol.projected
        for src in vol.projected.sources
    ]


def _token_mounts(pod_spec):
    return [
        m.mount_path
        for c in pod_spec.containers
        for m in (c.volume_mounts or [])
        if m.name == MC.K8S_SA_AUDIENCE_TOKEN_VOLUME
    ]


def _env(pod_spec, name):
    return [
        e.value
        for c in pod_spec.containers
        for e in (c.env or [])
        if e.name == name
    ]


@pytest.mark.parametrize('mode', ['legacy', 'k8s', 'hybrid'])
def test_pod_specs_are_serializable(mode):
    h = _deployment_helper(mode)

    for pod_spec in _pod_specs(h).values():
        h._api_client.sanitize_for_serialization(pod_spec)


@pytest.mark.parametrize('mode,expected', [
    ('legacy', False),
    ('k8s', True),
    ('hybrid', True),
])
def test_every_mistral_pod_gets_the_audience_token(mode, expected):
    """The notifier/executor/engine send the requests, not only the API."""
    pods = _pod_specs(_deployment_helper(mode))

    assert len(pods) > 2
    for name, pod_spec in pods.items():
        if expected:
            assert _projected_audiences(pod_spec) == [MC.K8S_SA_AUDIENCE], name
            assert _token_mounts(pod_spec) == [
                f'{MC.K8S_SA_AUDIENCE_TOKENS_DIR}/{MC.K8S_SA_AUDIENCE}'
            ], name
        else:
            assert _projected_audiences(pod_spec) == [], name
            assert _token_mounts(pod_spec) == [], name


@pytest.mark.parametrize('mode', ['legacy', 'k8s', 'hybrid'])
def test_mistral_pods_get_the_audience_env(mode):
    for name, pod_spec in _pod_specs(_deployment_helper(mode)).items():
        if name == 'robot':
            continue
        assert 'K8S_SA_AUDIENCE' in [
            e.name for c in pod_spec.containers for e in (c.env or [])
        ], name


@pytest.mark.parametrize('mode,creds_source,mounted', [
    ('legacy', 'cloudcore', True),
    ('hybrid', 'cloudcore', True),
    ('k8s', 'mistral-secret', False),
])
def test_idp_secret_only_when_keycloak_is_used(mode, creds_source, mounted):
    pod_spec = _pod_specs(
        _deployment_helper(mode, cloudcore=True))['mistral-api']

    assert _env(pod_spec, 'IDP_CREDS_SOURCE') == [creds_source]
    assert ('mistral-client-credentials' in
            [v.name for v in pod_spec.volumes]) is mounted
