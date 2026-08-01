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
config/               modem configuration, baked into the image
└── gammu.config      connection settings
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
docker run -d --name sms-gw \
  -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  --group-add "$(stat -c '%g' /dev/ttyUSB0)" \
  -e USERS=admin:your-password \
  --restart unless-stopped \
  ghcr.io/xstarina/sms-gammu-gateway:latest
```

That is the whole setup: nothing to prepare beforehand and nothing to mount. The modem
configuration ships inside the image and expects the device at `/dev/mobile`, which is exactly
what the `--device` mapping provides.

Check that it works:

```bash
curl -u admin:your-password http://localhost:5000/signal
```

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

docker build -t sms-gammu-gateway .
docker run -d --name sms-gw \
  -p 5000:5000 \
  --device=/dev/ttyUSB0:/dev/mobile \
  --group-add "$(stat -c '%g' /dev/ttyUSB0)" \
  -e USERS=admin:your-password \
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
    environment:
      USERS: admin:your-password
      PIN: "1234"
      TZ: Europe/Moscow
    restart: unless-stopped
```

Upgrading: `docker compose pull && docker compose up -d`.

### Hardened run

The container needs no capabilities and writes nothing to its own filesystem, so it can be
locked down further:

```yaml
    read_only: true
    tmpfs:
      - /tmp
      - /var/lock          # only needed if lockdevice is enabled in gammu.config
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 128
    mem_limit: 256m
```

Port 5000 is above 1024 and access to the modem comes from the device group, so not a single
capability is required. The image also runs as UID 100, declared numerically so that
orchestrators verifying "not root" do not have to resolve a name.

To build the image from your own copy of the sources, replace `image` with `build: .` — the
rest of the settings stay the same.

## Configuration

### Credentials

Pairs for HTTP Basic auth come from `USERS`, and there is no credentials file to prepare:

```yaml
    environment:
      USERS: admin:your-password,monitoring:another-password
```

Pairs are separated by commas, spaces or newlines, so a compose block scalar with one pair per
line reads just as well. A password may contain colons — only the first one separates — but not
commas or spaces, since those end the pair.

The gateway refuses to start when `USERS` is unset or holds anything that is not a usable pair,
and says which entry it choked on. Credentials are the one thing it cannot guess, so guessing
is not attempted.

#### Storing a hash instead of the password

A password written into the environment is readable by anyone who can run `docker inspect` or
open the compose file. Instead of the password itself the variable may carry its hash, which
cannot be turned back into the password and cannot be used to log in.

`htpasswd` prints exactly the `login:hash` pair this variable expects:

```bash
htpasswd -nbB admin your-password
# admin:$2y$05$9F7kBCq2MTqsnSehrbZeKu3E1mJzt38dffCKJJsHZFVSlrcILp6PO
```

Without `htpasswd` installed, borrow it from an image:

```bash
docker run --rm httpd:alpine htpasswd -nbB admin your-password
```

Paste the whole line into the variable, doubling every `$`:

```yaml
    environment:
      USERS: admin:$$2y$$05$$9F7kBCq2MTqsnSehrbZeKu3E1mJzt38dffCKJJsHZFVSlrcILp6PO
```

**Doubling matters.** Compose reads a single `$` as the start of a variable name, eats part of
the hash and only prints a warning, after which the password silently stops working. On a
`docker run` command line single quotes around the value are enough.

Hashed and plain entries may be mixed in the same variable. Besides bcrypt the gateway also
accepts what `werkzeug.security` produces, in case a hash has to be made without `htpasswd`.
Verification takes a few tens of milliseconds by design — that is what makes a stolen hash
expensive to attack, and for a gateway sending a handful of messages it is not a load worth
worrying about.

Note that this protects the password where it is stored, not where it travels: HTTP Basic auth
still sends the password itself with every request, so use `SSL` or a trusted network.

### The modem configuration

Connection settings live in the image in the [Gammu format](https://wammu.eu/docs/manual/config/index.html):

```ini
[gammu]
device = /dev/mobile
name = Phone on USB serial port
connection = at
```

The device is expected at `/dev/mobile`, which is why the run examples map
`--device=/dev/ttyUSB0:/dev/mobile`. This suits the common case, so nothing has to be mounted.

For anything else — a different connection type, a Bluetooth phone, a real device path instead
of the mapping — write your own file and mount it over this one, or point `GAMMU_CONFIG` at it:

```yaml
    volumes:
      - ./gammu.config:/sms-gw/config/gammu.config:ro
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `USERS` | **required** | Pairs for Basic auth, `admin:secret`, separated by commas, spaces or newlines |
| `ALLOWED_NETWORKS` | unset | Addresses and subnets allowed to reach the API. Unset means no restriction |
| `PIN` | unset | SIM card PIN. Required only if the card asks for one; without it the gateway will not start |
| `PORT` | `5000` | HTTP server port |
| `SSL` | off | Enables HTTPS. `1`, `true`, `yes` and `on` are truthy (case-insensitive), anything else turns it off |
| `GAMMU_CONFIG` | `config/gammu.config` | Path to the Gammu configuration file |
| `TZ` | `UTC` | Container timezone, for example `Europe/Moscow`. Controls timestamps in the logs |
| `WATCHDOG_INTERVAL` | `60` | Seconds between modem probes. `0` turns the watchdog off |
| `WATCHDOG_FAILURES` | `3` | Failed probes in a row before the session is rebuilt |

### Restricting access by address

`ALLOWED_NETWORKS` limits who may reach the API. Individual addresses and subnets both work:

```yaml
    environment:
      ALLOWED_NETWORKS: 10.0.0.0/8,192.168.1.5
```

The check runs before authentication, so a stranger never gets as far as guessing a password;
refused requests get `403` and a line in the log. Leaving the variable unset places no
restriction at all.

An entry that is not an address or a subnet stops the gateway with a message naming it.
Skipping it would leave the API open to everyone while the log quietly mentioned a typo, and a
whitelist that silently does nothing is worse than no whitelist at all. Leaving the variable
unset remains a valid answer.

The address compared is the one the server sees. Behind a reverse proxy that is the proxy
itself, and forwarded headers are deliberately not trusted: anyone can send those. Restrict by
address on the proxy in that case.

### Recovering from a wedged modem

A modem that hangs rarely reports an error, it simply stops answering. A background watchdog
asks it for the signal quality every `WATCHDOG_INTERVAL` seconds. Single failures are ignored —
the modem may be busy sending an SMS — but after `WATCHDOG_FAILURES` of them in a row the Gammu
session is torn down and opened again, which clears most hangs without touching the container.

If reopening the device fails as well, the process exits with a non-zero code and leaves the
rest to the restart policy, so make sure the container has one:

```yaml
    restart: unless-stopped
```

Loss of network registration is deliberately **not** treated as a fault. No amount of
restarting brings a cell tower back, and reacting to it would turn weak signal into a restart
loop. Watch `/signal` and `/network` for that instead.

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

If `/ssl` holds no certificate, the gateway does not refuse to start: it generates a
self-signed one and serves HTTPS with that. Handy for a quick check or a trusted network, but
keep in mind that the certificate is regenerated on every restart and no client will trust it,
so `curl` needs `-k` and anything past a trusted network needs a real certificate. Generating
it goes through a temporary file, so a container started with `read_only: true` also needs a
writable `/tmp` — the hardened example above already mounts one. Without it the gateway stops
at startup and says so.

## API

Every endpoint requires HTTP Basic authentication against the pairs in `USERS`.

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
([tests/test_config.py](https://github.com/xstarina/sms-gammu-gateway/blob/main/tests/test_config.py)): environment variables, credentials and the address whitelist.
The device conversation inside `sms_gateway.modem` is not covered: it can only be verified for
real, against a connected modem.

## Known limitations

- **The built-in Flask server is used** (`app.run`), which is not meant for production load.
  For permanent deployments put nginx in front of it or run it through a WSGI server.
- **Basic auth sends the password with every request**, so the connection is what protects it:
  use `SSL`, or keep the gateway on a trusted network. Storing a hash in `USERS` protects where
  the password rests, not how it travels.
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
