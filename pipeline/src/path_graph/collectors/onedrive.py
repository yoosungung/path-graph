from __future__ import annotations

import time
from typing import Any, Iterator
from urllib.parse import quote

import httpx

from path_graph.collectors.ms_graph_auth import GraphTokenProvider

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OneDriveError(Exception):
    pass


class OneDriveClient:
    """Personal or business OneDrive via Graph /me/drive."""

    def __init__(
        self,
        token_provider: GraphTokenProvider,
        *,
        http_client: httpx.Client | None = None,
        page_sleep: float = 0.2,
    ) -> None:
        self._token_provider = token_provider
        self._page_sleep = page_sleep
        self._http = http_client or httpx.Client(timeout=120.0)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token_provider.get_token()}"
        resp = self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "2"))
            time.sleep(retry_after)
            headers["Authorization"] = f"Bearer {self._token_provider.get_token()}"
            resp = self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code in (401, 403):
            detail = resp.json().get("error", {}).get("message", resp.text)
            raise OneDriveError(
                f"Graph {resp.status_code}: {detail} — check Files.Read.All consent"
            )
        if resp.status_code == 404:
            detail = resp.json().get("error", {}).get("message", resp.text)
            raise OneDriveError(f"Graph 404: {detail}")
        resp.raise_for_status()
        return resp

    def list_folder_items(self, folder_path: str) -> list[dict[str, Any]]:
        encoded = quote(folder_path, safe="/") if folder_path else ""
        if encoded:
            url = f"{GRAPH_BASE}/me/drive/root:/{encoded}:/children"
        else:
            url = f"{GRAPH_BASE}/me/drive/root/children"
        items: list[dict[str, Any]] = []
        while url:
            data = self._request("GET", url).json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            if url:
                time.sleep(self._page_sleep)
        return items

    def list_folder_recursive(self, folder_path: str) -> Iterator[dict[str, Any]]:
        for item in self.list_folder_items(folder_path):
            if "folder" in item:
                child = f"{folder_path}/{item['name']}".strip("/") if folder_path else item["name"]
                yield from self.list_folder_recursive(child)
            elif "file" in item:
                yield item

    def get_item_metadata(self, item_id: str) -> dict[str, Any]:
        url = f"{GRAPH_BASE}/me/drive/items/{item_id}?select=id,name,file"
        return self._request("GET", url).json()

    def download_item(self, item_id: str) -> bytes:
        url = f"{GRAPH_BASE}/me/drive/items/{item_id}/content"
        return self._request("GET", url).content
