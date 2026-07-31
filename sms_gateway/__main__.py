"""Entry point: wire the application together and start the HTTP server."""

from __future__ import annotations

import logging

import gammu

from sms_gateway.api import create_app
from sms_gateway.config import Settings, load_users
from sms_gateway.errors import GatewayError
from sms_gateway.modem import Modem

logger = logging.getLogger(__name__)

# Paths where the application expects the key and the certificate when SSL is on
SSL_CERTIFICATE = ('/ssl/cert.pem', '/ssl/key.pem')


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    settings = Settings.from_env()

    try:
        users = load_users(settings.credentials_file)
        modem = Modem(pin=settings.pin, config_file=settings.gammu_config)
    except (OSError, GatewayError, gammu.GSMError) as error:
        logger.error('Failed to start the gateway: %s', error)
        raise SystemExit(1) from error

    app = create_app(modem, users)
    # Listen on every interface: only the published port is reachable from outside
    app.run(
        host='0.0.0.0',
        port=settings.port,
        ssl_context=SSL_CERTIFICATE if settings.ssl else None,
    )


if __name__ == '__main__':
    main()
