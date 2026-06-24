from path_graph.admin.credential_settings import merge_credential_into_settings
from path_graph.config import Settings
from path_graph.contracts.credential import CredentialProfile, OAuthStatus, k8s_secret_name_for_credential
from path_graph.contracts.source import SourceDriver, SourceProfile


def test_merge_gdrive_refresh_token():
    base = Settings(gdrive_client_id="", gdrive_refresh_token="")
    cred = CredentialProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        label="gdrive-a",
        driver=SourceDriver.GDRIVE,
        k8s_secret_name=k8s_secret_name_for_credential("dev", "11111111-1111-4111-8111-111111111111"),
        oauth_status=OAuthStatus.CONNECTED,
        secret_keys=["GDRIVE_REFRESH_TOKEN"],
    )
    profile = SourceProfile(
        tenant="dev",
        id="22222222-2222-4222-8222-222222222222",
        name="docs",
        driver=SourceDriver.GDRIVE,
        source_id="gdrive:docs",
        credential_id=cred.id,
    )
    merged = merge_credential_into_settings(
        base,
        profile=profile,
        credential=cred,
        secret_values={"GDRIVE_REFRESH_TOKEN": "rt-test"},
        platform_client_id="app-id",
        platform_client_secret="app-secret",
    )
    assert merged.gdrive_refresh_token == "rt-test"
    assert merged.gdrive_client_id == "app-id"
    assert merged.gdrive_client_secret == "app-secret"
