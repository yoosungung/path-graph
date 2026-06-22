from __future__ import annotations

import time
from typing import Protocol

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"


class GDriveAuthError(Exception):
    pass


class GDriveTokenProvider(Protocol):
    def get_token(self) -> str: ...


class RefreshTokenProvider:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._http = httpx.Client(timeout=60.0)

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        resp = self._http.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            detail = resp.json().get("error_description", resp.text)
            raise GDriveAuthError(f"GDrive token refresh failed: {detail}")
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._token


def make_gdrive_token_provider(settings) -> GDriveTokenProvider:
    client_id = settings.gdrive_client_id.strip()
    client_secret = settings.gdrive_client_secret.strip()
    refresh = settings.gdrive_refresh_token.strip()
    if not client_id or not client_secret:
        raise GDriveAuthError("GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET are required")
    if not refresh:
        raise GDriveAuthError("GDRIVE_REFRESH_TOKEN is required")
    return RefreshTokenProvider(client_id, client_secret, refresh)
