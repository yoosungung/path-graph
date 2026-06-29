from __future__ import annotations

BLOCKS_SCHEMA_VERSION = "1"

REQUIRED_BLOCK_DOC_KEYS = frozenset({"schema_version", "extractor", "blocks"})


def normalize_blocks_document(doc: dict, *, extractor: str) -> dict:
    """Ensure blocks document matches ARCHITECTURE §2.1 contract."""
    blocks = doc.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("blocks document must contain a blocks array")
    return {
        "schema_version": BLOCKS_SCHEMA_VERSION,
        "extractor": extractor,
        "blocks": blocks,
    }
