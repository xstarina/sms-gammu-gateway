# ------------------------------------------------------------------------------
# Base: libraries needed both at build time and at runtime
# ------------------------------------------------------------------------------
FROM alpine:3.24 AS base

# tzdata makes the TZ variable work: without the timezone database musl keeps
# the container on UTC and log timestamps do not match local time.
RUN set -ex; \
    apk add --no-cache \
        python3 \
        libcurl \
        bluez-libs \
        libusb \
        tzdata \
    ;

WORKDIR /sms-gw

# ------------------------------------------------------------------------------
# Builder: compile Gammu and install the Python dependencies
# ------------------------------------------------------------------------------
FROM base AS builder

# Pinned to a tag so the build does not depend on the current state of master.
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

# Gammu goes into the standard /usr/local so that pkg-config finds its headers
# and libraries when python-gammu is built. Documentation is not needed.
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

# The environment is created without pip: it is useless at runtime and weighs 13 MB.
# Packages are installed by the system pip, --python points it at the target env.
# CFLAGS work around the strict GCC 14 check while building python-gammu, and the
# rpath records the path to libGammu in the module.
COPY requirements.txt ./
RUN set -ex; \
    python3 -m venv --without-pip .venv; \
    CFLAGS="-Wno-error=return-mismatch -Wno-return-mismatch" \
    LDFLAGS="-Wl,-rpath,/usr/local/lib" \
    pip --python .venv/bin/python install --no-cache-dir -r requirements.txt;

# ------------------------------------------------------------------------------
# Tests: pytest on top of the build environment
# ------------------------------------------------------------------------------
# Declared before the final stage, so a plain build never touches it. To run:
# docker build --target test -t sms-gammu-gateway-test . && docker run --rm sms-gammu-gateway-test
FROM builder AS test

COPY requirements-dev.txt pyproject.toml ./
RUN pip --python .venv/bin/python install --no-cache-dir -r requirements-dev.txt

COPY sms_gateway/ ./sms_gateway/
COPY config/ ./config/
COPY tests/ ./tests/

# Test paths and the project root on sys.path are configured in pyproject.toml.
CMD [".venv/bin/pytest"]

# ------------------------------------------------------------------------------
# Runtime: build artifacts only, no compilers and no headers
# ------------------------------------------------------------------------------
FROM base AS final

# The source label is what links a published package back to its repository, both on
# GHCR and in tooling that inspects images.
LABEL org.opencontainers.image.title="SMS Gammu Gateway" \
      org.opencontainers.image.description="REST API for sending and receiving SMS through a GSM modem" \
      org.opencontainers.image.source="https://github.com/xstarina/sms-gammu-gateway" \
      org.opencontainers.image.url="https://github.com/xstarina/sms-gammu-gateway" \
      org.opencontainers.image.licenses="Apache-2.0"

# The dialout group (GID 20) grants access to the forwarded modem: on most hosts
# (Debian, Ubuntu, Alpine) /dev/tty* belongs to exactly this group. Hosts using a
# different GID pass it with --group-add, see the README.
# The UID is fixed rather than left to the next free number: USER below refers to
# it numerically, and a shifted UID would silently point somewhere else.
RUN set -ex; \
    adduser -g 'Gammu User' -SDH -u 100 gammu; \
    addgroup gammu dialout; \
    mkdir -p /ssl; \
    chown gammu /ssl

# Only libGammu and libgsmsd are needed from the builder, _gammu.so links against
# both, plus the gammu CLI for diagnostics. Headers and pkg-config files stay behind.
COPY --link --from=builder /usr/local/bin/gammu /usr/local/bin/
COPY --link --from=builder /usr/local/lib/lib*.so* /usr/local/lib/

# Code and environment belong to root: the application only needs to read them, and
# it cannot rewrite its own files. Directories are listed explicitly to keep tests
# and repository housekeeping files out of the image.
COPY --link --from=builder /sms-gw/.venv/ ./.venv/
COPY --link sms_gateway/ ./sms_gateway/
COPY --link config/gammu.config ./config/

# The environment on PATH allows calling python without a path, and unbuffered
# output is what makes logs show up in docker logs right away.
ENV PATH="/sms-gw/.venv/bin:${PATH}" \
    PORT=5000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Numeric on purpose: orchestrators that verify the container is not root, such as
# Kubernetes with runAsNonRoot, cannot resolve a name from the image passwd file.
USER 100
EXPOSE 5000/tcp

# TCP liveness probe: independent of both authentication and SSL.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ['PORT'])), 3).close()"]

CMD ["python", "-m", "sms_gateway"]
