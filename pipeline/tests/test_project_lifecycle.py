"""Tests for project lifecycle async submission guards."""

from unittest.mock import MagicMock

import pytest

from path_graph.admin.lifecycle import (
    LIFECYCLE_BATCH_ID,
    ProjectLifecycleBusyError,
    assert_project_lifecycle_idle,
    clear_project_lifecycle_on_failure,
    mark_project_lifecycle_started,
)
from constants import PROJECT_ID


def test_lifecycle_batch_ids():
    assert LIFECYCLE_BATCH_ID["purge"] == "lifecycle:purge"
    assert LIFECYCLE_BATCH_ID["delete"] == "lifecycle:delete"


def test_assert_project_lifecycle_idle_allows_purged_for_delete_and_repurge():
    project_store = MagicMock()
    project_store.get_purge_state.return_value = "purged"
    source_store = MagicMock()
    source_store.has_active_lifecycle_run.return_value = False
    assert_project_lifecycle_idle(
        project_store, source_store, "dev", PROJECT_ID, operation="delete"
    )
    assert_project_lifecycle_idle(
        project_store, source_store, "dev", PROJECT_ID, operation="purge"
    )


def test_assert_project_lifecycle_idle_rejects_in_progress():
    project_store = MagicMock()
    project_store.get_purge_state.return_value = "purging"
    with pytest.raises(ProjectLifecycleBusyError, match="in progress"):
        assert_project_lifecycle_idle(
            project_store, MagicMock(), "dev", PROJECT_ID, operation="purge"
        )


def test_assert_project_lifecycle_idle_rejects_active_run():
    project_store = MagicMock()
    project_store.get_purge_state.return_value = None
    source_store = MagicMock()
    source_store.has_active_lifecycle_run.return_value = True
    with pytest.raises(ProjectLifecycleBusyError, match="active delete"):
        assert_project_lifecycle_idle(
            project_store, source_store, "dev", PROJECT_ID, operation="delete"
        )


def test_mark_and_clear_lifecycle_state():
    project_store = MagicMock()
    mark_project_lifecycle_started(project_store, "dev", PROJECT_ID, operation="delete")
    project_store.set_purge_state.assert_called_once_with("dev", PROJECT_ID, "deleting")
    project_store.clear_in_progress_purge_state.return_value = True
    assert clear_project_lifecycle_on_failure(project_store, "dev", PROJECT_ID) is True
