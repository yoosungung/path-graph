from __future__ import annotations

import sys
import time
from typing import Protocol

import msal

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
DELEGATED_SCOPES = ["Files.Read.All", "Sites.Read.All"]


class GraphAuthError(Exception):
    pass


class GraphTokenProvider(Protocol):
    def get_token(self) -> str: ...


class AppTokenProvider:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        result = self._app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise GraphAuthError(result.get("error_description", "app auth failed"))
        self._token = result["access_token"]
        self._expires_at = time.time() + int(result.get("expires_in", 3600))
        return self._token


class DelegatedTokenProvider:
    def __init__(self, tenant_id: str, client_id: str, refresh_token: str) -> None:
        self._app = msal.PublicClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        self._refresh_token = refresh_token
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        result = self._app.acquire_token_by_refresh_token(
            self._refresh_token,
            scopes=DELEGATED_SCOPES,
        )
        if "access_token" not in result:
            raise GraphAuthError(result.get("error_description", "delegated auth failed"))
        self._token = result["access_token"]
        self._expires_at = time.time() + int(result.get("expires_in", 3600))
        if "refresh_token" in result:
            self._refresh_token = result["refresh_token"]
        return self._token


def device_code_login(tenant_id: str, client_id: str) -> tuple[str, str]:
    """Interactive device-code flow. Returns (access_token, refresh_token)."""
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )
    flow = app.initiate_device_flow(scopes=DELEGATED_SCOPES)
    if "user_code" not in flow:
        raise GraphAuthError(flow.get("error_description", "device flow init failed"))
    print(flow["message"], file=sys.stderr)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise GraphAuthError(result.get("error_description", "device flow failed"))
    refresh = result.get("refresh_token", "")
    if refresh:
        print("Save MS_REFRESH_TOKEN for subsequent runs.", file=sys.stderr)
    return result["access_token"], refresh


class _StaticTokenProvider:
    def __init__(self, token: str) -> None:
        self._token = token

    def get_token(self) -> str:
        return self._token


def make_token_provider(settings) -> GraphTokenProvider:
    mode = (settings.ms_auth_mode or "app").strip().lower()
    tenant = settings.ms_tenant_id.strip()
    client_id = settings.ms_client_id.strip()
    if not tenant or not client_id:
        raise GraphAuthError("MS_TENANT_ID and MS_CLIENT_ID are required")

    if mode == "app":
        secret = settings.ms_client_secret.strip()
        if not secret:
            raise GraphAuthError("MS_CLIENT_SECRET required for app auth")
        return AppTokenProvider(tenant, client_id, secret)

    if mode == "delegated":
        refresh = settings.ms_refresh_token.strip()
        if not refresh:
            raise GraphAuthError("MS_REFRESH_TOKEN required for delegated auth")
        return DelegatedTokenProvider(tenant, client_id, refresh)

    if mode == "device":
        access, refresh = device_code_login(tenant, client_id)
        if refresh:
            print(f"MS_REFRESH_TOKEN={refresh}", file=sys.stderr)
        return _StaticTokenProvider(access)

    raise GraphAuthError(f"unknown MS_AUTH_MODE: {mode}")


def make_onedrive_token_provider(settings) -> GraphTokenProvider:
    tenant = settings.ms_tenant_id.strip()
    client_id = settings.ms_client_id.strip()
    refresh = settings.onedrive_refresh_token.strip() or settings.ms_refresh_token.strip()
    if not tenant or not client_id:
        raise GraphAuthError("MS_TENANT_ID and MS_CLIENT_ID are required for OneDrive")
    if not refresh:
        raise GraphAuthError(
            "ONEDRIVE_REFRESH_TOKEN or MS_REFRESH_TOKEN required for OneDrive"
        )
    return DelegatedTokenProvider(tenant, client_id, refresh)
