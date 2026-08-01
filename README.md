# SMS Gammu Gateway

[![Docker](https://github.com/xstarina/sms-gammu-gateway/actions/workflows/docker.yml/badge.svg)](https://github.com/xstarina/sms-gammu-gateway/actions/workflows/docker.yml)

**English** · [Русский](https://github.com/xstarina/sms-gammu-gateway/blob/main/README.ru.md)

Source code and issues: **https://github.com/xstarina/sms-gammu-gateway**

A simple REST API gateway for sending and receiving SMS through a GSM modem attached to the
host. The modem is driven by [Gammu](https://wammu.eu/gammu/) and its Python bindings, so any
device that speaks standard AT commands works — USB modems such as the Huawei E1750 in the
first place.

The application is a small Flask service, started with `python -m sms_gateway`.

## Project layout

```
sms_gateway/          application code
├── api.py            HTTP resources and the Flask application factory
├── modem.py          modem access through Gammu
├── config.py         environment settings and credentials
├── errors.py         application-level exceptions
└── __main__.py       entry point: wiring and server start
config/               configuration, mounted into the container
├── gammu.config      modem connection
└── credentials.txt   usernames and passwords, created from the .example file
tests/                tests against a fake modem
.github/workflows/    image build and publishing
Dockerfile            Gammu, environment and runtime image build
```

## Requirements

- Docker
- A GSM modem exposed on the host as a character device (`/dev/ttyUSB0` or similar)
- A SIM card, plus its PIN if the card asks for one

Check that the modem was detected:

```bash
lsusb
# Bus 001 Device 009: ID 12d1:1406 Huawei Technologies Co., Ltd. E1750
ls -l /dev/ttyUSB*
```

If the device only shows up as a CD-ROM, you need
[usb-modeswitch](http://www.draisberghof.de/usb_modeswitch) to switch it into modem mode.

## Quick start

There is no need to build the image — a ready one is published for `linux/amd64` and
`linux/arm64` to both the GitHub Container Registry and Docker Hub. The two are the same
image, so pick whichever registry suits you:

```
ghcr.io/xstarina/sms-gammu-gateway:latest
starina/sms-gammu-gateway:latest
```

```bash
# 1. Prepare the configuration
mkdir -p config && cd config
curl -O https://raw.githubusercontent.com/xstarina/sms-gammu-gateway/main/config/gammu.config
echo 'admin:your-password' > credentials.txt
cd ..

# 2. Run it
docker run -d --name sms-gw \
  -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  --group-add "$(stat -c '%g' /dev/ttyUSB0)" \
  -v "$PWD/config:/sms-gw/config:ro" \
  --restart unless-stopped \
  ghcr.io/xstarina/sms-gammu-gateway:latest
```

Check that it works:

```bash
curl -u admin:your-password http://localhost:5000/signal
```

The whole `config` directory is mounted, so edits to `gammu.config` and `credentials.txt`
take effect on a container restart, without rebuilding the image.

### Image tags

| Tag | Contents |
|---|---|
| `latest` | Most recent build, either from `main` or from a release tag |
| `main` | Current state of the `main` branch |
| `1.2.3` | A specific release, built from the `v1.2.3` git tag |
| `1.2` | Latest patch within a minor version |

Every image passes the test suite before publishing: if tests fail, nothing reaches the
registry. For production pin a specific version rather than `latest`, so upgrades happen when
you decide, not on the next restart.

### Upgrading

```bash
docker pull ghcr.io/xstarina/sms-gammu-gateway:latest
docker rm -f sms-gw
# then repeat the docker run command from the quick start
```

### Building from source

Needed if you want to change the code or pin your own Gammu version:

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

### About `--group-add` and device permissions

The container runs as the unprivileged user `gammu`, so access to the forwarded device is
decided by its group. That user belongs to `dialout` (GID 20) out of the box, which covers
most hosts (Debian, Ubuntu, Alpine).

If `/dev/ttyUSB0` belongs to a different group on your host (`uucp`, GID 14, on Arch for
example), pass that GID with `--group-add` as shown above. Without it the application fails at
startup with `gammu.ERR_DEVICENOTEXIST` or a permission error.

To see the current owner of the device: `ls -l /dev/ttyUSB0`.

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
      - "20"          # GID of the group owning /dev/ttyUSB0 on the host
    volumes:
      - ./config:/sms-gw/config:ro
    environment:
      PIN: "1234"
      TZ: Europe/Moscow
    restart: unless-stopped
```

Upgrading: `docker compose pull && docker compose up -d`.

To build the image from your own copy of the sources, replace `image` with `build: .` — the
rest of the settings stay the same.

## Configuration

### config/credentials.txt

Usernames and passwords for HTTP Basic auth, one `username:password` pair per line. A template
sits next to it in [config/credentials.txt.example](https://github.com/xstarina/sms-gammu-gateway/blob/main/config/credentials.txt.example):

```
admin:password
```

**The file is neither stored in the repository nor baked into the image** — otherwise the
password would end up in an image layer. Create it and mount it at runtime, or the container
will fail at startup with `No such file or directory: 'config/credentials.txt'`.

### config/gammu.config

Modem connection settings in the [Gammu format](https://wammu.eu/docs/manual/config/index.html):

```ini
[gammu]
device = /dev/mobile
name = Phone on USB serial port
connection = at
```

Inside the container the device is expected at `/dev/mobile`, which is why the run examples use
`--device=/dev/ttyUSB0:/dev/mobile`. If you would rather point at the real device path, change
`device` in this file.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `PIN` | unset | SIM card PIN. Required only if the card asks for one; without it the gateway will not start |
| `PORT` | `5000` | HTTP server port |
| `SSL` | off | Enables HTTPS. `1`, `true`, `yes` and `on` are truthy (case-insensitive), anything else turns it off |
| `GAMMU_CONFIG` | `config/gammu.config` | Path to the Gammu configuration file |
| `CREDENTIALS_FILE` | `config/credentials.txt` | Path to the credentials file |
| `TZ` | `UTC` | Container timezone, for example `Europe/Moscow`. Controls timestamps in the logs |

### HTTPS

With `SSL` enabled the application reads the key and the certificate from fixed paths, so
mount them into the prepared `/ssl` directory:

```bash
docker run -d -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  -v "$PWD/config:/sms-gw/config:ro" \
  -v "$PWD/ssl:/ssl:ro" \
  -e SSL=True \
  ghcr.io/xstarina/sms-gammu-gateway:latest
```

Expected files: `/ssl/cert.pem` and `/ssl/key.pem`.

## API

Every endpoint requires HTTP Basic authentication against the pairs in
`config/credentials.txt`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/sms` | List every SMS in modem memory and on the SIM |
| `POST` | `/sms` | Send an SMS |
| `GET` | `/sms/<id>` | An SMS by its index in the list |
| `DELETE` | `/sms/<id>` | Delete an SMS by its index |
| `GET` | `/getsms` | Return the first SMS **and delete it right away** from the modem |
| `GET` | `/signal` | Signal quality |
| `GET` | `/network` | Network information, including the operator name |
| `GET` | `/reset` | Soft reset of the modem |

The `<id>` is a position in the current message list, not a stable identifier: deleting any
SMS shifts the indices.

### Status codes

| Code | When |
|---|---|
| `400` | Required parameters are missing when sending |
| `401` | Credentials are missing or wrong |
| `404` | No message with that index |
| `502` | The modem did not answer or returned an error |

The error body is JSON of the form `{"message": "..."}`.

### Sending an SMS

```bash
curl -u admin:password -X POST http://localhost:5000/sms \
  -H "Content-Type: application/json" \
  -d '{"number": "+79001234567", "text": "Test message"}'
```

Anything outside the Latin alphabet needs `unicode`. Without it the text is encoded with the
GSM 7-bit alphabet, which has no Cyrillic letters, and the recipient gets question marks:

```bash
curl -u admin:password -X POST http://localhost:5000/sms \
  -H "Content-Type: application/json" \
  -d '{"number": "+79001234567", "text": "Привет! Это тест.", "unicode": true}'
```

Line breaks travel as `\n` inside the JSON string, and several recipients are listed in
`number` separated by commas:

```bash
curl -u admin:password -X POST http://localhost:5000/sms \
  -H "Content-Type: application/json" \
  -d '{"number": "+79001234567,+79007654321", "text": "Первая строка\nВторая строка", "unicode": true}'
```

A form-encoded body works as well, but mind the plus sign: in
`application/x-www-form-urlencoded` a `+` stands for a space, so `-d "number=+79001234567"`
quietly drops it and the number arrives as `79001234567`. Use `--data-urlencode`, which
escapes the plus for you:

```bash
curl -u admin:password -X POST http://localhost:5000/sms \
  --data-urlencode "number=+79001234567" \
  --data-urlencode "text=Привет! Это тест." \
  -d "unicode=true"
```

Parameters (form-encoded or JSON):

| Parameter | Required | Description |
|---|:---:|---|
| `number` | yes | Recipient number. Several can be listed comma separated, and the message goes to each of them |
| `text` | yes | Message text. Long texts are automatically split into several parts |
| `unicode` | no | `True` for non-Latin alphabets such as Cyrillic. `1`, `true`, `yes` and `on` are truthy |
| `smsc` | no | SMS centre number. Defaults to the one stored on the SIM (`Location: 1`) |

### Receiving SMS

```bash
# Read everything without deleting
curl -u admin:password http://localhost:5000/sms

# Take the first one and delete it from the modem
curl -u admin:password http://localhost:5000/getsms
```

For an empty inbox `/getsms` returns an object with empty `Date`, `Number`, `State` and `Text`.

## Build

```bash
docker build -t sms-gammu-gateway .
```

The image is built in several stages on top of `alpine`: the builder stage compiles Gammu and
`python-gammu` from source, while the final image receives only `libGammu`, `libgsmsd`, the
`gammu` CLI (for diagnostics) and the prepared Python environment. The result is about 130 MB.

The container runs as an unprivileged user; code and environment belong to `root` and are
read-only for it. A liveness probe is built into the image, so `docker ps` reports `healthy`
as soon as the service starts accepting connections.

The Gammu version is a build argument:

```bash
docker build --build-arg GAMMU_VERSION=1.43.3 -t sms-gammu-gateway .
```

Python dependency versions are pinned in [requirements.txt](https://github.com/xstarina/sms-gammu-gateway/blob/main/requirements.txt). A build takes a
few minutes because Gammu is compiled from source — there is no prebuilt package for current
Alpine.

### Diagnostics

The `gammu` CLI is available inside the container:

```bash
docker exec -it sms-gw gammu --config config/gammu.config --identify
```

The runtime image ships without `pip`, which saved the 13 MB it used to occupy. If you need to
install packages for debugging, use the `test` stage, where the environment is complete.

## Tests

The tests run against a fake modem, so no device is required. A dedicated build stage installs
pytest on top of the builder environment:

```bash
docker build --target test -t sms-gammu-gateway-test .
docker run --rm sms-gammu-gateway-test
```

Covered are the HTTP layer ([tests/test_api.py](https://github.com/xstarina/sms-gammu-gateway/blob/main/tests/test_api.py)) — authentication on every
route, status codes, parameter parsing — and configuration
([tests/test_config.py](https://github.com/xstarina/sms-gammu-gateway/blob/main/tests/test_config.py)): environment variables and credentials loading.
The device conversation inside `sms_gateway.modem` is not covered: it can only be verified for
real, against a connected modem.

## Known limitations

- **The built-in Flask server is used** (`app.run`), which is not meant for production load.
  For permanent deployments put nginx in front of it or run it through a WSGI server.
- **Passwords are stored in plain text** in `config/credentials.txt` — that is what the format
  requires, not an oversight; keep the file at mode `600` and never commit real credentials.
- **Modem requests are serialised.** Gammu keeps a single connection to the device, so calls
  are serialised by a lock: concurrent requests do not corrupt each other, but they do wait for
  the previous one to finish.
- **SMS indices are unstable** — see the note on `/sms/<id>` above.

## Contributing

Patches are welcome — see [CONTRIBUTING.md](https://github.com/xstarina/sms-gammu-gateway/blob/main/CONTRIBUTING.md) for how to run the tests and what
is expected of a change. One rule worth repeating here: `README.md` and `README.ru.md` are
updated together, in the same commit.

## License

Apache License 2.0, see [LICENSE](https://github.com/xstarina/sms-gammu-gateway/blob/main/LICENSE).

This project is based on [pajikos/sms-gammu-gateway](https://github.com/pajikos/sms-gammu-gateway).
