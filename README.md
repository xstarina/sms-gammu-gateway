# SMS Gammu Gateway

[![Docker](https://github.com/xstarina/sms-gammu-gateway/actions/workflows/docker.yml/badge.svg)](https://github.com/xstarina/sms-gammu-gateway/actions/workflows/docker.yml)

Простой REST API-шлюз для отправки и приёма SMS через GSM-модем, подключённый к хосту.
Работа с модемом идёт через [Gammu](https://wammu.eu/gammu/) и его Python-биндинги, так что
поддерживается любое устройство, понимающее стандартные AT-команды — в первую очередь
USB-модемы (Huawei E1750 и подобные).

Приложение — небольшой Flask-сервис, запускается как `python -m sms_gateway`.

## Структура проекта

```
sms_gateway/          код приложения
├── api.py            HTTP-ресурсы и фабрика приложения Flask
├── modem.py          работа с модемом через Gammu
├── config.py         настройки из окружения и учётные данные
├── errors.py         исключения уровня приложения
└── __main__.py       точка входа: сборка и запуск сервера
config/               конфигурация, монтируется в контейнер
├── gammu.config      подключение к модему
└── credentials.txt   логины и пароли, создаётся из .example
tests/                тесты на поддельном модеме
.github/workflows/    сборка и публикация образа
Dockerfile            сборка Gammu, окружения и рантайм-образа
```

## Требования

- Docker
- GSM-модем, видимый на хосте как символьное устройство (`/dev/ttyUSB0` и т.п.)
- SIM-карта; если на ней включён запрос PIN — сам PIN

Проверить, что модем определился:

```bash
lsusb
# Bus 001 Device 009: ID 12d1:1406 Huawei Technologies Co., Ltd. E1750
ls -l /dev/ttyUSB*
```

Если устройство определяется только как CD-ROM, понадобится
[usb-modeswitch](http://www.draisberghof.de/usb_modeswitch), чтобы переключить его в режим модема.

## Быстрый старт

Собирать образ не нужно — готовый публикуется в GitHub Container Registry под
`linux/amd64` и `linux/arm64`.

```bash
# 1. Подготовить конфигурацию
mkdir -p config && cd config
curl -O https://raw.githubusercontent.com/xstarina/sms-gammu-gateway/main/config/gammu.config
echo 'admin:ваш-пароль' > credentials.txt
cd ..

# 2. Запустить
docker run -d --name sms-gw \
  -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  --group-add "$(stat -c '%g' /dev/ttyUSB0)" \
  -v "$PWD/config:/sms-gw/config:ro" \
  --restart unless-stopped \
  ghcr.io/xstarina/sms-gammu-gateway:latest
```

Проверка:

```bash
curl -u admin:ваш-пароль http://localhost:5000/signal
```

Каталог `config` монтируется целиком: так правки в `gammu.config` и `credentials.txt`
подхватываются перезапуском контейнера, без пересборки образа.

### Теги образа

| Тег | Что внутри |
|---|---|
| `latest`, `main` | Текущее состояние ветки `main` |
| `1.2.3` | Конкретный релиз, из git-тега `v1.2.3` |
| `1.2` | Последний патч в минорной версии |

Каждый образ проходит тесты до публикации: если они падают, в реестр ничего не уходит.
Для продакшна лучше указывать конкретную версию, а не `latest` — так обновление
происходит по вашему решению, а не при очередном перезапуске.

### Обновление

```bash
docker pull ghcr.io/xstarina/sms-gammu-gateway:latest
docker rm -f sms-gw
# и повторить docker run из быстрого старта
```

### Сборка из исходников

Нужна, если хотите поменять код или зафиксировать свою версию Gammu:

```bash
git clone https://github.com/xstarina/sms-gammu-gateway.git
cd sms-gammu-gateway
cp config/credentials.txt.example config/credentials.txt
$EDITOR config/credentials.txt

docker build -t sms-gammu-gateway .
docker run -d --name sms-gw \
  -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  --group-add "$(stat -c '%g' /dev/ttyUSB0)" \
  -v "$PWD/config:/sms-gw/config:ro" \
  sms-gammu-gateway
```

### Про `--group-add` и права на устройство

Контейнер работает от непривилегированного пользователя `gammu`, поэтому доступ к
проброшенному устройству определяется его группой. Пользователь по умолчанию входит в
группу `dialout` (GID 20) — этого достаточно для большинства хостов (Debian, Ubuntu, Alpine).

Если на вашем хосте `/dev/ttyUSB0` принадлежит другой группе (например, `uucp` GID 14 в Arch),
добавьте её GID через `--group-add`, как в примере выше. Без этого приложение упадёт на старте
с `gammu.ERR_DEVICENOTEXIST` или ошибкой доступа.

Посмотреть текущего владельца устройства: `ls -l /dev/ttyUSB0`.

### docker compose

```yaml
services:
  sms-gateway:
    image: ghcr.io/xstarina/sms-gammu-gateway:latest
    ports:
      - "5000:5000"
    devices:
      - /dev/ttyUSB0:/dev/mobile
    group_add:
      - "20"          # GID группы, которой принадлежит /dev/ttyUSB0 на хосте
    volumes:
      - ./config:/sms-gw/config:ro
    environment:
      PIN: "1234"
      TZ: Europe/Moscow
    restart: unless-stopped
```

Обновление: `docker compose pull && docker compose up -d`.

Чтобы собирать образ из своей копии исходников, замените `image` на `build: .` — остальные
параметры не меняются.

## Конфигурация

### config/credentials.txt

Логины и пароли для HTTP Basic Auth, по одной паре на строку в формате `логин:пароль`.
Шаблон лежит рядом в [config/credentials.txt.example](config/credentials.txt.example):

```
admin:password
```

**Файл не хранится в репозитории и не попадает в образ** — иначе пароль запёкся бы в слой.
Его нужно создать и смонтировать при запуске, иначе контейнер упадёт на старте с
`No such file or directory: 'config/credentials.txt'`.

### config/gammu.config

Конфиг подключения к модему в [формате Gammu](https://wammu.eu/docs/manual/config/index.html):

```ini
[gammu]
device = /dev/mobile
name = Phone on USB serial port
connection = at
```

Внутри контейнера устройство ожидается по пути `/dev/mobile` — именно поэтому в примерах запуска
используется `--device=/dev/ttyUSB0:/dev/mobile`. Если удобнее указать реальный путь устройства,
поправьте `device` в этом файле.

### Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PIN` | не задан | PIN SIM-карты. Требуется, только если карта его запрашивает; без него шлюз не стартует |
| `PORT` | `5000` | Порт HTTP-сервера |
| `SSL` | выключен | Включает HTTPS. Истинными считаются `1`, `true`, `yes`, `on` (регистр не важен), любое другое значение выключает |
| `GAMMU_CONFIG` | `config/gammu.config` | Путь к конфигу Gammu |
| `CREDENTIALS_FILE` | `config/credentials.txt` | Путь к файлу с учётными данными |
| `TZ` | `UTC` | Часовой пояс контейнера, например `Europe/Moscow`. Определяет время в логах |

### HTTPS

При включённом `SSL` приложение читает ключ и сертификат по фиксированным путям — их нужно
смонтировать в подготовленный каталог `/ssl`:

```bash
docker run -d -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  -v "$PWD/config:/sms-gw/config:ro" \
  -v "$PWD/ssl:/ssl:ro" \
  -e SSL=True \
  ghcr.io/xstarina/sms-gammu-gateway:latest
```

Ожидаемые файлы: `/ssl/cert.pem` и `/ssl/key.pem`.

## API

Все эндпоинты требуют HTTP Basic-аутентификации по парам из `config/credentials.txt`.

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/sms` | Список всех SMS в памяти модема и на SIM |
| `POST` | `/sms` | Отправить SMS |
| `GET` | `/sms/<id>` | SMS по индексу в списке |
| `DELETE` | `/sms/<id>` | Удалить SMS по индексу |
| `GET` | `/getsms` | Вернуть первую SMS **и сразу удалить её** из модема |
| `GET` | `/signal` | Уровень сигнала |
| `GET` | `/network` | Информация о сети, включая имя оператора |
| `GET` | `/reset` | Программный сброс модема |

Идентификатор `<id>` — это порядковый номер в текущем списке сообщений, а не постоянный
идентификатор: после удаления любой SMS индексы смещаются.

### Коды ответов

| Код | Когда |
|---|---|
| `400` | Не переданы обязательные параметры при отправке |
| `401` | Отсутствуют или неверны учётные данные |
| `404` | Сообщения с таким индексом нет |
| `502` | Модем не ответил или вернул ошибку |

Тело ошибки — JSON вида `{"message": "..."}`.

### Отправка SMS

```bash
curl -u admin:password -X POST http://localhost:5000/sms \
  -d "number=+79001234567" \
  -d "text=Тестовое сообщение"
```

Параметры (form-encoded или JSON):

| Параметр | Обязательный | Описание |
|---|:---:|---|
| `number` | да | Номер получателя. Можно перечислить несколько через запятую — сообщение уйдёт каждому |
| `text` | да | Текст сообщения. Длинные тексты автоматически разбиваются на несколько частей |
| `unicode` | нет | `True` для не-латинских алфавитов (кириллица). Истинными считаются `1`, `true`, `yes`, `on` |
| `smsc` | нет | Номер SMS-центра. По умолчанию берётся записанный на SIM (`Location: 1`) |

### Приём SMS

```bash
# Прочитать все, ничего не удаляя
curl -u admin:password http://localhost:5000/sms

# Забрать первую и удалить её из модема
curl -u admin:password http://localhost:5000/getsms
```

Ответ `/getsms` при пустом ящике — объект с пустыми полями `Date`, `Number`, `State`, `Text`.

## Сборка

```bash
docker build -t sms-gammu-gateway .
```

Образ собирается в несколько стадий на базе `alpine`: в builder-стадии из исходников
компилируется Gammu и `python-gammu`, в финальный образ попадают только `libGammu`,
`libgsmsd`, CLI `gammu` (для диагностики) и готовое окружение Python. Итоговый размер —
около 130 МБ.

Контейнер запускается от непривилегированного пользователя, код и окружение принадлежат
`root` и доступны ему только на чтение. В образ встроена проверка живости: `docker ps`
покажет состояние `healthy`, как только сервис начнёт принимать соединения.

Версия Gammu задаётся build-аргументом:

```bash
docker build --build-arg GAMMU_VERSION=1.43.3 -t sms-gammu-gateway .
```

Версии Python-зависимостей закреплены в [requirements.txt](requirements.txt). Сборка занимает
несколько минут — Gammu компилируется из исходников, готового пакета для актуального Alpine нет.

### Диагностика

CLI `gammu` доступен внутри контейнера:

```bash
docker exec -it sms-gw gammu --config config/gammu.config --identify
```

В рантайм-образе нет `pip` — он вырезан вместе с 13 МБ, которые занимал. Если для отладки
нужно доставить пакеты, используйте стадию `test`, там окружение полное.

## Тесты

Тесты работают с поддельным модемом, поэтому устройство для них не нужно. Отдельная стадия
сборки ставит pytest поверх окружения builder:

```bash
docker build --target test -t sms-gammu-gateway-test .
docker run --rm sms-gammu-gateway-test
```

Покрыты HTTP-слой ([tests/test_api.py](tests/test_api.py)) — аутентификация всех маршрутов,
коды ответов, разбор параметров — и конфигурация ([tests/test_config.py](tests/test_config.py)):
переменные окружения и чтение учётных данных. Обмен с устройством внутри `sms_gateway.modem`
тестами не покрыт: он проверяется только вживую, на подключённом модеме.

## Известные ограничения

- **Используется встроенный сервер Flask** (`app.run`), не рассчитанный на продакшн-нагрузку.
  Для постоянной эксплуатации имеет смысл поставить перед ним nginx или запускать через WSGI-сервер.
- **Пароли хранятся в открытом виде** в `config/credentials.txt` — это требование формата, а не
  недосмотр; храните файл с правами `600` и не коммитьте реальные учётные данные.
- **Запросы к модему выполняются строго по очереди.** Gammu держит одно соединение с
  устройством, поэтому обращения сериализуются блокировкой: параллельные запросы не ломают
  друг друга, но ждут завершения предыдущего.
- **Индексы SMS нестабильны** — см. примечание к `/sms/<id>` выше.

## Лицензия

Apache License 2.0, см. [LICENSE](LICENSE).

Проект основан на [pajikos/sms-gammu-gateway](https://github.com/pajikos/sms-gammu-gateway).
