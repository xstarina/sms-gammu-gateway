"""GSM modem access through Gammu."""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterable

import gammu

from sms_gateway.config import DEFAULT_GAMMU_CONFIG
from sms_gateway.errors import GatewayError

logger = logging.getLogger(__name__)

# Folder 0 in Gammu terms is the inbox on the SIM and in phone memory
INBOX_FOLDER = 0


class Modem:
    """Thread-safe wrapper around gammu.StateMachine.

    Gammu keeps a single connection to the device and is not meant for
    concurrent access, while Flask serves requests in several threads. Every
    operation therefore runs under a shared lock, and compound operations
    (read then delete) hold that lock for the whole sequence.
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
            raise GatewayError('SIM card asks for a PIN, set the PIN environment variable')
        self._machine.EnterSecurityCode('PIN', pin)
        logger.info('PIN accepted')

    def close(self) -> None:
        """Release the serial port. Safe to call more than once."""
        with self._lock:
            try:
                self._machine.Terminate()
            except gammu.GSMError as error:
                # Shutdown must not fail because a dead modem refuses to say goodbye
                logger.warning('Modem did not close cleanly: %s', error)

    def signal_quality(self) -> dict[str, Any]:
        with self._lock:
            return self._machine.GetSignalQuality()

    def network_info(self) -> dict[str, Any]:
        with self._lock:
            info = self._machine.GetNetworkInfo()

        info['NetworkName'] = gammu.GSMNetworks.get(info['NetworkCode'], 'Unknown')
        return info

    def reset(self) -> None:
        """Soft-reset the modem without cutting power."""
        with self._lock:
            self._machine.Reset(False)

    def list_sms(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_all()

    def get_sms(self, index: int) -> dict[str, Any] | None:
        """Return the message at the given position, or None if there is none."""
        with self._lock:
            messages = self._read_all()
            return messages[index] if 0 <= index < len(messages) else None

    def pop_sms(self) -> dict[str, Any] | None:
        """Return the first message and delete it from modem memory."""
        with self._lock:
            messages = self._read_all()
            if not messages:
                return None

            first = messages[0]
            self._delete(first['Locations'])
            return first

    def delete_sms(self, index: int) -> bool:
        """Delete the message at the given position. False if there is none."""
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
        """Send the text to every number, returning the references of sent parts.

        Gammu splits long text into several parts on its own, and each part is
        sent as a separate message.
        """
        message_info = {
            'Class': -1,
            'Unicode': unicode,
            'Entries': [{'ID': 'ConcatenatedTextLong', 'Buffer': text}],
        }
        # Without an explicit SMS centre number the one stored on the SIM is used
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
        """Read the whole inbox. Call only while holding the lock."""
        raw_parts = []
        current = None

        # The modem returns one part per call and signals the end of the list
        # by raising ERR_EMPTY
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

        # LinkSMS joins the parts of multipart messages back together
        return [self._decode(parts) for parts in gammu.LinkSMS(raw_parts)]

    def _delete(self, locations: Iterable[int]) -> None:
        """Delete every part of a message. Call only while holding the lock."""
        for location in locations:
            self._machine.DeleteSMS(Folder=INBOX_FOLDER, Location=location)

    @staticmethod
    def _decode(parts: list[dict[str, Any]]) -> dict[str, Any]:
        """Flatten the parts of a message into a single dict with its text."""
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
            # Addresses of the parts in modem memory, needed only for deletion
            'Locations': [part['Location'] for part in parts],
        }
