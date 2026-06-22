FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pipeline/pyproject.toml pipeline/
COPY pipeline/src pipeline/src
RUN pip install --no-cache-dir ./pipeline

ENTRYPOINT ["python"]
