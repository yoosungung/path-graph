"""Console facade — credentials."""

from path_graph.admin.credential_settings import merge_credential_into_settings
from path_graph.admin.credentials import CredentialStore

__all__ = ["CredentialStore", "merge_credential_into_settings"]
