from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class SourceDriver(StrEnum):
    SHAREPOINT = "sharepoint"
    GDRIVE = "gdrive"
    ONEDRIVE = "onedrive"
    MANUAL = "manual"


class CollectSyncMode(StrEnum):
    """Source collection strategy (ROADMAP D5)."""

    DELTA = "delta"
    FULL = "full"


def resolve_collect_sync_mode(
    profile: SourceProfile,
    override: CollectSyncMode | str | None = None,
) -> CollectSyncMode:
    if override is not None:
        return CollectSyncMode(str(override))
    raw = profile.config.get("sync_mode", CollectSyncMode.DELTA.value)
    try:
        return CollectSyncMode(str(raw))
    except ValueError as exc:
        raise ValueError(f"invalid sync_mode for source {profile.id}: {raw!r}") from exc


class SourceProfile(BaseModel):
    tenant: str
    id: str
    project_id: str
    name: str
    driver: SourceDriver
    source_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    credential_id: str | None = None
    enabled: bool = True
    schedule_cron: str | None = None
    last_batch_id: str | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("tenant", "name", "source_id", "project_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class SourceCreate(BaseModel):
    project_id: str
    name: str
    driver: SourceDriver
    source_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    credential_id: str | None = None
    enabled: bool = True
    schedule_cron: str | None = None

    @field_validator("project_id", "name", "source_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class SourceUpdate(BaseModel):
    source_id: str | None = None
    config: dict[str, Any] | None = None
    credential_id: str | None = None
    enabled: bool | None = None
    schedule_cron: str | None = None

    @field_validator("source_id")
    @classmethod
    def _source_id_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


def row_to_profile(row: tuple) -> SourceProfile:
    """Map a DB row tuple to SourceProfile."""
    (
        tenant,
        sid,
        project_id,
        name,
        driver,
        source_id,
        config,
        enabled,
        schedule_cron,
        credential_id,
        last_batch_id,
        last_run_at,
        last_run_status,
        created_at,
        updated_at,
    ) = row
    cfg = config if isinstance(config, dict) else {}
    return SourceProfile(
        tenant=tenant,
        id=str(sid) if not isinstance(sid, str) else sid,
        project_id=str(project_id) if project_id else "",
        name=name,
        driver=SourceDriver(driver),
        source_id=source_id,
        config=cfg,
        enabled=bool(enabled),
        schedule_cron=schedule_cron,
        credential_id=str(credential_id) if credential_id else None,
        last_batch_id=last_batch_id,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
        created_at=created_at,
        updated_at=updated_at,
    )


def new_source_id() -> str:
    return str(uuid4())
