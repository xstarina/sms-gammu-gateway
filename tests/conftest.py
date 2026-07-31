"""Fixtures: an HTTP client backed by a fake modem."""

from __future__ import annotations

import pytest

from helpers import SMS, USERS, FakeModem
from sms_gateway.api import create_app


@pytest.fixture
def make_client():
    """Client factory: lets a test choose the inbox contents and modem behaviour."""

    def factory(messages=None, fail=False):
        modem = FakeModem(messages, fail)
        app = create_app(modem, USERS)
        app.config['TESTING'] = True

        client = app.test_client()
        # Tests need the modem to assert on the parameters passed to it
        client.modem = modem
        return client

    return factory


@pytest.fixture
def client(make_client):
    """Client with a single message in the inbox."""
    return make_client([dict(SMS)])


@pytest.fixture
def empty_client(make_client):
    """Client with an empty inbox."""
    return make_client([])
