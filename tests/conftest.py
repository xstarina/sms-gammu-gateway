"""Фикстуры: HTTP-клиент поверх поддельного модема."""

from __future__ import annotations

import pytest

from helpers import SMS, USERS, FakeModem
from sms_gateway.api import create_app


@pytest.fixture
def make_client():
    """Фабрика клиентов: позволяет задать содержимое ящика и поведение модема."""

    def factory(messages=None, fail=False):
        modem = FakeModem(messages, fail)
        app = create_app(modem, USERS)
        app.config['TESTING'] = True

        client = app.test_client()
        # Модем нужен тестам, чтобы проверять переданные в него параметры
        client.modem = modem
        return client

    return factory


@pytest.fixture
def client(make_client):
    """Клиент с одним сообщением во входящих."""
    return make_client([dict(SMS)])


@pytest.fixture
def empty_client(make_client):
    """Клиент с пустым ящиком."""
    return make_client([])
