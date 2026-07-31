# ------------------------------------------------------------------------------
# База: библиотеки, нужные и при сборке, и в рантайме
# ------------------------------------------------------------------------------
FROM alpine:3.24 AS base

RUN set -ex; \
    apk add --no-cache \
        python3 \
        libcurl \
        bluez-libs \
        libusb \
    ;

WORKDIR /sms-gw

# ------------------------------------------------------------------------------
# Сборка: компиляция Gammu и установка зависимостей Python
# ------------------------------------------------------------------------------
FROM base AS builder

# Версия закреплена тегом, чтобы сборка не зависела от состояния ветки master.
ARG GAMMU_VERSION=1.43.3

RUN set -ex; \
    apk add --no-cache \
        build-base \
        cmake \
        pkgconfig \
        curl-dev \
        bluez-dev \
        libusb-dev \
        python3-dev \
        py3-pip \
        git \
    ;

# Gammu ставится в стандартный /usr/local, чтобы pkg-config сам нашёл заголовки
# и библиотеки при последующей сборке python-gammu. Документация не нужна.
RUN set -ex; \
    git clone --branch "${GAMMU_VERSION}" --depth 1 https://github.com/gammu/gammu.git /tmp/gammu; \
    cd /tmp/gammu; \
    cmake . \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DCMAKE_BUILD_TYPE=Release \
        -DINSTALL_DOC=OFF; \
    make -j"$(nproc)"; \
    make install; \
    rm -rf /tmp/gammu

# Окружение создаётся без pip: в рантайме он не нужен и весит 13 МБ. Пакеты ставит
# системный pip, ключ --python указывает ему на целевое окружение.
# CFLAGS обходят строгую проверку GCC 14 при сборке python-gammu, rpath прописывает
# в модуль путь к libGammu.
COPY requirements.txt ./
RUN set -ex; \
    python3 -m venv --without-pip .venv; \
    CFLAGS="-Wno-error=return-mismatch -Wno-return-mismatch" \
    LDFLAGS="-Wl,-rpath,/usr/local/lib" \
    pip --python .venv/bin/python install --no-cache-dir -r requirements.txt;

# ------------------------------------------------------------------------------
# Тесты: pytest поверх окружения сборки
# ------------------------------------------------------------------------------
# Стадия объявлена до финальной, поэтому обычная сборка её не затрагивает. Запуск:
# docker build --target test -t sms-gammu-gateway-test . && docker run --rm sms-gammu-gateway-test
FROM builder AS test

COPY requirements-dev.txt pyproject.toml ./
RUN pip --python .venv/bin/python install --no-cache-dir -r requirements-dev.txt

COPY sms_gateway/ ./sms_gateway/
COPY config/ ./config/
COPY tests/ ./tests/

# Каталоги с тестами и корень в sys.path заданы в pyproject.toml.
CMD [".venv/bin/pytest"]

# ------------------------------------------------------------------------------
# Рантайм: только собранные артефакты, без компиляторов и заголовков
# ------------------------------------------------------------------------------
FROM base AS final

LABEL org.opencontainers.image.title="SMS Gammu Gateway" \
      org.opencontainers.image.description="REST API для отправки и приёма SMS через GSM-модем" \
      org.opencontainers.image.licenses="Apache-2.0"

# Группа dialout (GID 20) даёт доступ к проброшенному модему: с большинства хостов
# (Debian, Ubuntu, Alpine) /dev/tty* приходит именно с этой группой. Если на хосте
# GID другой, его добавляют ключом --group-add, см. README.
RUN set -ex; \
    adduser -g 'Gammu User' -SDH gammu; \
    addgroup gammu dialout; \
    mkdir -p /ssl; \
    chown gammu /ssl

# Из сборочной стадии нужны только libGammu и libgsmsd, с обеими линкуется _gammu.so,
# плюс CLI gammu для диагностики. Заголовки и pkgconfig остаются в builder.
COPY --from=builder /usr/local/bin/gammu /usr/local/bin/
COPY --from=builder /usr/local/lib/lib*.so* /usr/local/lib/

# Код и окружение принадлежат root: приложению они нужны только на чтение, и правка
# собственных файлов из контейнера становится невозможной. Каталоги перечислены явно,
# чтобы в образ не попадали тесты и служебные файлы репозитория.
COPY --from=builder /sms-gw/.venv/ ./.venv/
COPY sms_gateway/ ./sms_gateway/
COPY config/gammu.config ./config/

# PATH с окружением позволяет вызывать python без указания пути, отключённая
# буферизация нужна, чтобы логи сразу попадали в docker logs.
ENV PATH="/sms-gw/.venv/bin:${PATH}" \
    PORT=5000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER gammu
EXPOSE 5000/tcp

# Проверка живости по TCP: не зависит ни от аутентификации, ни от включённого SSL.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ['PORT'])), 3).close()"]

CMD ["python", "-m", "sms_gateway"]
