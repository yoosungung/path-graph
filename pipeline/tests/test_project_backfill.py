from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from path_graph.admin.projects import ProjectStore
from path_graph.admin.sources import SourceStore
from path_graph.contracts.project import ProjectProfile
from constants import PROJECT_ID


def _default_project() -> ProjectProfile:
    return ProjectProfile(
        tenant="dev",
        id=PROJECT_ID,
        slug="default",
        name="Default",
    )


@patch("path_graph.admin.projects.psycopg.connect")
def test_backfill_orphan_project_ids_creates_default_and_updates(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.rowcount = 2

    with patch.object(
        ProjectStore,
        "ensure_default_project",
        return_value=_default_project(),
    ) as ensure:
        store = ProjectStore("postgresql://localhost/test")
        updated = store.backfill_orphan_project_ids("dev")

    ensure.assert_called_once_with("dev")
    assert updated == 6
    update_calls = [
        c
        for c in conn.execute.call_args_list
        if "UPDATE path_graph." in str(c.args[0]) and "project_id IS NULL" in str(c.args[0])
    ]
    assert len(update_calls) == 3
    for update_call in update_calls:
        assert update_call.args[1][0] == PROJECT_ID
        assert update_call.args[1][1] == "dev"
    conn.commit.assert_called_once()


@patch("path_graph.admin.sources.ProjectStore")
@patch("path_graph.admin.sources.psycopg.connect")
def test_list_sources_backfills_before_read(mock_connect, mock_project_store_cls):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = [
        (
            "dev",
            "11111111-1111-4111-8111-111111111111",
            PROJECT_ID,
            "kms",
            "sharepoint",
            "sharepoint:kms",
            {},
            True,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    ]
    backfill = MagicMock()
    mock_project_store_cls.return_value.backfill_orphan_project_ids = backfill

    store = SourceStore("postgresql://localhost/test")
    profiles = store.list_sources("dev")

    backfill.assert_called_once_with("dev")
    assert len(profiles) == 1
    assert profiles[0].project_id == PROJECT_ID
