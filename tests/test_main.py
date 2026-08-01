"""Checks for the process lifecycle: signals and shutdown."""

from __future__ import annotations

import os
import signal

import pytest

from helpers import FakeModem
from sms_gateway import __main__ as entry_point
from sms_gateway.config import Settings
from sms_gateway.errors import GatewayError


@pytest.fixture
def restore_sigterm():
    """Signal handlers are process-wide, so put the previous one back."""
    previous = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, previous)


def test_sigterm_becomes_a_normal_exit(restore_sigterm):
    """Without a handler PID 1 ignores SIGTERM and docker stop has to kill it."""
    entry_point.install_signal_handlers()

    with pytest.raises(SystemExit) as stop:
        os.kill(os.getpid(), signal.SIGTERM)

    # A requested stop is not a failure, or restart policies would react to it
    assert stop.value.code == 0


def test_plain_http_when_ssl_is_off():
    assert entry_point.ssl_context(Settings(ssl=False)) is None


def test_mounted_certificate_is_used(tmp_path, monkeypatch):
    certificate = tmp_path / 'cert.pem'
    key = tmp_path / 'key.pem'
    certificate.write_text('cert')
    key.write_text('key')
    monkeypatch.setattr(entry_point, 'SSL_CERTIFICATE', (str(certificate), str(key)))

    assert entry_point.ssl_context(Settings(ssl=True)) == (str(certificate), str(key))


@pytest.mark.parametrize('present', ['neither', 'certificate only', 'key only'])
def test_incomplete_certificate_falls_back_to_self_signed(tmp_path, monkeypatch, present):
    """Half a pair is as unusable as none, and refusing to start helps nobody."""
    certificate = tmp_path / 'cert.pem'
    key = tmp_path / 'key.pem'
    if present == 'certificate only':
        certificate.write_text('cert')
    if present == 'key only':
        key.write_text('key')
    monkeypatch.setattr(entry_point, 'SSL_CERTIFICATE', (str(certificate), str(key)))

    assert entry_point.ssl_context(Settings(ssl=True)) == 'adhoc'


def test_unwritable_temp_directory_is_reported_clearly(tmp_path, monkeypatch):
    """A read-only container without tmpfs would otherwise fail deep inside the server."""
    monkeypatch.setattr(
        entry_point, 'SSL_CERTIFICATE', (str(tmp_path / 'cert.pem'), str(tmp_path / 'key.pem'))
    )
    monkeypatch.setattr(
        entry_point.tempfile, 'TemporaryFile', lambda *a, **kw: (_ for _ in ()).throw(
            OSError('No usable temporary directory found')
        )
    )

    with pytest.raises(GatewayError) as failure:
        entry_point.ssl_context(Settings(ssl=True))

    assert 'writable /tmp' in str(failure.value)


def test_modem_is_released_on_shutdown(restore_sigterm, monkeypatch):
    """The serial port must be handed back, or the next start finds it busy."""
    modem = FakeModem([])

    class StoppedServer:
        """Stands in for a server interrupted by a signal."""

        def run(self, **kwargs):
            raise SystemExit('received SIGTERM')

    monkeypatch.setattr(entry_point, 'load_users', lambda filename: {'admin': 'secret'})
    monkeypatch.setattr(entry_point, 'Modem', lambda pin, config_file: modem)
    monkeypatch.setattr(entry_point, 'create_app', lambda modem, users: StoppedServer())

    with pytest.raises(SystemExit):
        entry_point.main()

    assert modem.closed
