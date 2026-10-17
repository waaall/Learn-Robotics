# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${PYTHON_IMAGE} AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install --only-binary=:all: --require-hashes -r requirements.lock

FROM dependencies AS verifier
COPY requirements-test.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --only-binary=:all: --require-hashes -r requirements-test.lock
COPY src ./src
COPY tests ./tests
ENV PYTHONPATH=/app/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN /opt/venv/bin/python -m unittest discover -s tests -v \
    && /opt/venv/bin/python -c "from robotics_lab.diagnostics import viewer_capability; r = viewer_capability(); print(r); assert r['available'], r"

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/src \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ROBOTICS_LAB_DATA_DIR=/var/lib/robotics-lab \
    ROBOTICS_LAB_VIEWER_PORT=8081 ROBOTICS_LAB_VIEWER_URL=/viewer/
WORKDIR /app
RUN groupadd --gid 10001 robotics \
    && useradd --uid 10001 --gid robotics --no-create-home --shell /usr/sbin/nologin robotics \
    && mkdir -p /var/lib/robotics-lab \
    && chown robotics:robotics /var/lib/robotics-lab
COPY --from=dependencies /opt/venv /opt/venv
# 依赖 verifier 的源码副本，确保运行镜像构建经过测试和 WebViewer 组件检查。
COPY --from=verifier /app/src ./src
USER 10001:10001
EXPOSE 8000 8081
STOPSIGNAL SIGTERM
HEALTHCHECK --start-period=20s --interval=15s --timeout=5s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read()"]
CMD ["python", "-m", "robotics_lab", "serve", "--host", "0.0.0.0", "--port", "8000"]
