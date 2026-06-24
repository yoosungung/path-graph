from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.admin.credentials import CredentialStore
from path_graph.contracts.credential import CredentialCreate
from path_graph.contracts.source import SourceDriver


@patch("path_graph.admin.credentials.psycopg.connect")
def test_create_credential(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (
        "dev",
        "11111111-1111-4111-8111-111111111111",
        "gdrive-a",
        "gdrive",
        {},
        [],
        "pending",
        "path-graph-cred-dev-111111111111",
        None,
        None,
    )

    store = CredentialStore("postgresql://localhost/test")
    profile = store.create_credential(
        "dev",
        CredentialCreate(label="gdrive-a", driver=SourceDriver.GDRIVE),
    )
    assert profile.label == "gdrive-a"
    assert profile.driver == SourceDriver.GDRIVE
    assert profile.k8s_secret_name.startswith("path-graph-cred-")
