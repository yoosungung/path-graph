from __future__ import annotations

from path_graph.config import Settings
from path_graph.contracts.credential import CredentialProfile, refresh_token_env_key
from path_graph.contracts.source import SourceDriver, SourceProfile


def merge_credential_into_settings(
    base: Settings,
    *,
    profile: SourceProfile,
    credential: CredentialProfile | None,
    secret_values: dict[str, str],
    platform_client_id: str = "",
    platform_client_secret: str = "",
    platform_ms_tenant_id: str = "",
) -> Settings:
    """Overlay per-source OAuth secrets onto Settings for collectors."""
    if credential is None:
        return base

    updates: dict[str, object] = {}
    token_key = refresh_token_env_key(credential.driver)
    refresh = secret_values.get(token_key, "").strip()
    if not refresh:
        return base

    if credential.driver == SourceDriver.GDRIVE:
        client_id = (credential.config.get("client_id") or platform_client_id or "").strip()
        client_secret = platform_client_secret.strip()
        if client_id:
            updates["gdrive_client_id"] = client_id
        if client_secret:
            updates["gdrive_client_secret"] = client_secret
        updates["gdrive_refresh_token"] = refresh
    elif credential.driver in (SourceDriver.SHAREPOINT, SourceDriver.ONEDRIVE):
        tenant_id = (
            credential.config.get("ms_tenant_id") or platform_ms_tenant_id or base.ms_tenant_id
        ).strip()
        client_id = (credential.config.get("client_id") or platform_client_id or "").strip()
        client_secret = platform_client_secret.strip()
        if tenant_id:
            updates["ms_tenant_id"] = tenant_id
        if client_id:
            updates["ms_client_id"] = client_id
        if client_secret:
            updates["ms_client_secret"] = client_secret
        updates["ms_auth_mode"] = "delegated"
        updates["ms_refresh_token"] = refresh
        if credential.driver == SourceDriver.ONEDRIVE:
            updates["onedrive_refresh_token"] = refresh

    if not updates:
        return base
    return base.model_copy(update=updates)
