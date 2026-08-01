"""Checks for the modem watchdog."""

from __future__ import annotations

import gammu
import pytest

from sms_gateway.watchdog import Watchdog


class SilentModem:
    """Modem that fails a given number of probes, then answers again."""

    def __init__(self, failures: int = 0, reconnect_fails: bool = False) -> None:
        self.remaining_failures = failures
        self.reconnect_fails = reconnect_fails
        self.probes = 0
        self.reconnects = 0

    def probe(self) -> None:
        self.probes += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise gammu.ERR_TIMEOUT('no answer')

    def reconnect(self) -> None:
        self.reconnects += 1
        if self.reconnect_fails:
            raise gammu.ERR_DEVICEOPENERROR('device is gone')
        self.remaining_failures = 0


def run_checks(watchdog: Watchdog, times: int) -> None:
    for _ in range(times):
        watchdog.check()


def test_healthy_modem_is_left_alone():
    modem = SilentModem()
    watchdog = Watchdog(modem, failures=3)

    run_checks(watchdog, 5)

    assert modem.probes == 5
    assert modem.reconnects == 0


def test_single_failures_do_not_trigger_recovery():
    """One missed answer is normal — the modem may be busy sending an SMS."""
    modem = SilentModem(failures=1)
    watchdog = Watchdog(modem, failures=3)

    run_checks(watchdog, 3)

    assert modem.reconnects == 0


def test_session_is_rebuilt_after_consecutive_failures():
    modem = SilentModem(failures=3)
    watchdog = Watchdog(modem, failures=3)

    run_checks(watchdog, 3)

    assert modem.reconnects == 1


def test_counter_resets_after_a_successful_probe():
    """Failures must be consecutive, otherwise rare glitches would add up."""
    modem = SilentModem(failures=2)
    watchdog = Watchdog(modem, failures=3)

    run_checks(watchdog, 3)          # fail, fail, success
    modem.remaining_failures = 2
    run_checks(watchdog, 2)          # fail, fail — still short of three in a row

    assert modem.reconnects == 0


def test_process_gives_up_when_reconnect_fails():
    """A device that cannot be reopened is a case for a container restart."""
    modem = SilentModem(failures=5, reconnect_fails=True)
    given_up = []
    watchdog = Watchdog(modem, failures=2, on_lost=lambda: given_up.append(True))

    run_checks(watchdog, 2)

    assert modem.reconnects == 1
    assert given_up == [True]


def test_recovery_is_not_repeated_while_the_modem_answers():
    modem = SilentModem(failures=2)
    watchdog = Watchdog(modem, failures=2)

    run_checks(watchdog, 6)

    assert modem.reconnects == 1


@pytest.mark.parametrize('interval', [0, -1])
def test_zero_interval_disables_the_watchdog(interval):
    modem = SilentModem()
    watchdog = Watchdog(modem, interval=interval)

    watchdog.start()

    assert watchdog._thread is None
