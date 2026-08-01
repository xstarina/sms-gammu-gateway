"""Checks for settings taken from the environment."""

from __future__ import annotations

import ipaddress

import pytest

from sms_gateway.config import (
    DEFAULT_GAMMU_CONFIG,
    Settings,
    as_bool,
    parse_networks,
    parse_users,
)
from sms_gateway.errors import GatewayError

ENV_VARS = (
    'PORT',
    'PIN',
    'SSL',
    'GAMMU_CONFIG',
    'USERS',
    'ALLOWED_NETWORKS',
    'WATCHDOG_INTERVAL',
    'WATCHDOG_FAILURES',
)


@pytest.fixture
def clean_env(monkeypatch):
    """Environment without gateway variables, so tests do not depend on the machine."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    'value, expected',
    [
        ('1', True),
        ('true', True),
        ('True', True),
        ('YES', True),
        ('on', True),
        ('false', False),
        ('0', False),
        ('', False),
        (None, False),
        (True, True),
    ],
)
def test_as_bool(value, expected):
    assert as_bool(value) is expected


def test_settings_defaults(clean_env, monkeypatch):
    monkeypatch.setenv('USERS', 'admin:secret')

    settings = Settings.from_env()

    assert settings.port == 5000
    assert settings.pin is None
    assert settings.ssl is False
    assert settings.gammu_config == DEFAULT_GAMMU_CONFIG
    assert settings.allowed_networks == ()


def test_settings_read_from_env(clean_env, monkeypatch):
    monkeypatch.setenv('PORT', '8080')
    monkeypatch.setenv('PIN', '1234')
    monkeypatch.setenv('SSL', 'yes')
    monkeypatch.setenv('GAMMU_CONFIG', '/etc/gammu.conf')
    monkeypatch.setenv('USERS', 'admin:secret')
    monkeypatch.setenv('ALLOWED_NETWORKS', '10.0.0.0/8')

    settings = Settings.from_env()

    assert settings.port == 8080
    assert settings.pin == '1234'
    assert settings.ssl is True
    assert settings.gammu_config == '/etc/gammu.conf'
    assert settings.users == {'admin': 'secret'}
    assert settings.allowed_networks == (ipaddress.ip_network('10.0.0.0/8'),)


def test_empty_pin_treated_as_missing(clean_env, monkeypatch):
    """An empty variable means "not set", otherwise the modem gets an empty code."""
    monkeypatch.setenv('USERS', 'admin:secret')
    monkeypatch.setenv('PIN', '')

    assert Settings.from_env().pin is None


def test_parses_one_pair():
    assert parse_users('admin:secret') == {'admin': 'secret'}


@pytest.mark.parametrize(
    'raw',
    [
        pytest.param('admin:secret,user:pass', id='commas'),
        pytest.param('admin:secret user:pass', id='spaces'),
        pytest.param('admin:secret\nuser:pass\n', id='newlines'),
    ],
)
def test_separators_between_pairs(raw):
    """Compose can pass a block scalar with one pair per line just as well."""
    assert parse_users(raw) == {'admin': 'secret', 'user': 'pass'}


def test_password_may_contain_colon():
    assert parse_users('admin:se:cret') == {'admin': 'se:cret'}


@pytest.mark.parametrize(
    'raw',
    [
        pytest.param('', id='empty'),
        pytest.param('   ', id='blank'),
        pytest.param('admin', id='no separator'),
        pytest.param(':secret', id='no login'),
        pytest.param('admin:', id='no password'),
        pytest.param('admin:secret,broken', id='one pair of two broken'),
    ],
)
def test_unusable_credentials_stop_the_gateway(raw):
    """Credentials cannot be guessed, so anything unusable is a startup error."""
    with pytest.raises(GatewayError):
        parse_users(raw)


@pytest.mark.parametrize(
    'raw, expected',
    [
        pytest.param('192.168.1.10', ['192.168.1.10/32'], id='single address'),
        pytest.param('10.0.0.0/8', ['10.0.0.0/8'], id='subnet'),
        pytest.param('10.0.0.0/8,192.168.1.10', ['10.0.0.0/8', '192.168.1.10/32'], id='both'),
        pytest.param('10.0.0.0/8 192.168.0.0/16', ['10.0.0.0/8', '192.168.0.0/16'], id='spaces'),
        pytest.param('2001:db8::/32', ['2001:db8::/32'], id='ipv6'),
        pytest.param('192.168.1.42/24', ['192.168.1.0/24'], id='host bits are trimmed'),
    ],
)
def test_parses_networks(raw, expected):
    assert parse_networks(raw) == tuple(ipaddress.ip_network(item) for item in expected)


def test_unset_variable_leaves_access_open():
    """Not asking for a whitelist is a valid answer; a broken one is not."""
    assert parse_networks('') == ()


@pytest.mark.parametrize(
    'raw',
    [
        pytest.param('not-an-address', id='nonsense'),
        pytest.param('999.1.1.1', id='out of range'),
        pytest.param('10.0.0.0/8,nonsense', id='one entry of two broken'),
        pytest.param('10.0.0.0/64', id='impossible prefix'),
    ],
)
def test_unusable_networks_stop_the_gateway(raw):
    """Skipping the entry would silently expose the API the whitelist was meant to close."""
    with pytest.raises(GatewayError):
        parse_networks(raw)
