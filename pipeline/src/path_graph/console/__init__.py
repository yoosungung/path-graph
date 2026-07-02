"""Stable public API for external consumers (agents-runtime Console BFF, MCP images).

Import from this package only — not from path_graph.admin (internal / Argo steps).
"""

from path_graph.console.config import Settings, get_settings
from path_graph.console.contracts import (
    CredentialCreate,
    CredentialProfile,
    OAuthStatus,
    ProjectCreate,
    ProjectProfile,
    SourceCreate,
    SourceDriver,
    SourceProfile,
    SourceUpdate,
    refresh_token_env_key,
    s3_key_dead_letter,
)
from path_graph.console.credentials import CredentialStore, merge_credential_into_settings
from path_graph.console.downstream import (
    DownstreamBusyError,
    DownstreamValidationError,
    apply_graphrag_success,
    assert_project_graphrag_idle,
    prepare_graphrag_submission,
)
from path_graph.console.lifecycle import (
    LIFECYCLE_BATCH_ID,
    ProjectLifecycleBusyError,
    api_cleanup_project,
    api_get_binding,
    api_list_tombstones,
    api_purge_document,
    api_purge_source,
    api_reconcile_project,
    api_reingest_document,
    api_restore_document,
    assert_project_lifecycle_idle,
    clear_project_lifecycle_on_failure,
    mark_project_lifecycle_started,
)
from path_graph.console.meta import PgMetaStore
from path_graph.console.projects import ProjectStore
from path_graph.console.rag import hybrid_search
from path_graph.console.retrieval import api_search_project
from path_graph.console.runner import probe_source, resolve_source_settings
from path_graph.console.sources import SourceStore
from path_graph.console.storage import make_blob_store
from path_graph.console.uploads import (
    UploadValidationError,
    build_ingest_manifest,
    count_documents_for_project,
    count_documents_for_source,
    filename_from_raw_uri,
    list_documents_for_project,
    list_documents_for_source,
    upload_raw_files,
)

__all__ = [
    "CredentialCreate",
    "CredentialProfile",
    "CredentialStore",
    "DownstreamBusyError",
    "DownstreamValidationError",
    "LIFECYCLE_BATCH_ID",
    "OAuthStatus",
    "PgMetaStore",
    "ProjectCreate",
    "ProjectLifecycleBusyError",
    "ProjectProfile",
    "ProjectStore",
    "Settings",
    "SourceCreate",
    "SourceDriver",
    "SourceProfile",
    "SourceStore",
    "SourceUpdate",
    "UploadValidationError",
    "api_cleanup_project",
    "api_get_binding",
    "api_list_tombstones",
    "api_purge_document",
    "api_purge_source",
    "api_reconcile_project",
    "api_reingest_document",
    "api_restore_document",
    "api_search_project",
    "apply_graphrag_success",
    "assert_project_graphrag_idle",
    "assert_project_lifecycle_idle",
    "build_ingest_manifest",
    "clear_project_lifecycle_on_failure",
    "count_documents_for_project",
    "count_documents_for_source",
    "filename_from_raw_uri",
    "get_settings",
    "hybrid_search",
    "list_documents_for_project",
    "list_documents_for_source",
    "make_blob_store",
    "mark_project_lifecycle_started",
    "merge_credential_into_settings",
    "prepare_graphrag_submission",
    "probe_source",
    "refresh_token_env_key",
    "resolve_source_settings",
    "s3_key_dead_letter",
    "upload_raw_files",
]
