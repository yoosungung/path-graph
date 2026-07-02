"""Console public API contract for external consumers (agents-runtime)."""

from __future__ import annotations

import path_graph.console as console

# Symbols agents-runtime backend uses (must be reachable via path_graph.console).
_REQUIRED_SYMBOLS = frozenset(
    {
        "ProjectStore",
        "SourceStore",
        "CredentialStore",
        "merge_credential_into_settings",
        "probe_source",
        "resolve_source_settings",
        "api_search_project",
        "apply_graphrag_success",
        "prepare_graphrag_submission",
        "assert_project_graphrag_idle",
        "DownstreamBusyError",
        "DownstreamValidationError",
        "LIFECYCLE_BATCH_ID",
        "ProjectLifecycleBusyError",
        "api_cleanup_project",
        "api_get_binding",
        "api_list_tombstones",
        "api_purge_document",
        "api_purge_source",
        "api_reconcile_project",
        "api_reingest_document",
        "api_restore_document",
        "assert_project_lifecycle_idle",
        "mark_project_lifecycle_started",
        "clear_project_lifecycle_on_failure",
        "UploadValidationError",
        "build_ingest_manifest",
        "count_documents_for_project",
        "count_documents_for_source",
        "filename_from_raw_uri",
        "list_documents_for_project",
        "list_documents_for_source",
        "upload_raw_files",
        "Settings",
        "get_settings",
        "ProjectCreate",
        "ProjectProfile",
        "SourceCreate",
        "SourceProfile",
        "SourceUpdate",
        "SourceDriver",
        "CredentialCreate",
        "CredentialProfile",
        "OAuthStatus",
        "refresh_token_env_key",
        "s3_key_dead_letter",
        "PgMetaStore",
        "make_blob_store",
        "hybrid_search",
    }
)

# Argo / internal orchestration — must not be top-level console exports.
_FORBIDDEN_TOP_LEVEL = frozenset(
    {
        "collect_source",
        "manifest_lines_to_json",
        "resolve_settings_from_env",
        "read_manifest_lines",
    }
)


def test_console_exports_required_symbols() -> None:
    missing = sorted(name for name in _REQUIRED_SYMBOLS if not hasattr(console, name))
    assert not missing, f"missing console exports: {missing}"


def test_console_all_matches_public_attributes() -> None:
    public = {name for name in console.__all__ if not name.startswith("_")}
    exported = {name for name in public if hasattr(console, name)}
    assert public == exported


def test_console_all_excludes_internal_orchestration() -> None:
    overlap = _FORBIDDEN_TOP_LEVEL & set(console.__all__)
    assert not overlap, f"internal symbols in console.__all__: {sorted(overlap)}"
