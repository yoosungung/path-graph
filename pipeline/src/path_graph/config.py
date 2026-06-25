from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env.dev.local"),
            str(_REPO_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"

    path_graph_tenant: str = ""  # PATH_GRAPH_TENANT
    path_graph_dsn: str = ""  # PATH_GRAPH_DSN — psycopg (postgresql://)

    pipeline_storage_backend: str = "local"  # local | s3
    pipeline_storage_dir: str = ".data/pipeline"
    s3_endpoint_url: str = ""
    s3_bucket: str = "path-graph"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""

    nebula_host: str = "127.0.0.1"
    nebula_port: int = 9669
    nebula_user: str = "root"
    nebula_password: str = "nebula"

    envoy_url: str = "http://127.0.0.1:8084"
    pipeline_agent_access_token: str = ""  # PIPELINE_AGENT_ACCESS_TOKEN

    embedding_model: str = "BAAI/bge-m3"  # EMBEDDING_MODEL
    embedding_dim: int = 1024  # EMBEDDING_DIM — Qdrant cosine
    embedding_base_url: str = (
        "http://bge-m3-tei.llm-serving.svc.cluster.local:8080"  # EMBEDDING_BASE_URL
    )
    embedding_api_key: str = ""  # EMBEDDING_API_KEY (optional)
    embedding_timeout: float = 120.0  # EMBEDDING_TIMEOUT
    embedding_batch_size: int = 8  # EMBEDDING_BATCH_SIZE — TEI CPU backend max

    chunk_max_chars: int = 1000  # CHUNK_MAX_CHARS — embed context (~1k tokens) safe limit

    community_max_cluster_size: int = 10  # COMMUNITY_MAX_CLUSTER_SIZE
    community_use_lcc: bool = True  # COMMUNITY_USE_LCC
    community_seed: int = 0xDEADBEEF  # COMMUNITY_SEED
    graph_context_max_entities: int = 50  # GRAPH_CONTEXT_MAX_ENTITIES

    rhwp_batch_bin: str = "rhwp-batch"

    ms_tenant_id: str = ""  # MS_TENANT_ID
    ms_client_id: str = ""  # MS_CLIENT_ID
    ms_client_secret: str = ""  # MS_CLIENT_SECRET — app auth
    ms_refresh_token: str = ""  # MS_REFRESH_TOKEN — delegated auth
    ms_auth_mode: str = "app"  # MS_AUTH_MODE — app | delegated | device
    sharepoint_site: str = "tripodoffice.sharepoint.com:/sites/kms"
    sharepoint_drive_name: str = "Documents"
    sharepoint_folder: str = "회사규정"
    sharepoint_file_extensions: str = (
        ".pdf,.doc,.docx,.hwp,.hwpx,.txt,.md,.ppt,.pptx"
    )

    gdrive_client_id: str = ""  # GDRIVE_CLIENT_ID
    gdrive_client_secret: str = ""  # GDRIVE_CLIENT_SECRET
    gdrive_refresh_token: str = ""  # GDRIVE_REFRESH_TOKEN
    gdrive_folder_id: str = ""  # GDRIVE_FOLDER_ID
    gdrive_folder_path: str = ""  # GDRIVE_FOLDER_PATH — used when folder_id empty
    gdrive_file_extensions: str = (
        ".pdf,.doc,.docx,.hwp,.hwpx,.txt,.md,.ppt,.pptx,.xlsx"
    )

    onedrive_refresh_token: str = ""  # ONEDRIVE_REFRESH_TOKEN
    onedrive_folder: str = ""  # ONEDRIVE_FOLDER — path from drive root
    onedrive_file_extensions: str = (
        ".pdf,.doc,.docx,.hwp,.hwpx,.txt,.md,.ppt,.pptx"
    )

    @model_validator(mode="after")
    def _normalize_dsn_and_nebula(self) -> Settings:
        # agents-runtime wire-dev uses POSTGRES_DSN (asyncpg); path-graph uses psycopg.
        if not self.path_graph_dsn:
            legacy = os.environ.get("POSTGRES_DSN", "")
            if legacy:
                object.__setattr__(
                    self,
                    "path_graph_dsn",
                    legacy.replace("postgresql+asyncpg://", "postgresql://"),
                )

        # Optional NEBULA_URL=host:port (no scheme)
        nebula_url = os.environ.get("NEBULA_URL", "").strip()
        if nebula_url:
            host, _, port = nebula_url.partition(":")
            object.__setattr__(self, "nebula_host", host.strip())
            if port.strip().isdigit():
                object.__setattr__(self, "nebula_port", int(port.strip()))
        return self

    def require_tenant(self, tenant: str | None) -> str:
        t = (tenant or self.path_graph_tenant or "").strip()
        if not t:
            raise ValueError("tenant is required")
        return t


@lru_cache
def get_settings() -> Settings:
    return Settings()
