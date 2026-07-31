"""Работа с GSM-модемом через Gammu."""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterable

import gammu

from sms_gateway.config import DEFAULT_GAMMU_CONFIG
from sms_gateway.errors import GatewayError

logger = logging.getLogger(__name__)

# Папка 0 в терминах Gammu — входящие сообщения на SIM и в памяти телефона
INBOX_FOLDER = 0


class Modem:
    """Потокобезопасная обёртка над gammu.StateMachine.

    Gammu держит одно соединение с устройством и не рассчитан на параллельные
    обращения, а Flask обслуживает запросы в нескольких потоках. Поэтому каждая
    операция выполняется под общей блокировкой, а составные операции
    (прочитать и удалить) захватывают её один раз целиком.
    """

    def __init__(self, pin: str | None = None, config_file: str = DEFAULT_GAMMU_CONFIG) -> None:
        self._lock = threading.Lock()
        self._machine = gammu.StateMachine()
        self._machine.ReadConfig(Filename=config_file)
        self._machine.Init()
        self._unlock_sim(pin)

    def _unlock_sim(self, pin: str | None) -> None:
        if self._machine.GetSecurityStatus() != 'PIN':
            return
        if not pin:
            raise GatewayError('SIM-карта запрашивает PIN, задайте переменную окружения PIN')
        self._machine.EnterSecurityCode('PIN', pin)
        logger.info('PIN принят')

    def signal_quality(self) -> dict[str, Any]:
        with self._lock:
            return self._machine.GetSignalQuality()

    def network_info(self) -> dict[str, Any]:
        with self._lock:
            info = self._machine.GetNetworkInfo()

        info['NetworkName'] = gammu.GSMNetworks.get(info['NetworkCode'], 'Unknown')
        return info

    def reset(self) -> None:
        """Программный сброс модема без выключения питания."""
        with self._lock:
            self._machine.Reset(False)

    def list_sms(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_all()

    def get_sms(self, index: int) -> dict[str, Any] | None:
        """Сообщение по порядковому номеру в текущем списке или None."""
        with self._lock:
            messages = self._read_all()
            return messages[index] if 0 <= index < len(messages) else None

    def pop_sms(self) -> dict[str, Any] | None:
        """Возвращает первое сообщение и сразу удаляет его из памяти модема."""
        with self._lock:
            messages = self._read_all()
            if not messages:
                return None

            first = messages[0]
            self._delete(first['Locations'])
            return first

    def delete_sms(self, index: int) -> bool:
        """Удаляет сообщение по номеру. False, если такого номера нет."""
        with self._lock:
            messages = self._read_all()
            if not 0 <= index < len(messages):
                return False

            self._delete(messages[index]['Locations'])
            return True

    def send_sms(
        self,
        text: str,
        numbers: Iterable[str],
        smsc: str | None = None,
        unicode: bool = False,
    ) -> list[int]:
        """Отправляет текст на каждый номер, возвращает ссылки отправленных частей.

        Длинный текст Gammu сам разбивает на несколько частей, каждая уходит
        отдельным сообщением.
        """
        message_info = {
            'Class': -1,
            'Unicode': unicode,
            'Entries': [{'ID': 'ConcatenatedTextLong', 'Buffer': text}],
        }
        # Без явного номера SMS-центра берётся тот, что записан на SIM
        smsc_info = {'Number': smsc} if smsc else {'Location': 1}
        parts = gammu.EncodeSMS(message_info)

        references = []
        with self._lock:
            for number in numbers:
                for part in parts:
                    part = dict(part, SMSC=dict(smsc_info), Number=number)
                    references.append(self._machine.SendSMS(part))

        return references

    def _read_all(self) -> list[dict[str, Any]]:
        """Читает входящие целиком. Вызывать только при захваченной блокировке."""
        raw_parts = []
        current = None

        # Модем отдаёт сообщения по одной части за вызов и сигнализирует
        # о конце списка исключением ERR_EMPTY
        while True:
            try:
                if current is None:
                    current = self._machine.GetNextSMS(Folder=INBOX_FOLDER, Start=True)
                else:
                    current = self._machine.GetNextSMS(
                        Folder=INBOX_FOLDER, Location=current[0]['Location']
                    )
            except gammu.ERR_EMPTY:
                break

            raw_parts.append(current)

        # LinkSMS собирает части многочастных сообщений в одно
        return [self._decode(parts) for parts in gammu.LinkSMS(raw_parts)]

    def _delete(self, locations: Iterable[int]) -> None:
        """Удаляет все части сообщения. Вызывать только при захваченной блокировке."""
        for location in locations:
            self._machine.DeleteSMS(Folder=INBOX_FOLDER, Location=location)

    @staticmethod
    def _decode(parts: list[dict[str, Any]]) -> dict[str, Any]:
        """Собирает из частей сообщения плоский словарь с текстом."""
        head = parts[0]
        decoded = gammu.DecodeSMS(parts)

        if decoded is None:
            text = head['Text']
        else:
            text = ''.join(
                entry['Buffer'] for entry in decoded['Entries'] if entry.get('Buffer')
            )

        return {
            'Date': str(head['DateTime']),
            'Number': head['Number'],
            'State': head['State'],
            'Text': text,
            # Адреса частей в памяти модема, нужны только для удаления
            'Locations': [part['Location'] for part in parts],
        }
