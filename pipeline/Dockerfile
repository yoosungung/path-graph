ARG RHWP_BATCH_VERSION=0.7.15
ARG RHWP_BATCH_ARCH=x86_64-unknown-linux-gnu

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fonts-nanum \
        fonts-nanum-coding \
    && rm -rf /var/lib/apt/lists/*

ARG RHWP_BATCH_VERSION
ARG RHWP_BATCH_ARCH
RUN set -eu; \
    base="rhwp-batch-v${RHWP_BATCH_VERSION}-${RHWP_BATCH_ARCH}"; \
    url="https://github.com/yoosungung/rhwp_batch/releases/download/v${RHWP_BATCH_VERSION}"; \
    cd /tmp; \
    curl -fsSL -o "${base}.tar.gz" "${url}/${base}.tar.gz"; \
    curl -fsSL -o "${base}.tar.gz.sha256" "${url}/${base}.tar.gz.sha256"; \
    sha256sum -c "${base}.tar.gz.sha256"; \
    tar -xzf "${base}.tar.gz" -C /usr/local/bin; \
    chmod +x /usr/local/bin/rhwp-batch; \
    rm -f "${base}.tar.gz" "${base}.tar.gz.sha256"

WORKDIR /app
COPY pipeline/pyproject.toml pipeline/
COPY pipeline/src pipeline/src
RUN pip install --no-cache-dir ./pipeline

ENTRYPOINT ["python"]
