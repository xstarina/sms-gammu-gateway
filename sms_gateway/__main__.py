"""Entry point: wire the application together and start the HTTP server."""

from __future__ import annotations

import logging
import os
import signal
import tempfile
from types import FrameType

import gammu

from sms_gateway.api import create_app
from sms_gateway.config import Settings
from sms_gateway.errors import GatewayError
from sms_gateway.modem import Modem
from sms_gateway.watchdog import Watchdog

logger = logging.getLogger(__name__)

# Paths where the application expects the key and the certificate when SSL is on
SSL_CERTIFICATE = ('/ssl/cert.pem', '/ssl/key.pem')


def _shutdown(signum: int, _frame: FrameType | None) -> None:
    logger.info('Received %s', signal.Signals(signum).name)
    # Exit code zero: a requested stop is not a failure, and restart policies
    # such as on-failure would otherwise bring the container straight back
    raise SystemExit(0)


def _require_writable_temp(directory: str) -> None:
    """A generated certificate is handed to the server through a temporary file."""
    try:
        with tempfile.TemporaryFile():
            pass
    except OSError as error:
        raise GatewayError(
            f'SSL is on, {directory} holds no certificate, and a self-signed one cannot be '
            f'generated without a writable temporary directory ({error}). Mount a certificate '
            f'into {directory}, or give the container a writable /tmp.'
        ) from error


def ssl_context(settings: Settings) -> tuple[str, str] | str | None:
    """Pick what to serve HTTPS with, or None for plain HTTP.

    A missing certificate is not a reason to refuse to start: the server falls
    back to one generated at startup. Nothing is written to the image, but the
    certificate does pass through a temporary file on its way to the server.
    """
    if not settings.ssl:
        return None

    certificate, key = SSL_CERTIFICATE
    if os.path.isfile(certificate) and os.path.isfile(key):
        return SSL_CERTIFICATE

    directory = os.path.dirname(certificate)
    _require_writable_temp(directory)
    logger.warning(
        'No certificate in %s, generating a self-signed one. It changes on every '
        'restart and no client will trust it: mount a real certificate for anything '
        'beyond a trusted network.',
        directory,
    )
    return 'adhoc'


def _give_up() -> None:
    """Leave with a failure code so the restart policy brings the container back.

    Called from the watchdog thread, where raising would only kill that thread,
    so the process is ended directly.
    """
    logger.critical('Modem cannot be reached, exiting for a restart')
    os._exit(1)


def install_signal_handlers() -> None:
    """Turn SIGTERM into a normal exit.

    The application is PID 1 in the container, and the kernel does not apply
    default signal dispositions to PID 1. Without an explicit handler SIGTERM is
    ignored, `docker stop` waits out its timeout and kills the process, which is
    why a restart used to take ten seconds and end with exit code 137.
    """
    signal.signal(signal.SIGTERM, _shutdown)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    try:
        # Everything that can be judged without touching the device is judged
        # first: a typo in the environment should not cost a round trip to a modem
        settings = Settings.from_env()
        context = ssl_context(settings)
        modem = Modem(pin=settings.pin, config_file=settings.gammu_config)
    except (OSError, ValueError, GatewayError, gammu.GSMError) as error:
        logger.error('Failed to start the gateway: %s', error)
        raise SystemExit(1) from error

    app = create_app(modem, settings.users, settings.allowed_networks)
    install_signal_handlers()

    watchdog = Watchdog(
        modem,
        interval=settings.watchdog_interval,
        failures=settings.watchdog_failures,
        on_lost=_give_up,
    )
    watchdog.start()

    try:
        # Listen on every interface: only the published port is reachable from outside
        app.run(
            host='0.0.0.0',
            port=settings.port,
            ssl_context=context,
        )
    finally:
        watchdog.stop()
        # Hand the serial port back, so the next start does not find it busy
        logger.info('Shutting down')
        modem.close()


if __name__ == '__main__':
    main()
