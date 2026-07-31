"""Shared test data and doubles."""

from __future__ import annotations

import base64
from typing import Any

import gammu

USERS = {'admin': 'secret'}

# The text is deliberately Cyrillic: it exercises the non-Latin path end to end
SMS = {
    'Date': '2026-01-01 12:00:00',
    'Number': '+79001234567',
    'State': 'UnRead',
    'Text': 'привет',
    'Locations': [1, 2],
}


def basic_auth(username: str = 'admin', password: str = 'secret') -> dict[str, str]:
    token = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {token}'}


AUTH = basic_auth()


class FakeModem:
    """Stand-in for the device.

    Mirrors the interface of sms_gateway.modem.Modem, keeps the inbox in a list
    and records sent messages. With fail=True every call simulates a modem error.
    """

    def __init__(self, messages: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.messages = list(messages or [])
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    def _check(self) -> None:
        if self.fail:
            raise gammu.ERR_TIMEOUT('device timeout')

    def list_sms(self) -> list[dict[str, Any]]:
        self._check()
        return list(self.messages)

    def get_sms(self, index: int) -> dict[str, Any] | None:
        self._check()
        return self.messages[index] if 0 <= index < len(self.messages) else None

    def pop_sms(self) -> dict[str, Any] | None:
        self._check()
        return self.messages.pop(0) if self.messages else None

    def delete_sms(self, index: int) -> bool:
        self._check()
        if not 0 <= index < len(self.messages):
            return False

        self.messages.pop(index)
        return True

    def send_sms(self, text, numbers, smsc=None, unicode=False) -> list[int]:
        self._check()
        self.sent.append(
            {'text': text, 'numbers': list(numbers), 'smsc': smsc, 'unicode': unicode}
        )
        return [1, 2]

    def signal_quality(self) -> dict[str, Any]:
        self._check()
        return {'SignalPercent': 75, 'SignalStrength': -60}

    def network_info(self) -> dict[str, Any]:
        self._check()
        return {'NetworkCode': '250 01', 'NetworkName': 'MTS'}

    def reset(self) -> None:
        self._check()
