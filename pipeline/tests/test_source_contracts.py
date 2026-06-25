from __future__ import annotations

from datetime import UTC, datetime

import pytest

from path_graph.contracts.source import (
    SourceCreate,
    SourceDriver,
    SourceProfile,
    row_to_profile,
)
from constants import PROJECT_ID


def test_row_to_profile():
    now = datetime.now(UTC)
    row = (
        "dev",
        "11111111-1111-4111-8111-111111111111",
        PROJECT_ID,
        "kms",
        "sharepoint",
        "sharepoint:kms",
        {"folder": "회사규정"},
        True,
        None,
        None,
        "batch-1",
        now,
        "submitted",
        now,
        now,
    )
    profile = row_to_profile(row)
    assert profile.tenant == "dev"
    assert profile.project_id == PROJECT_ID
    assert profile.name == "kms"
    assert profile.driver == SourceDriver.SHAREPOINT
    assert profile.config["folder"] == "회사규정"


def test_source_create_requires_name():
    with pytest.raises(ValueError):
        SourceCreate(
            project_id=PROJECT_ID,
            name="  ",
            driver=SourceDriver.SHAREPOINT,
            source_id="sp:kms",
        )


def test_source_driver_includes_manual():
    assert SourceDriver.MANUAL.value == "manual"


def test_source_profile_roundtrip_fields():
    p = SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id=PROJECT_ID,
        name="gdrive-reports",
        driver=SourceDriver.GDRIVE,
        source_id="gdrive:reports",
        config={"folder_path": "Reports"},
    )
    assert p.enabled is True
