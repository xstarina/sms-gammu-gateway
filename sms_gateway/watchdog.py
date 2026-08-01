"""Background check that keeps the modem session usable."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol

import gammu

logger = logging.getLogger(__name__)


class Recoverable(Protocol):
    """The part of the modem interface the watchdog relies on."""

    def probe(self) -> None: ...

    def reconnect(self) -> None: ...


class Watchdog:
    """Polls the modem and rebuilds the session when it stops answering.

    A wedged modem rarely reports an error, it simply goes quiet, so the only
    dependable symptom is a probe that keeps failing. Single failures are
    expected — the modem can be busy with an SMS — which is why recovery starts
    only after `failures` of them in a row.

    Loss of network registration is deliberately not treated as a fault: no
    amount of restarting brings a cell tower back, and reacting to it would turn
    weak signal into a restart loop.
    """

    def __init__(
        self,
        modem: Recoverable,
        interval: float = 60.0,
        failures: int = 3,
        on_lost: Callable[[], None] | None = None,
    ) -> None:
        self._modem = modem
        self._interval = interval
        self._max_failures = max(1, failures)
        self._on_lost = on_lost
        self._failures = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._interval <= 0:
            logger.info('Watchdog disabled')
            return

        logger.info(
            'Watchdog every %.0fs, recovering after %d failures in a row',
            self._interval,
            self._max_failures,
        )
        self._thread = threading.Thread(target=self._loop, name='watchdog', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # wait() doubles as the sleep and as the stop signal, so shutdown is immediate
        while not self._stop.wait(self._interval):
            self.check()

    def check(self) -> None:
        """One probe with its consequences. Public so tests can drive it directly."""
        try:
            self._modem.probe()
        except gammu.GSMError as error:
            self._failures += 1
            logger.warning(
                'Modem did not answer (%d of %d): %s', self._failures, self._max_failures, error
            )
            if self._failures >= self._max_failures:
                self._recover()
            return

        if self._failures:
            logger.info('Modem answers again')
        self._failures = 0

    def _recover(self) -> None:
        logger.error('Modem is unresponsive, rebuilding the session')
        try:
            self._modem.reconnect()
        except Exception as error:
            logger.critical('Could not reopen the modem: %s', error)
            if self._on_lost:
                self._on_lost()
            return

        self._failures = 0
        logger.info('Modem session rebuilt')
