"""Checks for the address whitelist."""

from __future__ import annotations

import ipaddress

import pytest

from helpers import AUTH

LOCAL = (ipaddress.ip_network('127.0.0.1/32'),)
ELSEWHERE = (ipaddress.ip_network('10.0.0.0/8'),)


def test_open_by_default(client):
    """No whitelist configured means no restriction, as an unset variable implies."""
    assert client.get('/signal', headers=AUTH).status_code == 200


def test_allowed_address_passes(make_client):
    client = make_client([], allowed_networks=LOCAL)

    assert client.get('/signal', headers=AUTH).status_code == 200


def test_foreign_address_is_refused(make_client):
    client = make_client([], allowed_networks=ELSEWHERE)
    response = client.get('/signal', headers=AUTH)

    assert response.status_code == 403
    assert response.get_json()['message'] == 'Access denied'


def test_refusal_happens_before_authentication(make_client):
    """A stranger should not even get the chance to guess a password."""
    client = make_client([], allowed_networks=ELSEWHERE)

    assert client.get('/signal').status_code == 403


@pytest.mark.parametrize(
    'method, path',
    [('get', '/sms'), ('post', '/sms'), ('delete', '/sms/0'), ('get', '/reset')],
)
def test_whitelist_covers_every_route(make_client, method, path):
    client = make_client([], allowed_networks=ELSEWHERE)

    assert getattr(client, method)(path, headers=AUTH).status_code == 403


def test_subnet_membership(make_client):
    client = make_client([], allowed_networks=(ipaddress.ip_network('127.0.0.0/24'),))

    assert client.get('/signal', headers=AUTH).status_code == 200
