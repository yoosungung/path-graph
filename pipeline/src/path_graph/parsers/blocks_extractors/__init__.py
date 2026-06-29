from __future__ import annotations

import re
from typing import Protocol

from path_graph.parsers.blocks_contract import normalize_blocks_document


class BlocksExtractor(Protocol):
    name: str

    def extract(self, markdown: str) -> dict: ...


_REGISTRY: dict[str, BlocksExtractor] = {}


def register_blocks_extractor(extractor: BlocksExtractor) -> None:
    _REGISTRY[extractor.name] = extractor


def get_blocks_extractor(name: str) -> BlocksExtractor:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"unknown blocks extractor: {name!r} (known: {known})") from exc


def _register_defaults() -> None:
    from path_graph.parsers.blocks_extractors.md_heuristic import MdHeuristicBlocksExtractor

    register_blocks_extractor(MdHeuristicBlocksExtractor())


_register_defaults()
