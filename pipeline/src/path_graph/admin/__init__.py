"""Admin console domain — sources CRUD, collect/run orchestration, manual uploads.

Internal / Argo use. External consumers import path_graph.console instead.
"""

from path_graph.admin.runner import collect_source, manifest_lines_to_json, probe_source
from path_graph.admin.sources import SourceStore, make_source_store
from path_graph.admin.uploads import (
    build_ingest_manifest,
    list_documents_for_project,
    list_documents_for_source,
    upload_raw_file,
    upload_raw_files,
)

__all__ = [
    "SourceStore",
    "build_ingest_manifest",
    "collect_source",
    "list_documents_for_project",
    "list_documents_for_source",
    "make_source_store",
    "manifest_lines_to_json",
    "probe_source",
    "upload_raw_file",
    "upload_raw_files",
]
