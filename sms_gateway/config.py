"""Настройки из переменных окружения и чтение учётных данных."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from sms_gateway.errors import GatewayError

logger = logging.getLogger(__name__)

DEFAULT_GAMMU_CONFIG = 'config/gammu.config'
DEFAULT_CREDENTIALS = 'config/credentials.txt'

# Значения, которые считаются включённым флагом в окружении и параметрах запроса
TRUTHY = frozenset({'1', 'true', 'yes', 'on'})


def as_bool(value: Any) -> bool:
    """Приводит строковый флаг к bool: 'false', '0' и пустое значение выключают его."""
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in TRUTHY


@dataclass(frozen=True)
class Settings:
    """Параметры запуска. Пути к файлам можно переопределить окружением."""

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
    """Читает пары «логин:пароль», по одной на строку.

    Пустые строки и строки, начинающиеся с #, пропускаются.
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
                logger.warning('%s, строка %d: ожидается формат «логин:пароль»', filename, number)
                continue

            users[username] = password

    if not users:
        raise GatewayError(f'{filename}: не найдено ни одной пары «логин:пароль»')

    return users
