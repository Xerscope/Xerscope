# syntax=docker/dockerfile:1.7
#
# xerscope in a container: uv builds, distroless runs.
#
#   docker build -t xerscope .
#   docker compose up            # http://localhost:8501, exports read from ./exports
#
# Build stage: uv installs a managed CPython (PYTHON_VERSION, python-build-standalone, needs
# only glibc) and the locked dependencies into /app/.venv. Runtime stage: distroless "cc"
# (glibc + libstdc++ for pyarrow, no shell, no package manager), non-root user. The
# interpreter and the venv are copied at the same paths, so the venv's links still resolve.
#
# Pin the base images by digest in production (docker buildx imagetools inspect <image>).

ARG UV_VERSION=0.13.6
ARG PYTHON_VERSION=3.14

FROM ghcr.io/astral-sh/uv:${UV_VERSION}-trixie-slim AS build
ARG PYTHON_VERSION
ENV UV_PYTHON_INSTALL_DIR=/python \
  UV_PYTHON_PREFERENCE=only-managed \
  UV_PROJECT_ENVIRONMENT=/app/.venv \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy
RUN uv python install ${PYTHON_VERSION} \
  # the managed CPython ships pip, never run here (uv builds the venv, distroless has no
  # shell); its vendored msgpack, urllib3 and pkg_resources are what Trivy flags
  && rm -rf /python/cpython-*/lib/python3*/site-packages/pip \
    /python/cpython-*/lib/python3*/site-packages/pip-*.dist-info \
    /python/cpython-*/bin/pip*
WORKDIR /src
# dependencies first: this layer is reused until uv.lock changes
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --locked --no-dev --no-install-project --python ${PYTHON_VERSION}
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --locked --no-dev --no-editable --python ${PYTHON_VERSION}
# an empty mount point for the exports, owned by the runtime user (distroless has no mkdir)
RUN mkdir -p /data

FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=build /python /python
COPY --from=build /app/.venv /app/.venv
COPY --from=build --chown=nonroot:nonroot /data /data
ENV PATH=/app/.venv/bin:$PATH \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  XERSCOPE_DATA=/data \
  STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
USER nonroot
WORKDIR /app
EXPOSE 8501
# Inside the container the app must listen on all interfaces to be reachable at all; what
# reaches it is decided where the port is published (compose.yaml binds 127.0.0.1 only).
# Runtime on the same Debian release as the build stage (trixie = Debian 13).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"]
ENTRYPOINT ["/app/.venv/bin/xerscope"]
CMD ["app", "--host", "0.0.0.0", "--port", "8501"]
