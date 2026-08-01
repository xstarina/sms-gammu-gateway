"""Checks for password verification, hashed and plain."""

from __future__ import annotations

import base64

import pytest
from werkzeug.security import generate_password_hash

from helpers import FakeModem, basic_auth
from sms_gateway.api import create_app, password_matches

PLAIN = 'secret'
HASHED = generate_password_hash(PLAIN)


def client_for(users):
    app = create_app(FakeModem([]), users)
    app.config['TESTING'] = True
    return app.test_client()


def test_hash_looks_nothing_like_the_password():
    """The point of storing a hash: the variable no longer carries the password."""
    assert PLAIN not in HASHED
    assert HASHED.startswith('scrypt:')


@pytest.mark.parametrize(
    'stored',
    [pytest.param(PLAIN, id='plain'), pytest.param(HASHED, id='hashed')],
)
def test_correct_password_is_accepted(stored):
    response = client_for({'admin': stored}).get('/signal', headers=basic_auth())

    assert response.status_code == 200


@pytest.mark.parametrize(
    'stored',
    [pytest.param(PLAIN, id='plain'), pytest.param(HASHED, id='hashed')],
)
def test_wrong_password_is_rejected(stored):
    headers = basic_auth(password='wrong')
    response = client_for({'admin': stored}).get('/signal', headers=headers)

    assert response.status_code == 401


def test_hash_itself_is_not_a_password():
    """Someone who reads the variable must not be able to log in with what they saw."""
    token = base64.b64encode(f'admin:{HASHED}'.encode()).decode()
    response = client_for({'admin': HASHED}).get(
        '/signal', headers={'Authorization': f'Basic {token}'}
    )

    assert response.status_code == 401


@pytest.mark.parametrize('prefix', ['scrypt:', 'pbkdf2:'])
def test_both_werkzeug_algorithms_are_recognised(prefix):
    method = 'scrypt' if prefix == 'scrypt:' else 'pbkdf2'
    stored = generate_password_hash(PLAIN, method=method)

    assert password_matches(stored, PLAIN)
    assert not password_matches(stored, 'wrong')


def test_plain_password_may_contain_a_colon():
    assert password_matches('pa:ss', 'pa:ss')
