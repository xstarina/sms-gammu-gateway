"""Checks for the process lifecycle: signals and shutdown."""

from __future__ import annotations

import os
import signal

import pytest

from helpers import FakeModem
from sms_gateway import __main__ as entry_point


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
