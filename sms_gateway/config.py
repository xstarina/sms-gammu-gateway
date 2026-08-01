"""Settings taken from environment variables."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from sms_gateway.errors import GatewayError

logger = logging.getLogger(__name__)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# Baked into the image; mount your own over it only if the defaults do not fit
DEFAULT_GAMMU_CONFIG = 'config/gammu.config'

# Seconds between modem probes, and how many failures in a row mean it is wedged.
# Zero as the interval turns the watchdog off.
DEFAULT_WATCHDOG_INTERVAL = 60.0
DEFAULT_WATCHDOG_FAILURES = 3

# Values treated as an enabled flag in the environment and in request parameters
TRUTHY = frozenset({'1', 'true', 'yes', 'on'})

# Commas and whitespace both separate list entries, so a compose block scalar
# with one entry per line works as well as a single inline string
SEPARATORS = re.compile(r'[,\s]+')


def as_bool(value: Any) -> bool:
    """Coerce a string flag to bool: 'false', '0' and an empty value turn it off."""
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in TRUTHY


def parse_users(raw: str) -> dict[str, str]:
    """Read 'login:password' pairs from the USERS variable.

    Credentials are the one thing the gateway cannot guess, so anything short of a
    usable pair is a startup error rather than a warning. Passwords may contain
    colons; only the first one separates.
    """
    users: dict[str, str] = {}

    for entry in SEPARATORS.split(raw.strip() if raw else ''):
        if not entry:
            continue

        login, separator, password = entry.partition(':')
        if not separator or not login or not password:
            raise GatewayError(
                f'USERS: expected login:password pairs separated by commas, got {entry!r}'
            )

        users[login] = password

    if not users:
        raise GatewayError(
            'USERS is empty or unset: set it to at least one login:password pair, '
            'for example USERS=admin:your-password'
        )

    return users


def parse_networks(raw: str) -> tuple[Network, ...]:
    """Read addresses and subnets from the ALLOWED_NETWORKS variable.

    Unparsable entries are skipped with a warning rather than refusing to start:
    a typo here must not take a working gateway down. An empty result means no
    restriction at all, which is also what an unset variable gives.
    """
    networks: list[Network] = []

    for entry in SEPARATORS.split(raw.strip() if raw else ''):
        if not entry:
            continue

        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(
                'ALLOWED_NETWORKS: %r is not an address or a subnet, ignoring it', entry
            )

    return tuple(networks)


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Everything arrives through the environment."""

    port: int = 5000
    pin: str | None = None
    ssl: bool = False
    gammu_config: str = DEFAULT_GAMMU_CONFIG
    users: dict[str, str] = field(default_factory=dict)
    allowed_networks: tuple[Network, ...] = ()
    watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL
    watchdog_failures: int = DEFAULT_WATCHDOG_FAILURES

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            port=int(os.getenv('PORT', '5000')),
            pin=os.getenv('PIN') or None,
            ssl=as_bool(os.getenv('SSL')),
            gammu_config=os.getenv('GAMMU_CONFIG', DEFAULT_GAMMU_CONFIG),
            users=parse_users(os.getenv('USERS', '')),
            allowed_networks=parse_networks(os.getenv('ALLOWED_NETWORKS', '')),
            watchdog_interval=float(
                os.getenv('WATCHDOG_INTERVAL', str(DEFAULT_WATCHDOG_INTERVAL))
            ),
            watchdog_failures=int(
                os.getenv('WATCHDOG_FAILURES', str(DEFAULT_WATCHDOG_FAILURES))
            ),
        )
