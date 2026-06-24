from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import BaseClient

from path_graph.config import Settings, get_settings


def clear_blob_store_cache() -> None:
    _s3_store_cache.clear()


def s3_client_kwargs(settings: Settings) -> dict:
    from botocore.config import Config

    config_kwargs: dict = {
        "signature_version": "s3v4",
        "request_checksum_calculation": "when_required",
        "response_checksum_validation": "when_required",
        "retries": {"max_attempts": 10, "mode": "adaptive"},
    }
    if settings.s3_endpoint_url:
        # Garage/MinIO/NCP: path-style avoids virtual-host 400 on custom endpoints.
        config_kwargs["s3"] = {"addressing_style": "path"}

    kwargs: dict = {
        "region_name": settings.s3_region,
        "config": Config(**config_kwargs),
    }
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    if settings.s3_access_key:
        kwargs["aws_access_key_id"] = settings.s3_access_key
    if settings.s3_secret_key:
        kwargs["aws_secret_access_key"] = settings.s3_secret_key
    return kwargs


class BlobStore(Protocol):
    def put_bytes(self, key: str, data: bytes, *, skip_if_exists: bool = False) -> str: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def uri_for(self, key: str) -> str: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / key

    def put_bytes(self, key: str, data: bytes, *, skip_if_exists: bool = False) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if skip_if_exists and path.exists():
            return self.uri_for(key)
        path.write_bytes(data)
        return self.uri_for(key)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def uri_for(self, key: str) -> str:
        return f"file://{self._path(key).resolve()}"


class S3BlobStore:
    def __init__(self, client: BaseClient, bucket: str, endpoint: str) -> None:
        self._client = client
        self._bucket = bucket
        self._endpoint = endpoint.rstrip("/")

    def put_bytes(self, key: str, data: bytes, *, skip_if_exists: bool = False) -> str:
        if skip_if_exists:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return self.uri_for(key)
            except self._client.exceptions.ClientError:
                pass
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return self.uri_for(key)

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except self._client.exceptions.ClientError:
            return False

    def uri_for(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"


_s3_store_cache: dict[tuple[str, str, str, str, str], S3BlobStore] = {}


def make_blob_store(settings: Settings | None = None) -> BlobStore:
    s = settings or get_settings()
    if s.pipeline_storage_backend == "s3":
        cache_key = (
            s.s3_endpoint_url,
            s.s3_bucket,
            s.s3_access_key,
            s.s3_secret_key,
            s.s3_region,
        )
        cached = _s3_store_cache.get(cache_key)
        if cached is not None:
            return cached
        client = boto3.client("s3", **s3_client_kwargs(s))
        store = S3BlobStore(client, s.s3_bucket, s.s3_endpoint_url)
        _s3_store_cache[cache_key] = store
        return store
    return LocalBlobStore(Path(s.pipeline_storage_dir))


def write_jsonl(path_key: str, lines: list[dict], store: BlobStore) -> str:
    body = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"
    return store.put_bytes(path_key, body.encode("utf-8"))


def read_jsonl(store: BlobStore, key: str) -> list[dict]:
    raw = store.get_bytes(key).decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]
