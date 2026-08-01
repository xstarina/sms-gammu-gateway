"""Checks for password verification: bcrypt, werkzeug hashes and plain text."""

from __future__ import annotations

import base64

import pytest
from werkzeug.security import generate_password_hash

from helpers import FakeModem, basic_auth
from sms_gateway.api import create_app, password_matches

PLAIN = 'secret'

# Produced by `htpasswd -nbB admin secret`, kept verbatim so the test covers the
# exact string that tool hands out
BCRYPT = '$2y$05$9F7kBCq2MTqsnSehrbZeKu3E1mJzt38dffCKJJsHZFVSlrcILp6PO'

SCRYPT = generate_password_hash(PLAIN)


def client_for(users):
    app = create_app(FakeModem([]), users)
    app.config['TESTING'] = True
    return app.test_client()


def test_bcrypt_hash_is_short_enough_to_paste():
    """The reason bcrypt is the documented default: scrypt runs to 162 characters."""
    assert len(BCRYPT) == 60
    assert len(SCRYPT) > 150


@pytest.mark.parametrize(
    'stored',
    [
        pytest.param(PLAIN, id='plain'),
        pytest.param(BCRYPT, id='bcrypt from htpasswd'),
        pytest.param(SCRYPT, id='scrypt from werkzeug'),
    ],
)
def test_correct_password_is_accepted(stored):
    assert client_for({'admin': stored}).get('/signal', headers=basic_auth()).status_code == 200


@pytest.mark.parametrize(
    'stored',
    [
        pytest.param(PLAIN, id='plain'),
        pytest.param(BCRYPT, id='bcrypt from htpasswd'),
        pytest.param(SCRYPT, id='scrypt from werkzeug'),
    ],
)
def test_wrong_password_is_rejected(stored):
    headers = basic_auth(password='wrong')

    assert client_for({'admin': stored}).get('/signal', headers=headers).status_code == 401


@pytest.mark.parametrize(
    'stored',
    [pytest.param(BCRYPT, id='bcrypt'), pytest.param(SCRYPT, id='scrypt')],
)
def test_hash_itself_is_not_a_password(stored):
    """Someone who reads the variable must not be able to log in with what they saw."""
    token = base64.b64encode(f'admin:{stored}'.encode()).decode()
    response = client_for({'admin': stored}).get(
        '/signal', headers={'Authorization': f'Basic {token}'}
    )

    assert response.status_code == 401


@pytest.mark.parametrize('prefix', ['$2a$', '$2b$', '$2y$'])
def test_every_bcrypt_variant_is_recognised(prefix):
    """The variants differ in history, not in the algorithm."""
    stored = prefix + BCRYPT[4:]

    assert password_matches(stored, PLAIN)


def test_mangled_hash_is_refused_without_crashing():
    """A compose file with single dollar signs eats part of the hash."""
    mangled = '$2y$05$9F7kBCq2MTqsnSeh'

    assert not password_matches(mangled, PLAIN)


def test_plain_password_may_contain_a_colon():
    assert password_matches('pa:ss', 'pa:ss')
