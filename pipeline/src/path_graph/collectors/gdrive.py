from __future__ import annotations

import time
from typing import Any, Iterator
from urllib.parse import quote

import httpx

from path_graph.collectors.gdrive_auth import GDriveTokenProvider

DRIVE_API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
EXPORT_TARGETS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


class GDriveError(Exception):
    pass


class GDriveClient:
    def __init__(
        self,
        token_provider: GDriveTokenProvider,
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
        if resp.status_code in (401, 403):
            detail = resp.json().get("error", {}).get("message", resp.text)
            raise GDriveError(f"Drive {resp.status_code}: {detail}")
        if resp.status_code == 404:
            raise GDriveError("Drive 404: resource not found")
        resp.raise_for_status()
        return resp

    def resolve_folder_id(self, folder_id: str | None, folder_path: str | None) -> str:
        if folder_id:
            return folder_id
        if not folder_path:
            return "root"
        parent = "root"
        for segment in [p for p in folder_path.split("/") if p]:
            q = (
                f"name = '{segment.replace(chr(39), chr(92)+chr(39))}' "
                f"and '{parent}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
            )
            url = f"{DRIVE_API}/files?q={quote(q)}&fields=files(id,name)"
            files = self._request("GET", url).json().get("files", [])
            if not files:
                raise GDriveError(f"folder not found: {segment!r} under {parent!r}")
            parent = files[0]["id"]
        return parent

    def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        q = f"'{folder_id}' in parents and trashed = false"
        url = (
            f"{DRIVE_API}/files?q={quote(q)}"
            "&fields=nextPageToken,files(id,name,mimeType)"
        )
        items: list[dict[str, Any]] = []
        while url:
            data = self._request("GET", url).json()
            items.extend(data.get("files", []))
            token = data.get("nextPageToken")
            if not token:
                break
            url = (
                f"{DRIVE_API}/files?q={quote(q)}"
                f"&pageToken={token}&fields=nextPageToken,files(id,name,mimeType)"
            )
            time.sleep(self._page_sleep)
        return items

    def download_file(self, file_id: str, mime_type: str, name: str) -> tuple[bytes, str, str]:
        if mime_type in EXPORT_TARGETS:
            export_mime, ext = EXPORT_TARGETS[mime_type]
            url = f"{DRIVE_API}/files/{file_id}/export?mimeType={quote(export_mime)}"
            base, _, _ = name.rpartition(".")
            filename = (base or name) + ext
            mime = export_mime
        else:
            url = f"{DRIVE_API}/files/{file_id}?alt=media"
            filename = name
            mime = mime_type or "application/octet-stream"
        content = self._request("GET", url).content
        return content, filename, mime

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        url = f"{DRIVE_API}/files/{file_id}?fields=id,name,mimeType"
        return self._request("GET", url).json()

    def list_folder_recursive(self, folder_id: str) -> Iterator[dict[str, Any]]:
        for item in self.list_children(folder_id):
            mime = item.get("mimeType", "")
            if mime == FOLDER_MIME:
                yield from self.list_folder_recursive(item["id"])
            else:
                yield item
