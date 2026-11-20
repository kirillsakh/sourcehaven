# Requires BuildKit (RUN --mount): the default in Docker Desktop, Docker 23+ and `docker compose build`;
# on a bare Docker 20.10 engine set DOCKER_BUILDKIT=1.
FROM ghcr.io/astral-sh/uv:0.9.17 AS uv

FROM python:3.14-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# --no-default-groups: the "test" group is a default group, so --no-dev alone would still export it.
# --no-emit-project: the application wheel is installed separately, without its dependencies.
RUN uv export --frozen --no-dev --no-default-groups --no-editable --no-hashes --no-emit-project \
        -o requirements.txt \
    && uv build --wheel --out-dir dist

FROM python:3.14-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=bind,from=builder,source=/build,target=/build \
    uv pip install --system --no-cache -r /build/requirements.txt \
    && uv pip install --system --no-cache --no-deps /build/dist/*.whl
# tiktoken ships no encoding data and would download it on first use; fetch it at build time so the
# container never needs network access for token counting. World-readable for the runtime user.
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX "$TIKTOKEN_CACHE_DIR"
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin sourcehaven \
    && mkdir -p /var/lib/sourcehaven/uploads \
    && chown sourcehaven:sourcehaven /var/lib/sourcehaven/uploads
USER sourcehaven
ENTRYPOINT ["sourcehaven"]
