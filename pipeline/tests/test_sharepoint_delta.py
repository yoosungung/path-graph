from unittest.mock import MagicMock

from path_graph.collectors.sharepoint import SharePointClient


def test_list_delta_pagination():
    client = SharePointClient(MagicMock(), http_client=MagicMock())
    client._request = MagicMock(
        side_effect=[
            MagicMock(
                json=lambda: {
                    "value": [{"id": "1", "file": {"mimeType": "application/pdf"}, "name": "a.pdf"}],
                    "@odata.nextLink": "https://graph.microsoft.com/next",
                }
            ),
            MagicMock(
                json=lambda: {
                    "value": [{"id": "2", "deleted": {}}],
                    "@odata.deltaLink": "https://graph.microsoft.com/delta/final",
                }
            ),
        ]
    )
    items, link = client.list_delta("drive-1", folder_path="Shared")
    assert len(items) == 2
    assert link == "https://graph.microsoft.com/delta/final"
