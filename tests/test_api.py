"""HTTP layer checks: authentication, status codes, parameter parsing."""

from __future__ import annotations

import pytest

from helpers import AUTH, basic_auth

# Every route of the service: none of them may answer without credentials
ENDPOINTS = [
    ('get', '/sms'),
    ('post', '/sms'),
    ('get', '/sms/0'),
    ('delete', '/sms/0'),
    ('get', '/getsms'),
    ('get', '/signal'),
    ('get', '/network'),
    ('get', '/reset'),
]


@pytest.mark.parametrize('method, path', ENDPOINTS)
def test_endpoint_requires_auth(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(
    'credentials',
    [
        pytest.param(basic_auth(password='wrong'), id='wrong password'),
        pytest.param(basic_auth(username='nobody'), id='unknown user'),
        pytest.param(basic_auth(password=''), id='empty password'),
    ],
)
def test_bad_credentials_rejected(client, credentials):
    assert client.get('/signal', headers=credentials).status_code == 401


def test_unauthorized_response_is_json(client):
    response = client.get('/signal')

    assert response.is_json
    assert 'message' in response.get_json()
    # Without this header the reply is not a valid Basic authentication challenge
    assert 'WWW-Authenticate' in response.headers


def test_signal(client):
    response = client.get('/signal', headers=AUTH)

    assert response.status_code == 200
    assert response.get_json()['SignalPercent'] == 75


def test_network_includes_operator_name(client):
    assert client.get('/network', headers=AUTH).get_json()['NetworkName'] == 'MTS'


def test_reset(client):
    response = client.get('/reset', headers=AUTH)

    assert response.status_code == 200
    assert response.get_json()['message'] == 'Reset done'


@pytest.mark.parametrize('path', ['/sms', '/sms/0', '/getsms'])
def test_locations_are_not_exposed(client, path):
    """Locations are internal addresses in modem memory and are never exposed."""
    payload = client.get(path, headers=AUTH).get_json()
    messages = payload if isinstance(payload, list) else [payload]

    assert all('Locations' not in message for message in messages)
    assert all(message['Text'] == 'привет' for message in messages)


def test_send_splits_and_trims_numbers(empty_client):
    response = empty_client.post(
        '/sms',
        data={'number': ' +79001111111 , +79002222222 ', 'text': 'привет'},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert empty_client.modem.sent[-1]['numbers'] == ['+79001111111', '+79002222222']


def test_send_accepts_json_body(empty_client):
    empty_client.post(
        '/sms',
        json={'number': '+79001111111', 'text': 'привет', 'smsc': '+79001112233'},
        headers=AUTH,
    )
    sent = empty_client.modem.sent[-1]

    assert sent['text'] == 'привет'
    assert sent['smsc'] == '+79001112233'


@pytest.mark.parametrize(
    'value, expected',
    [('True', True), ('1', True), ('on', True), ('false', False), ('0', False), (None, False)],
)
def test_unicode_flag_parsed_as_bool(empty_client, value, expected):
    data = {'number': '+79001111111', 'text': 'привет'}
    if value is not None:
        data['unicode'] = value

    empty_client.post('/sms', data=data, headers=AUTH)

    assert empty_client.modem.sent[-1]['unicode'] is expected


@pytest.mark.parametrize(
    'data',
    [
        pytest.param({'text': 'привет'}, id='no number'),
        pytest.param({'number': '+79001111111'}, id='no text'),
        pytest.param({'number': '', 'text': 'привет'}, id='empty number'),
        pytest.param({'number': ',,', 'text': 'привет'}, id='separators only'),
    ],
)
def test_incomplete_request_returns_400(empty_client, data):
    response = empty_client.post('/sms', data=data, headers=AUTH)

    assert response.status_code == 400
    assert not empty_client.modem.sent


@pytest.mark.parametrize('method', ['get', 'delete'])
def test_unknown_sms_returns_404(empty_client, method):
    assert getattr(empty_client, method)('/sms/5', headers=AUTH).status_code == 404


def test_getsms_returns_empty_structure_on_empty_inbox(empty_client):
    response = empty_client.get('/getsms', headers=AUTH)

    assert response.status_code == 200
    assert response.get_json() == {'Date': '', 'Number': '', 'State': '', 'Text': ''}


def test_getsms_removes_message(client):
    assert client.get('/getsms', headers=AUTH).get_json()['Text'] == 'привет'
    assert client.get('/getsms', headers=AUTH).get_json()['Text'] == ''


def test_delete_removes_message(client):
    response = client.delete('/sms/0', headers=AUTH)

    assert response.status_code == 204
    assert client.get('/sms', headers=AUTH).get_json() == []


@pytest.mark.parametrize('method, path', ENDPOINTS)
def test_modem_failure_returns_502(make_client, method, path):
    """A device failure must not surface as a 500 with a traceback."""
    client = make_client([], fail=True)
    data = {'number': '+79001111111', 'text': 'привет'}

    response = getattr(client, method)(path, data=data, headers=AUTH)

    assert response.status_code == 502
    assert 'Modem error' in response.get_json()['message']
