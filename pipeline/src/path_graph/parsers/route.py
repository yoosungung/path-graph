"""Extension → parse backend routing (ARCHITECTURE D3 / DESIGN Blocks).

Upload/collector allowlists must match ``allowed_extensions()``.
Adapters that consume these backends land in follow-up tickets (#279+).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class ParseBackend(StrEnum):
    UNSTRUCTURED = "unstructured"
    PYMUPDF = "pymupdf"
    RHWP_BATCH = "rhwp_batch"
    TEXT = "text"


class UnsupportedFormatError(ValueError):
    """Legacy or unknown extension — ingest should dead_letter."""


# Ordered for stable display / join order in error messages.
_EXTENSION_BACKEND: dict[str, ParseBackend] = {
    ".docx": ParseBackend.UNSTRUCTURED,
    ".pptx": ParseBackend.UNSTRUCTURED,
    ".xlsx": ParseBackend.UNSTRUCTURED,
    ".xls": ParseBackend.UNSTRUCTURED,
    ".pdf": ParseBackend.PYMUPDF,
    ".hwp": ParseBackend.RHWP_BATCH,
    ".hwpx": ParseBackend.RHWP_BATCH,
    ".txt": ParseBackend.TEXT,
    ".md": ParseBackend.TEXT,
}

_REJECTED_EXTENSIONS = frozenset({".doc", ".ppt"})


def allowed_extensions() -> frozenset[str]:
    """Parser-policy allowlist — single source for upload/collector defaults."""
    return frozenset(_EXTENSION_BACKEND)


def allowed_extensions_csv() -> str:
    return ",".join(sorted(allowed_extensions()))


def route_parse(filename: str) -> ParseBackend:
    """Map a filename to a parse backend.

    Raises
    ------
    UnsupportedFormatError
        For legacy ``.doc``/``.ppt`` or any extension not in the allowlist.
    """
    suffix = Path(filename).suffix.lower()
    if suffix in _REJECTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"legacy {suffix} is not supported; convert to "
            f"{'.docx' if suffix == '.doc' else '.pptx'}"
        )
    backend = _EXTENSION_BACKEND.get(suffix)
    if backend is None:
        raise UnsupportedFormatError(f"extension {suffix or '(none)'} is not supported")
    return backend
