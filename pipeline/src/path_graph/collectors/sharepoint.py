from __future__ import annotations

import time
from typing import Any, Iterator
from urllib.parse import quote

import httpx

from path_graph.collectors.ms_graph_auth import GraphTokenProvider

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointError(Exception):
    pass


class SharePointClient:
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
            raise SharePointError(
                f"Graph {resp.status_code}: {detail} — check app permissions/admin consent"
            )
        if resp.status_code == 404:
            detail = resp.json().get("error", {}).get("message", resp.text)
            raise SharePointError(f"Graph 404: {detail}")
        resp.raise_for_status()
        return resp

    def resolve_site(self, site_path: str) -> dict[str, Any]:
        url = f"{GRAPH_BASE}/sites/{site_path}"
        return self._request("GET", url).json()

    def resolve_drive(self, site_id: str, drive_name: str) -> dict[str, Any]:
        url = f"{GRAPH_BASE}/sites/{site_id}/drives"
        drives = self._request("GET", url).json().get("value", [])
        needle = drive_name.lower()
        for drive in drives:
            name = (drive.get("name") or "").lower()
            web = (drive.get("webUrl") or "").lower()
            if name == needle or needle in web or "shared%20documents" in web and needle == "documents":
                return drive
        names = [d.get("name") for d in drives]
        raise SharePointError(f"drive not found: {drive_name!r} (available: {names})")

    def list_folder_items(self, drive_id: str, folder_path: str) -> list[dict[str, Any]]:
        encoded = quote(folder_path, safe="/")
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}:/children"
        items: list[dict[str, Any]] = []
        while url:
            data = self._request("GET", url).json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            if url:
                time.sleep(self._page_sleep)
        return items

    def list_folder_recursive(
        self,
        drive_id: str,
        folder_path: str,
    ) -> Iterator[dict[str, Any]]:
        for item in self.list_folder_items(drive_id, folder_path):
            if "folder" in item:
                child_path = f"{folder_path}/{item['name']}".lstrip("/")
                yield from self.list_folder_recursive(drive_id, child_path)
            elif "file" in item:
                yield item

    def download_item(self, drive_id: str, item_id: str) -> bytes:
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
        return self._request("GET", url).content
