# syntax=docker/dockerfile:1
# 前端仅在构建阶段使用 Node；最终镜像与原生部署运行同一个单端口应用。
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install --only-binary=:all: --require-hashes -r requirements.lock

FROM dependencies AS verifier
COPY src ./src
COPY tests ./tests
COPY lab.sh ./
ENV PYTHONPATH=/app/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN /opt/venv/bin/python -m unittest discover -s tests -v \
    && /opt/venv/bin/python -m robotics_lab doctor

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/src \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ROBOTICS_LAB_HOST=0.0.0.0 ROBOTICS_LAB_PORT=8000 \
    ROBOTICS_LAB_DATA_DIR=/var/lib/robotics-lab
WORKDIR /app
RUN groupadd --gid 10001 robotics \
    && useradd --uid 10001 --gid robotics --no-create-home --shell /usr/sbin/nologin robotics \
    && mkdir -p /var/lib/robotics-lab \
    && chown robotics:robotics /var/lib/robotics-lab
COPY --from=dependencies /opt/venv /opt/venv
# 运行镜像依赖 verifier，构建必须通过回归测试和官方组件检查。
COPY --from=verifier /app/src ./src
COPY --from=frontend /web/dist ./frontend/dist
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --start-period=20s --interval=15s --timeout=5s --retries=5 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['ROBOTICS_LAB_PORT'] + '/api/health', timeout=2).read()"]
CMD ["python", "-m", "robotics_lab", "serve"]
