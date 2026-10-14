"""
Unit tests for DBaaSHelper
"""

import pytest
import requests
from unittest.mock import MagicMock, patch

from dbaas_helper import DBaaSHelper
from pg_connection import PgConnectionInfo

NAMESPACE = "test-ns"
BASE_URL = "http://dbaas-aggregator:8080"
PG = PgConnectionInfo('my-pg', '5432', 'mistral', 'db_user', 'db_pw')


@pytest.fixture
def helper():
    return DBaaSHelper(BASE_URL + "/", "user", "pw", NAMESPACE)


def _resp(status_code, json_data=None, raise_err=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.text = str(json_data)
    r.raise_for_status.side_effect = raise_err
    return r


def test_trailing_slash_stripped():
    h = DBaaSHelper(BASE_URL + "/", "u", "p", NAMESPACE)
    assert h._base == BASE_URL


@patch('dbaas_helper.requests.post')
def test_get_by_classifier_returns_none_on_404(mock_post, helper):
    mock_post.return_value = _resp(404)
    assert helper.get_by_classifier() is None


@patch('dbaas_helper.requests.post')
def test_get_by_classifier_returns_json_on_200(mock_post, helper):
    payload = {'connectionProperties': {'host': 'pg', 'port': 5432}}
    mock_post.return_value = _resp(200, payload)
    assert helper.get_by_classifier() == payload


@patch('dbaas_helper.requests.post')
def test_get_by_classifier_raises_on_5xx(mock_post, helper):
    mock_post.return_value = _resp(500, raise_err=requests.HTTPError("500"))
    with pytest.raises(requests.HTTPError):
        helper.get_by_classifier()


@patch('dbaas_helper.requests.post')
def test_get_by_classifier_uses_correct_url_and_auth(mock_post, helper):
    mock_post.return_value = _resp(200, {})
    helper.get_by_classifier()
    url = mock_post.call_args[0][0]
    assert f"/api/v3/dbaas/{NAMESPACE}/databases/get-by-classifier/postgresql" in url
    assert mock_post.call_args[1]['auth'] == ("user", "pw")


@patch('dbaas_helper.requests.put')
def test_create_db_returns_json_on_201(mock_put, helper):
    payload = {'connectionProperties': {'host': 'new-pg'}}
    mock_put.return_value = _resp(201, payload)
    assert helper.create_db() == payload


@patch('dbaas_helper.requests.put')
def test_create_db_raises_on_error(mock_put, helper):
    mock_put.return_value = _resp(409, raise_err=requests.HTTPError("409"))
    with pytest.raises(requests.HTTPError):
        helper.create_db()

@patch('dbaas_helper.requests.put')
def test_register_external_db_sends_full_connection_details(mock_put, helper):
    mock_put.return_value = _resp(200, {})
    helper.register_external_db(PG)

    body = mock_put.call_args[1]['json']
    cp = body['connectionProperties'][0]

    assert cp['host'] == 'my-pg'
    assert cp['port'] == '5432'
    assert cp['name'] == 'mistral'
    assert cp['username'] == 'db_user'
    assert cp['password'] == 'db_pw'
    assert body['type'] == 'postgresql'
    assert body['classifier']['microserviceName'] == 'mistral-operator'
    assert body['classifier']['namespace'] == NAMESPACE


@patch('dbaas_helper.requests.put')
def test_migrate_external_sends_list_with_classifier(mock_put, helper):
    mock_put.return_value = _resp(200)
    helper.migrate_external_to_internal(PG)
    body = mock_put.call_args[1]['json']
    assert isinstance(body, list) and len(body) == 1
    assert body[0]['namespace'] == NAMESPACE
    assert body[0]['classifier']['microserviceName'] == 'mistral-operator'


@patch('dbaas_helper.requests.put')
def test_migrate_external_raises_on_error(mock_put, helper):
    mock_put.return_value = _resp(500, raise_err=requests.HTTPError("500"))
    with pytest.raises(requests.HTTPError):
        helper.migrate_external_to_internal(PG)


# --- ServiceAccount token (m2m) authentication ------------------------------

TOKEN = "sa-token-with-dbaas-audience"


@pytest.fixture
def token_file(tmp_path):
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n")
    return str(path)


def _make(mode, token_path):
    return DBaaSHelper(BASE_URL, "user", "pw", NAMESPACE,
                       m2m_auth_mode=mode, token_path=token_path)


def _bearer(call):
    return call.kwargs["headers"]["Authorization"]


@pytest.mark.parametrize("mode", [None, "", "legacy", "LEGACY", "bogus"])
@patch('dbaas_helper.requests.put')
def test_legacy_and_unknown_modes_use_basic_auth_only(mock_put, mode,
                                                      token_file):
    mock_put.return_value = _resp(200, {})

    _make(mode, token_file).create_db()

    assert mock_put.call_count == 1
    assert mock_put.call_args.kwargs["auth"] == ("user", "pw")
    assert "headers" not in mock_put.call_args.kwargs


@pytest.mark.parametrize("mode", ["k8s", "hybrid", "K8S", " Hybrid "])
@patch('dbaas_helper.requests.post')
def test_token_mode_sends_bearer_and_no_basic_auth(mock_post, mode,
                                                   token_file):
    payload = {'connectionProperties': {'host': 'pg'}}
    mock_post.return_value = _resp(200, payload)

    assert _make(mode, token_file).get_by_classifier() == payload

    assert mock_post.call_count == 1
    assert _bearer(mock_post.call_args) == "Bearer " + TOKEN
    assert "auth" not in mock_post.call_args.kwargs


@patch('dbaas_helper.requests.put')
def test_token_is_reread_on_every_call(mock_put, tmp_path):
    path = tmp_path / "token"
    path.write_text("first")
    mock_put.return_value = _resp(200, {})
    h = _make("k8s", str(path))

    h.create_db()
    path.write_text("rotated")
    h.create_db()

    assert [_bearer(c) for c in mock_put.call_args_list] == [
        "Bearer first", "Bearer rotated"]


@pytest.mark.parametrize("status", [401, 403])
@patch('dbaas_helper.requests.put')
def test_hybrid_falls_back_to_basic_when_token_rejected(mock_put, status,
                                                        token_file):
    mock_put.side_effect = [_resp(status), _resp(200, {"ok": True})]

    assert _make("hybrid", token_file).create_db() == {"ok": True}

    first, second = mock_put.call_args_list
    assert _bearer(first) == "Bearer " + TOKEN
    assert second.kwargs["auth"] == ("user", "pw")
    assert "headers" not in second.kwargs


@patch('dbaas_helper.requests.put')
def test_hybrid_does_not_fall_back_on_other_errors(mock_put, token_file):
    mock_put.return_value = _resp(500, raise_err=requests.HTTPError("500"))

    with pytest.raises(requests.HTTPError):
        _make("hybrid", token_file).create_db()

    assert mock_put.call_count == 1


@patch('dbaas_helper.requests.put')
def test_hybrid_falls_back_when_token_file_missing(mock_put, tmp_path):
    mock_put.return_value = _resp(200, {})

    _make("hybrid", str(tmp_path / "missing")).create_db()

    assert mock_put.call_count == 1
    assert mock_put.call_args.kwargs["auth"] == ("user", "pw")


@patch('dbaas_helper.requests.put')
def test_hybrid_falls_back_when_token_file_empty(mock_put, tmp_path):
    empty = tmp_path / "token"
    empty.write_text("  \n")
    mock_put.return_value = _resp(200, {})

    _make("hybrid", str(empty)).create_db()

    assert mock_put.call_args.kwargs["auth"] == ("user", "pw")


@patch('dbaas_helper.requests.put')
def test_k8s_mode_never_falls_back_to_basic_auth(mock_put, token_file):
    mock_put.return_value = _resp(401, raise_err=requests.HTTPError("401"))

    with pytest.raises(requests.HTTPError):
        _make("k8s", token_file).create_db()

    assert mock_put.call_count == 1
    assert "auth" not in mock_put.call_args.kwargs


@patch('dbaas_helper.requests.put')
def test_k8s_mode_fails_when_token_file_missing(mock_put, tmp_path):
    with pytest.raises(OSError):
        _make("k8s", str(tmp_path / "missing")).create_db()

    mock_put.assert_not_called()


def test_default_token_path_is_the_dbaas_audience_token():
    h = DBaaSHelper(BASE_URL, "u", "p", NAMESPACE, m2m_auth_mode="k8s")
    assert h._token_path == "/var/run/secrets/tokens/dbaas/token"
