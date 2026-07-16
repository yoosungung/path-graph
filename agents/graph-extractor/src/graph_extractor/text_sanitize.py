"""Normalize chunk input and graph_v1 output for safe LLM + JSON serialization."""

from __future__ import annotations

import json
import re
import unicodedata

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+\{([^}]*)\}")
_MIDWORD_NEWLINE_RE = re.compile(r"(?<=[^\n\s])\n(?=[^\n\s])")
_HANGUL_MIDWORD_NEWLINE_RE = re.compile(r"([\uac00-\ud7a3])\n([\uac00-\ud7a3])")
_JSON_DEBRIS_TAIL_RE = re.compile(r"[\.\d]*\}\],?\s*['\"]?\s*$")

_ENTITY_STRING_FIELDS = ("id", "name", "description")
_EDGE_STRING_FIELDS = ("type", "source", "target", "description")


def _strip_surrogates(text: str) -> str:
    return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))


def _fix_midword_newlines(text: str) -> str:
    s = _HANGUL_MIDWORD_NEWLINE_RE.sub(r"\1\2", text)
    return _MIDWORD_NEWLINE_RE.sub(" ", s)


def sanitize_graph_string(text: str) -> str:
    """Clean one graph_v1 string field (entity/edge property)."""
    s = unicodedata.normalize("NFC", _strip_surrogates(text or ""))
    s = _CONTROL_CHARS_RE.sub(" ", s)
    s = _LATEX_CMD_RE.sub(r"\1", s)
    s = _fix_midword_newlines(s)
    s = _JSON_DEBRIS_TAIL_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def sanitize_chunk_text(text: str) -> str:
    """Clean chunk body before LLM prompt assembly."""
    s = unicodedata.normalize("NFC", _strip_surrogates(text or ""))
    s = _CONTROL_CHARS_RE.sub(" ", s)
    s = _LATEX_CMD_RE.sub(r"\1", s)
    s = _HANGUL_MIDWORD_NEWLINE_RE.sub(r"\1\2", s)
    s = _MIDWORD_NEWLINE_RE.sub("", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _sanitize_entity(entity: dict) -> dict:
    out = dict(entity)
    for field in _ENTITY_STRING_FIELDS:
        if field in out and out[field] is not None:
            out[field] = sanitize_graph_string(str(out[field]))
    return out


def _sanitize_edge(edge: dict) -> dict:
    out = dict(edge)
    for field in _EDGE_STRING_FIELDS:
        if field in out and out[field] is not None:
            out[field] = sanitize_graph_string(str(out[field]))
    return out


def sanitize_graph_v1(data: dict) -> dict:
    """Return graph_v1 payload with UTF-8-safe string fields."""
    entities = [
        _sanitize_entity(entity)
        for entity in (data.get("entities") or [])
        if isinstance(entity, dict)
    ]
    edges = [
        _sanitize_edge(edge)
        for edge in (data.get("edges") or [])
        if isinstance(edge, dict)
    ]
    return {"entities": entities, "edges": edges}


def ensure_json_utf8_safe(value: object) -> None:
    """Raise UnicodeEncodeError when value cannot be UTF-8 JSON-encoded."""
    json.dumps(value, ensure_ascii=False).encode("utf-8")
