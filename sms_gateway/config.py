"""Settings from environment variables and credentials loading."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from sms_gateway.errors import GatewayError

logger = logging.getLogger(__name__)

DEFAULT_GAMMU_CONFIG = 'config/gammu.config'
DEFAULT_CREDENTIALS = 'config/credentials.txt'

# Values treated as an enabled flag in the environment and in request parameters
TRUTHY = frozenset({'1', 'true', 'yes', 'on'})


def as_bool(value: Any) -> bool:
    """Coerce a string flag to bool: 'false', '0' and an empty value turn it off."""
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in TRUTHY


@dataclass(frozen=True)
class Settings:
    """Runtime settings. File paths can be overridden through the environment."""

    port: int = 5000
    pin: str | None = None
    ssl: bool = False
    gammu_config: str = DEFAULT_GAMMU_CONFIG
    credentials_file: str = DEFAULT_CREDENTIALS

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            port=int(os.getenv('PORT', '5000')),
            pin=os.getenv('PIN') or None,
            ssl=as_bool(os.getenv('SSL')),
            gammu_config=os.getenv('GAMMU_CONFIG', DEFAULT_GAMMU_CONFIG),
            credentials_file=os.getenv('CREDENTIALS_FILE', DEFAULT_CREDENTIALS),
        )


def load_users(filename: str = DEFAULT_CREDENTIALS) -> dict[str, str]:
    """Read 'username:password' pairs, one per line.

    Blank lines and lines starting with # are skipped.
    """
    users: dict[str, str] = {}

    with open(filename, encoding='utf-8') as credentials:
        for number, line in enumerate(credentials, start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            username, separator, password = line.partition(':')
            username, password = username.strip(), password.strip()
            if not separator or not username or not password:
                logger.warning('%s, line %d: expected the format "username:password"', filename, number)
                continue

            users[username] = password

    if not users:
        raise GatewayError(f'{filename}: no "username:password" pair found')

    return users
