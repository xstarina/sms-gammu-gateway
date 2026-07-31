"""HTTP-ресурсы шлюза и фабрика приложения Flask."""

from __future__ import annotations

import hmac
import logging
from functools import wraps
from typing import Any, Callable

import gammu
from flask import Flask, current_app, request
from flask_httpauth import HTTPBasicAuth
from flask_restful import Api, Resource, abort

from sms_gateway.config import as_bool
from sms_gateway.modem import Modem

logger = logging.getLogger(__name__)
auth = HTTPBasicAuth()

# Ответ на запрос к пустому ящику: структура сохраняется, поля пустые
EMPTY_SMS = {'Date': '', 'Number': '', 'State': '', 'Text': ''}


@auth.verify_password
def verify_password(username: str, password: str) -> str | None:
    expected = current_app.config['USERS'].get(username)
    if not expected or not password:
        return None

    # Сравнение за постоянное время, чтобы пароль нельзя было подобрать по времени ответа
    if not hmac.compare_digest(expected, password):
        return None

    return username


@auth.error_handler
def unauthorized() -> tuple[dict[str, str], int]:
    return {'message': 'Unauthorized access'}, 401


def handle_gsm_errors(func: Callable) -> Callable:
    """Отдаёт 502 вместо стектрейса, если модем не ответил или вернул ошибку."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except gammu.GSMError as error:
            # Traceback для кодов 5xx пишет сам flask-restful, здесь важна причина
            logger.warning('Ошибка модема: %s', error)
            message = f'Modem error: {error}'

        # abort вне блока except, иначе в лог попадает сцепленный traceback
        abort(502, message=message)

    return wrapper


def request_params() -> Any:
    """Параметры запроса из JSON, формы или query string — в этом порядке."""
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return request.form if request.form else request.args


def split_numbers(raw: Any) -> list[str]:
    """Номера получателей: в одном запросе их можно перечислить через запятую."""
    if not raw:
        return []
    return [number.strip() for number in str(raw).split(',') if number.strip()]


def public_view(sms: dict[str, Any]) -> dict[str, Any]:
    """Locations — внутренние адреса частей в памяти модема, наружу не отдаются."""
    return {key: value for key, value in sms.items() if key != 'Locations'}


class ModemResource(Resource):
    """Базовый ресурс: аутентификация обязательна, ошибки модема не текут наружу.

    Декораторы применяются в обратном порядке, поэтому login_required
    оказывается внешним и отсекает запрос до обращения к устройству.
    """

    method_decorators = [handle_gsm_errors, auth.login_required]

    def __init__(self, modem: Modem) -> None:
        self.modem = modem


class SmsList(ModemResource):
    """Все входящие сообщения и отправка новых."""

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
    """Сообщение по порядковому номеру в текущем списке."""

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
    """Забирает первое сообщение и удаляет его из памяти модема."""

    def get(self) -> dict[str, Any]:
        sms = self.modem.pop_sms()
        return EMPTY_SMS if sms is None else public_view(sms)


class Signal(ModemResource):
    """Уровень сигнала."""

    def get(self) -> dict[str, Any]:
        return self.modem.signal_quality()


class Network(ModemResource):
    """Информация о сети оператора."""

    def get(self) -> dict[str, Any]:
        return self.modem.network_info()


class Reset(ModemResource):
    """Программный сброс модема."""

    def get(self) -> tuple[dict[str, Any], int]:
        self.modem.reset()
        return {'status': 200, 'message': 'Reset done'}, 200


def create_app(modem: Modem, users: dict[str, str]) -> Flask:
    app = Flask(__name__)
    app.config['USERS'] = users

    api = Api(app)
    resource_args = {'resource_class_args': [modem]}
    api.add_resource(SmsList, '/sms', **resource_args)
    api.add_resource(SmsItem, '/sms/<int:sms_id>', **resource_args)
    api.add_resource(SmsInbox, '/getsms', **resource_args)
    api.add_resource(Signal, '/signal', **resource_args)
    api.add_resource(Network, '/network', **resource_args)
    api.add_resource(Reset, '/reset', **resource_args)

    return app
