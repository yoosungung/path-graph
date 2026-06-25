from __future__ import annotations

from pathlib import Path
from typing import Any

from path_graph.collectors.gdrive import GDriveClient
from path_graph.collectors.gdrive_auth import make_gdrive_token_provider
from path_graph.collectors.ms_graph_auth import make_onedrive_token_provider, make_token_provider
from path_graph.collectors.onedrive import OneDriveClient
from path_graph.collectors.sharepoint import SharePointClient
from path_graph.collectors.web import fetch_url, filename_from_url
from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest, s3_key_raw
from path_graph.ids import document_id, sha256_bytes
from path_graph.storage.blob import BlobStore, make_blob_store, write_jsonl


class GDriveCollector:
    """Collect files from a Google Drive folder via Drive API v3."""

    def __init__(self, client: GDriveClient | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or GDriveClient(make_gdrive_token_provider(self._settings))

    def _list_files(
        self,
        *,
        folder_id: str | None,
        folder_path: str | None,
        recursive: bool,
        extensions: set[str] | None,
    ) -> list[dict[str, Any]]:
        ext_set = extensions or _parse_extensions(self._settings.gdrive_file_extensions)
        resolved = self._client.resolve_folder_id(
            folder_id or self._settings.gdrive_folder_id or None,
            folder_path if folder_path is not None else self._settings.gdrive_folder_path or None,
        )
        if recursive:
            items = list(self._client.list_folder_recursive(resolved))
        else:
            items = [
                i
                for i in self._client.list_children(resolved)
                if i.get("mimeType") != "application/vnd.google-apps.folder"
            ]
        if ext_set:
            items = _filter_gdrive_extensions(items, ext_set)
        return items

    def enumerate_files(
        self,
        *,
        folder_id: str | None = None,
        folder_path: str | None = None,
        recursive: bool = True,
        extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self._list_files(
            folder_id=folder_id,
            folder_path=folder_path,
            recursive=recursive,
            extensions=extensions,
        )

    def collect_folder(
        self,
        tenant: str,
        project_id: str,
        source_id: str,
        *,
        folder_id: str | None = None,
        folder_path: str | None = None,
        recursive: bool = True,
        extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        items = self._list_files(
            folder_id=folder_id,
            folder_path=folder_path,
            recursive=recursive,
            extensions=extensions,
        )
        metas: list[dict[str, Any]] = []
        for item in items:
            data, filename, mime = self._client.download_file(
                item["id"], item.get("mimeType", ""), item.get("name", "file")
            )
            metas.append(store_raw(data, filename, tenant, project_id, source_id, mime))
        return metas

    def collect_file(self, file_id: str, tenant: str, project_id: str, source_id: str) -> dict[str, Any]:
        meta = self._client.get_file_metadata(file_id)
        data, filename, mime = self._client.download_file(
            meta["id"], meta.get("mimeType", ""), meta.get("name", "file")
        )
        return store_raw(data, filename, tenant, project_id, source_id, mime)

    def write_batch_manifest(self, tenant: str, batch_id: str, items: list[dict[str, Any]]) -> str:
        return write_batch_manifest(tenant, batch_id, items, self._settings)


class OneDriveCollector:
    """Collect files from personal OneDrive via Microsoft Graph /me/drive."""

    def __init__(self, client: OneDriveClient | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or OneDriveClient(make_onedrive_token_provider(self._settings))

    def _list_files(
        self,
        *,
        folder: str | None,
        recursive: bool,
        extensions: set[str] | None,
    ) -> list[dict[str, Any]]:
        folder_path = folder if folder is not None else self._settings.onedrive_folder
        ext_set = extensions or _parse_extensions(self._settings.onedrive_file_extensions)
        if recursive:
            items = list(self._client.list_folder_recursive(folder_path))
        else:
            items = [i for i in self._client.list_folder_items(folder_path) if "file" in i]
        if ext_set:
            items = [
                i
                for i in items
                if any((i.get("name") or "").lower().endswith(ext) for ext in ext_set)
            ]
        return items

    def enumerate_files(
        self,
        *,
        folder: str | None = None,
        recursive: bool = True,
        extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self._list_files(folder=folder, recursive=recursive, extensions=extensions)

    def collect_folder(
        self,
        tenant: str,
        project_id: str,
        source_id: str,
        *,
        folder: str | None = None,
        recursive: bool = True,
        extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        items = self._list_files(folder=folder, recursive=recursive, extensions=extensions)
        metas: list[dict[str, Any]] = []
        for item in items:
            name = item.get("name", "")
            mime = item.get("file", {}).get("mimeType", "application/octet-stream")
            data = self._client.download_item(item["id"])
            metas.append(store_raw(data, name, tenant, project_id, source_id, mime))
        return metas

    def collect_file(self, item_id: str, tenant: str, project_id: str, source_id: str) -> dict[str, Any]:
        meta = self._client.get_item_metadata(item_id)
        name = meta.get("name", "file")
        mime = meta.get("file", {}).get("mimeType", "application/octet-stream")
        data = self._client.download_item(item_id)
        return store_raw(data, name, tenant, project_id, source_id, mime)

    def write_batch_manifest(self, tenant: str, batch_id: str, items: list[dict[str, Any]]) -> str:
        return write_batch_manifest(tenant, batch_id, items, self._settings)


class AgentChatCollector:
    """Export agent conversation JSON from path or S3."""

    def collect_json(self, export_path: Path, tenant: str, project_id: str, source_id: str) -> dict[str, Any]:
        data = export_path.read_bytes()
        return store_raw(data, "conversation.json", tenant, project_id, source_id, "application/json")


class SharePointCollector:
    """Collect files from a SharePoint document library folder via Microsoft Graph."""

    def __init__(self, client: SharePointClient | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if client is not None:
            self._client = client
        else:
            self._client = SharePointClient(make_token_provider(self._settings))

    def _resolve_folder_items(
        self,
        *,
        site: str | None,
        drive_name: str | None,
        folder: str | None,
        recursive: bool,
        extensions: set[str] | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        site_path = site or self._settings.sharepoint_site
        drive = drive_name or self._settings.sharepoint_drive_name
        folder_path = folder or self._settings.sharepoint_folder
        ext_set = extensions or _parse_extensions(self._settings.sharepoint_file_extensions)

        site_info = self._client.resolve_site(site_path)
        drive_info = self._client.resolve_drive(site_info["id"], drive)
        drive_id = drive_info["id"]

        if recursive:
            items = list(self._client.list_folder_recursive(drive_id, folder_path))
        else:
            items = [i for i in self._client.list_folder_items(drive_id, folder_path) if "file" in i]

        if ext_set:
            items = [
                i
                for i in items
                if any((i.get("name") or "").lower().endswith(ext) for ext in ext_set)
            ]
        return drive_id, items

    def enumerate_files(
        self,
        *,
        site: str | None = None,
        drive_name: str | None = None,
        folder: str | None = None,
        recursive: bool = True,
        extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        _, items = self._resolve_folder_items(
            site=site,
            drive_name=drive_name,
            folder=folder,
            recursive=recursive,
            extensions=extensions,
        )
        return items

    def collect_folder(
        self,
        tenant: str,
        project_id: str,
        source_id: str,
        *,
        site: str | None = None,
        drive_name: str | None = None,
        folder: str | None = None,
        recursive: bool = True,
        extensions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        drive_id, items = self._resolve_folder_items(
            site=site,
            drive_name=drive_name,
            folder=folder,
            recursive=recursive,
            extensions=extensions,
        )
        metas: list[dict[str, Any]] = []
        for item in items:
            name = item.get("name", "")
            mime = item.get("file", {}).get("mimeType", "application/octet-stream")
            data = self._client.download_item(drive_id, item["id"])
            metas.append(store_raw(data, name, tenant, project_id, source_id, mime))
        return metas

    def collect_delta(
        self,
        tenant: str,
        project_id: str,
        source_id: str,
        *,
        site: str | None = None,
        drive_name: str | None = None,
        folder: str | None = None,
        delta_link: str | None = None,
        extensions: set[str] | None = None,
    ) -> dict[str, Any]:
        """Incremental sync via Graph delta. Returns metas, purged, new delta_link."""
        from path_graph.lifecycle.purge import purge_document
        from path_graph.meta.pg import PgMetaStore

        site_path = site or self._settings.sharepoint_site
        drive = drive_name or self._settings.sharepoint_drive_name
        folder_path = folder or self._settings.sharepoint_folder
        ext_set = extensions or _parse_extensions(self._settings.sharepoint_file_extensions)

        site_info = self._client.resolve_site(site_path)
        drive_info = self._client.resolve_drive(site_info["id"], drive)
        drive_id = drive_info["id"]

        items, new_link = self._client.list_delta(
            drive_id, delta_link=delta_link, folder_path=folder_path
        )

        metas: list[dict[str, Any]] = []
        purged: list[str] = []
        pg = PgMetaStore(self._settings.path_graph_dsn) if self._settings.path_graph_dsn else None

        for item in items:
            if item.get("deleted"):
                if pg is None:
                    continue
                remote_id = item.get("id", "")
                docs = pg.list_documents_for_project(
                    tenant, project_id, source_id=source_id
                )
                for doc in docs:
                    if remote_id and remote_id in (doc.get("s3_raw_uri") or ""):
                        purge_document(
                            tenant,
                            project_id,
                            doc["document_id"],
                            reason="sharepoint_delta_delete",
                            settings=self._settings,
                        )
                        purged.append(doc["document_id"])
                continue
            if "file" not in item:
                continue
            name = item.get("name", "")
            if ext_set and not any(name.lower().endswith(ext) for ext in ext_set):
                continue
            mime = item.get("file", {}).get("mimeType", "application/octet-stream")
            data = self._client.download_item(drive_id, item["id"])
            meta = store_raw(data, name, tenant, project_id, source_id, mime)
            metas.append(meta)

        return {
            "items": metas,
            "purged_document_ids": purged,
            "delta_link": new_link,
            "project_id": project_id,
        }

    def write_batch_manifest(self, tenant: str, batch_id: str, items: list[dict[str, Any]]) -> str:
        return write_batch_manifest(tenant, batch_id, items, self._settings)


def write_batch_manifest(
    tenant: str,
    batch_id: str,
    items: list[dict[str, Any]],
    settings: Settings | None = None,
) -> str:
    lines = [
        {
            "tenant": item["tenant"],
            "project_id": item["project_id"],
            "source_id": item["source_id"],
            "content_hash": item["content_hash"],
            "document_id": item["document_id"],
            "s3_raw_uri": item["s3_raw_uri"],
            "filename": item["filename"],
        }
        for item in items
    ]
    key = s3_key_batch_manifest(tenant, batch_id)
    store = make_blob_store(settings or get_settings())
    return write_jsonl(key, lines, store)


def _parse_extensions(raw: str) -> set[str]:
    return {
        e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
        for e in raw.split(",")
        if e.strip()
    }


def _filter_gdrive_extensions(items: list[dict[str, Any]], ext_set: set[str]) -> list[dict[str, Any]]:
    from path_graph.collectors.gdrive import EXPORT_TARGETS

    filtered: list[dict[str, Any]] = []
    for item in items:
        mime = item.get("mimeType", "")
        name = (item.get("name") or "").lower()
        if any(name.endswith(ext) for ext in ext_set):
            filtered.append(item)
            continue
        if mime in EXPORT_TARGETS and ext_set & {EXPORT_TARGETS[mime][1]}:
            filtered.append(item)
    return filtered


def store_raw(
    data: bytes,
    filename: str,
    tenant: str,
    project_id: str,
    source_id: str,
    mime: str,
    *,
    settings: Settings | None = None,
    store: BlobStore | None = None,
) -> dict[str, Any]:
    content_hash = sha256_bytes(data)
    doc_id = document_id(tenant, project_id, content_hash)
    key = s3_key_raw(tenant, project_id, source_id, content_hash, filename)
    blob = store or make_blob_store(settings or get_settings())
    uri = blob.put_bytes(key, data, skip_if_exists=True)
    return {
        "tenant": tenant,
        "project_id": project_id,
        "source_id": source_id,
        "content_hash": content_hash,
        "document_id": doc_id,
        "s3_raw_uri": uri,
        "filename": filename,
        "mime": mime,
    }


def collect_web(url: str, tenant: str, project_id: str, source_id: str = "web") -> dict[str, Any]:
    data, mime = fetch_url(url)
    filename = filename_from_url(url)
    return store_raw(data, filename, tenant, project_id, source_id, mime)


def collect_local_file(path: Path, tenant: str, project_id: str, source_id: str) -> dict[str, Any]:
    data = path.read_bytes()
    return store_raw(data, path.name, tenant, project_id, source_id, "application/octet-stream")
