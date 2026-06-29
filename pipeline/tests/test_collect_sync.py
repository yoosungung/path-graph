from __future__ import annotations

import pytest

from path_graph.contracts.source import (
    CollectSyncMode,
    SourceDriver,
    SourceProfile,
    resolve_collect_sync_mode,
)
from constants import PROJECT_ID


def _sharepoint_profile(**config) -> SourceProfile:
    return SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id=PROJECT_ID,
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config=config,
    )


def test_resolve_collect_sync_mode_defaults_to_delta():
    profile = _sharepoint_profile(folder="회사규정")
    assert resolve_collect_sync_mode(profile) == CollectSyncMode.DELTA


def test_resolve_collect_sync_mode_from_config():
    profile = _sharepoint_profile(sync_mode="full")
    assert resolve_collect_sync_mode(profile) == CollectSyncMode.FULL


def test_resolve_collect_sync_mode_override_wins():
    profile = _sharepoint_profile(sync_mode="delta")
    assert resolve_collect_sync_mode(profile, CollectSyncMode.FULL) == CollectSyncMode.FULL


def test_resolve_collect_sync_mode_invalid_raises():
    profile = _sharepoint_profile(sync_mode="bogus")
    with pytest.raises(ValueError, match="sync_mode"):
        resolve_collect_sync_mode(profile)
