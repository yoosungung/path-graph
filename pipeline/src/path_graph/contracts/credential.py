from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from path_graph.contracts.source import SourceDriver


class OAuthStatus(StrEnum):
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"


class CredentialProfile(BaseModel):
    tenant: str
    id: str
    label: str
    driver: SourceDriver
    config: dict[str, Any] = Field(default_factory=dict)
    secret_keys: list[str] = Field(default_factory=list)
    oauth_status: OAuthStatus = OAuthStatus.PENDING
    k8s_secret_name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("tenant", "label", "k8s_secret_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class CredentialCreate(BaseModel):
    label: str
    driver: SourceDriver
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def _label_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


def row_to_credential(row: tuple) -> CredentialProfile:
    (
        tenant,
        cid,
        label,
        driver,
        config,
        secret_keys,
        oauth_status,
        k8s_secret_name,
        created_at,
        updated_at,
    ) = row
    cfg = config if isinstance(config, dict) else {}
    keys = list(secret_keys) if secret_keys else []
    return CredentialProfile(
        tenant=tenant,
        id=str(cid) if not isinstance(cid, str) else cid,
        label=label,
        driver=SourceDriver(driver),
        config=cfg,
        secret_keys=keys,
        oauth_status=OAuthStatus(oauth_status),
        k8s_secret_name=k8s_secret_name,
        created_at=created_at,
        updated_at=updated_at,
    )


def new_credential_id() -> str:
    return str(uuid4())


def k8s_secret_name_for_credential(tenant: str, credential_id: str) -> str:
    """DNS-safe Secret name (max 63 chars)."""
    import re

    slug = re.sub(r"[^a-z0-9-]+", "-", tenant.lower()).strip("-") or "tenant"
    short_id = credential_id.replace("-", "")[:12]
    name = f"path-graph-cred-{slug}-{short_id}".lower()
    return name[:63].rstrip("-")


def refresh_token_env_key(driver: SourceDriver) -> str:
    if driver == SourceDriver.GDRIVE:
        return "GDRIVE_REFRESH_TOKEN"
    return "MS_REFRESH_TOKEN"
