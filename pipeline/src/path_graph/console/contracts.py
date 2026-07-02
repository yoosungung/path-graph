"""Console facade — shared contracts (DTOs)."""

from path_graph.contracts.credential import (
    CredentialCreate,
    CredentialProfile,
    OAuthStatus,
    refresh_token_env_key,
)
from path_graph.contracts.project import ProjectCreate, ProjectProfile
from path_graph.contracts.s3_keys import s3_key_dead_letter
from path_graph.contracts.source import SourceCreate, SourceDriver, SourceProfile, SourceUpdate

__all__ = [
    "CredentialCreate",
    "CredentialProfile",
    "OAuthStatus",
    "ProjectCreate",
    "ProjectProfile",
    "SourceCreate",
    "SourceDriver",
    "SourceProfile",
    "SourceUpdate",
    "refresh_token_env_key",
    "s3_key_dead_letter",
]
