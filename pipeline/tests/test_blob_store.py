from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.config import Settings
from path_graph.storage.blob import s3_client_kwargs


def test_s3_client_kwargs_uses_region_and_disables_default_checksums():
    settings = Settings(
        pipeline_storage_backend="s3",
        s3_endpoint_url="http://127.0.0.1:3900",
        s3_bucket="runtime-bundles",
        s3_access_key="access",
        s3_secret_key="secret",
        s3_region="garage",
    )
    kwargs = s3_client_kwargs(settings)

    assert kwargs["region_name"] == "garage"
    assert kwargs["endpoint_url"] == "http://127.0.0.1:3900"
    assert kwargs["aws_access_key_id"] == "access"
    assert kwargs["aws_secret_access_key"] == "secret"
    assert kwargs["config"].request_checksum_calculation == "when_required"
    assert kwargs["config"].response_checksum_validation == "when_required"
    assert kwargs["config"].s3["addressing_style"] == "path"


@patch("path_graph.storage.blob.boto3.client")
def test_make_blob_store_passes_garage_client_kwargs(mock_client: MagicMock):
    from path_graph.storage.blob import clear_blob_store_cache, make_blob_store

    clear_blob_store_cache()
    settings = Settings(
        pipeline_storage_backend="s3",
        s3_endpoint_url="http://127.0.0.1:3900",
        s3_bucket="runtime-bundles",
        s3_access_key="access",
        s3_secret_key="secret",
        s3_region="garage",
    )
    make_blob_store(settings)

    mock_client.assert_called_once()
    _, kwargs = mock_client.call_args
    assert kwargs["region_name"] == "garage"
    assert kwargs["config"].request_checksum_calculation == "when_required"
    assert kwargs["config"].retries["max_attempts"] == 10
    clear_blob_store_cache()


@patch("path_graph.storage.blob.boto3.client")
def test_make_blob_store_reuses_s3_client(mock_client: MagicMock):
    from path_graph.storage.blob import clear_blob_store_cache, make_blob_store

    clear_blob_store_cache()
    settings = Settings(
        pipeline_storage_backend="s3",
        s3_endpoint_url="http://127.0.0.1:3900",
        s3_bucket="runtime-bundles",
        s3_access_key="access",
        s3_secret_key="secret",
        s3_region="garage",
    )
    first = make_blob_store(settings)
    second = make_blob_store(settings)

    assert first is second
    mock_client.assert_called_once()
    clear_blob_store_cache()
