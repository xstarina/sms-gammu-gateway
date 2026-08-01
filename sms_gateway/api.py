"""HTTP resources of the gateway and the Flask application factory."""

from __future__ import annotations

import hmac
import ipaddress
import logging
from functools import wraps
from typing import Any, Callable

import gammu
from flask import Flask, current_app, request
from flask_httpauth import HTTPBasicAuth
from flask_restful import Api, Resource, abort
from werkzeug.security import check_password_hash

from sms_gateway.config import Network, as_bool
from sms_gateway.modem import Modem

logger = logging.getLogger(__name__)
auth = HTTPBasicAuth()

# Werkzeug puts the algorithm in front of the hash, which is what distinguishes a
# hashed password from one written in the clear
HASH_PREFIXES = ('scrypt:', 'pbkdf2:')

# Reply for an empty inbox: same structure, empty fields
EMPTY_SMS = {'Date': '', 'Number': '', 'State': '', 'Text': ''}


def password_matches(expected: str, given: str) -> bool:
    """Compare against a stored password, hashed or plain.

    Both branches take the same time whatever the input, so neither a plain
    password nor a hash can be guessed from how long the answer took.
    """
    if expected.startswith(HASH_PREFIXES):
        return check_password_hash(expected, given)
    return hmac.compare_digest(expected, given)


@auth.verify_password
def verify_password(username: str, password: str) -> str | None:
    expected = current_app.config['USERS'].get(username)
    if not expected or not password:
        return None

    if not password_matches(expected, password):
        return None

    return username


@auth.error_handler
def unauthorized() -> tuple[dict[str, str], int]:
    return {'message': 'Unauthorized access'}, 401


def handle_gsm_errors(func: Callable) -> Callable:
    """Return 502 instead of a traceback when the modem fails or does not answer."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except gammu.GSMError as error:
            # flask-restful logs the traceback for 5xx itself, the cause matters here
            logger.warning('Modem error: %s', error)
            message = f'Modem error: {error}'

        # abort outside the except block, otherwise the log gets a chained traceback
        abort(502, message=message)

    return wrapper


def request_params() -> Any:
    """Request parameters from JSON, form data or the query string, in that order."""
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return request.form if request.form else request.args


def split_numbers(raw: Any) -> list[str]:
    """Recipient numbers: several of them can be listed in one request, comma separated."""
    if not raw:
        return []
    return [number.strip() for number in str(raw).split(',') if number.strip()]


def public_view(sms: dict[str, Any]) -> dict[str, Any]:
    """Locations are internal addresses in modem memory and are never exposed."""
    return {key: value for key, value in sms.items() if key != 'Locations'}


class ModemResource(Resource):
    """Base resource: authentication required, modem errors kept inside.

    Decorators apply in reverse order, so login_required ends up outermost and
    rejects the request before the device is touched.
    """

    method_decorators = [handle_gsm_errors, auth.login_required]

    def __init__(self, modem: Modem) -> None:
        self.modem = modem


class SmsList(ModemResource):
    """All incoming messages, and sending new ones."""

    def get(self) -> list[dict[str, Any]]:
        return [public_view(sms) for sms in self.modem.list_sms()]

    def post(self) -> tuple[dict[str, Any], int]:
        params = request_params()
        text = params.get('text')
        numbers = split_numbers(params.get('number'))

        if not text or not numbers:
            abort(400, message="Parameters 'text' and 'number' are required.")

        references = self.modem.send_sms(
            text=text,
            numbers=numbers,
            smsc=params.get('smsc'),
            unicode=as_bool(params.get('unicode')),
        )
        return {'status': 200, 'message': str(references)}, 200


class SmsItem(ModemResource):
    """A message addressed by its position in the current list."""

    def get(self, sms_id: int) -> dict[str, Any]:
        sms = self.modem.get_sms(sms_id)
        if sms is None:
            abort(404, message=f"Sms with id '{sms_id}' not found")

        return public_view(sms)

    def delete(self, sms_id: int) -> tuple[str, int]:
        if not self.modem.delete_sms(sms_id):
            abort(404, message=f"Sms with id '{sms_id}' not found")

        return '', 204


class SmsInbox(ModemResource):
    """Takes the first message and deletes it from modem memory."""

    def get(self) -> dict[str, Any]:
        sms = self.modem.pop_sms()
        return EMPTY_SMS if sms is None else public_view(sms)


class Signal(ModemResource):
    """Signal quality."""

    def get(self) -> dict[str, Any]:
        return self.modem.signal_quality()


class Network(ModemResource):
    """Operator network information."""

    def get(self) -> dict[str, Any]:
        return self.modem.network_info()


class Reset(ModemResource):
    """Soft reset of the modem."""

    def get(self) -> tuple[dict[str, Any], int]:
        self.modem.reset()
        return {'status': 200, 'message': 'Reset done'}, 200


def reject_foreign_addresses(networks: tuple[Network, ...]) -> Callable[[], None]:
    """Refuse anything coming from outside the listed addresses and subnets.

    Runs before authentication, so a stranger never gets as far as guessing a
    password. The check uses the peer address as seen by the server: behind a
    reverse proxy that is the proxy itself, and trusting a forwarded header
    instead would let anyone claim any address.
    """

    def check() -> None:
        try:
            address = ipaddress.ip_address(request.remote_addr or '')
        except ValueError:
            logger.warning('Rejected a request from an unreadable address')
            abort(403, message='Access denied')

        if not any(address in network for network in networks):
            logger.warning('Rejected a request from %s', address)
            abort(403, message='Access denied')

    return check


def create_app(
    modem: Modem, users: dict[str, str], allowed_networks: tuple[Network, ...] = ()
) -> Flask:
    app = Flask(__name__)
    app.config['USERS'] = users

    if allowed_networks:
        logger.info(
            'Access limited to %s', ', '.join(str(network) for network in allowed_networks)
        )
        app.before_request(reject_foreign_addresses(allowed_networks))

    api = Api(app)
    resource_args = {'resource_class_args': [modem]}
    api.add_resource(SmsList, '/sms', **resource_args)
    api.add_resource(SmsItem, '/sms/<int:sms_id>', **resource_args)
    api.add_resource(SmsInbox, '/getsms', **resource_args)
    api.add_resource(Signal, '/signal', **resource_args)
    api.add_resource(Network, '/network', **resource_args)
    api.add_resource(Reset, '/reset', **resource_args)

    return app
