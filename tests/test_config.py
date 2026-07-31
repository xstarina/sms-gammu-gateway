"""Checks for environment settings and credentials file parsing."""

from __future__ import annotations

import pytest

from sms_gateway.config import (
    DEFAULT_CREDENTIALS,
    DEFAULT_GAMMU_CONFIG,
    Settings,
    as_bool,
    load_users,
)
from sms_gateway.errors import GatewayError

ENV_VARS = ('PORT', 'PIN', 'SSL', 'GAMMU_CONFIG', 'CREDENTIALS_FILE')


@pytest.fixture
def clean_env(monkeypatch):
    """Environment without gateway variables, so tests do not depend on the machine."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_credentials(tmp_path, content: str) -> str:
    path = tmp_path / 'credentials.txt'
    path.write_text(content, encoding='utf-8')
    return str(path)


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


def test_settings_defaults(clean_env):
    settings = Settings.from_env()

    assert settings.port == 5000
    assert settings.pin is None
    assert settings.ssl is False
    assert settings.gammu_config == DEFAULT_GAMMU_CONFIG
    assert settings.credentials_file == DEFAULT_CREDENTIALS


def test_settings_read_from_env(clean_env, monkeypatch):
    monkeypatch.setenv('PORT', '8080')
    monkeypatch.setenv('PIN', '1234')
    monkeypatch.setenv('SSL', 'yes')
    monkeypatch.setenv('GAMMU_CONFIG', '/etc/gammu.conf')
    monkeypatch.setenv('CREDENTIALS_FILE', '/run/secrets/users')

    settings = Settings.from_env()

    assert settings.port == 8080
    assert settings.pin == '1234'
    assert settings.ssl is True
    assert settings.gammu_config == '/etc/gammu.conf'
    assert settings.credentials_file == '/run/secrets/users'


def test_empty_pin_treated_as_missing(clean_env, monkeypatch):
    """An empty variable means "not set", otherwise the modem gets an empty code."""
    monkeypatch.setenv('PIN', '')

    assert Settings.from_env().pin is None


def test_parses_pairs(tmp_path):
    path = write_credentials(tmp_path, 'admin:secret\nuser:pass\n')

    assert load_users(path) == {'admin': 'secret', 'user': 'pass'}


def test_trims_spaces_around_pair(tmp_path):
    """Spaces around the separator appear in real files and must not reach the password."""
    path = write_credentials(tmp_path, '  admin : secret  \n')

    assert load_users(path) == {'admin': 'secret'}


def test_password_may_contain_colon(tmp_path):
    path = write_credentials(tmp_path, 'admin:se:cret\n')

    assert load_users(path) == {'admin': 'se:cret'}


def test_skips_blank_and_comment_lines(tmp_path):
    path = write_credentials(tmp_path, '# main user\n\nadmin:secret\n\n')

    assert load_users(path) == {'admin': 'secret'}


@pytest.mark.parametrize(
    'line',
    [
        pytest.param('admin\n', id='no separator'),
        pytest.param(':secret\n', id='no username'),
        pytest.param('admin:\n', id='no password'),
    ],
)
def test_skips_malformed_lines(tmp_path, line):
    path = write_credentials(tmp_path, f'{line}user:pass\n')

    assert load_users(path) == {'user': 'pass'}


def test_requires_at_least_one_pair(tmp_path):
    """An empty file is a configuration error: otherwise the service starts with no access."""
    path = write_credentials(tmp_path, '# comment only\n')

    with pytest.raises(GatewayError):
        load_users(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_users(str(tmp_path / 'no-such-file.txt'))
