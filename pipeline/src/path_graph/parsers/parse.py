from __future__ import annotations

import json
import subprocess
from pathlib import Path

from markitdown import MarkItDown


def parse_markdown_file(path: Path) -> str:
    md = MarkItDown()
    result = md.convert(str(path))
    return result.text_content or ""


def parse_bytes_markitdown(data: bytes, suffix: str) -> str:
    tmp = Path(f"/tmp/path-graph-parse{suffix}")
    tmp.write_bytes(data)
    try:
        return parse_markdown_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def parse_hwp_json(data: bytes, rhwp_bin: str = "rhwp-batch") -> dict:
    tmp_in = Path("/tmp/path-graph-in.hwp")
    tmp_out = Path("/tmp/path-graph-out.json")
    tmp_in.write_bytes(data)
    try:
        subprocess.run(
            [rhwp_bin, "to-json", str(tmp_in), "-o", str(tmp_out), "--log-format=json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(tmp_out.read_text(encoding="utf-8"))
    finally:
        tmp_in.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)


def parse_document(data: bytes, filename: str, *, rhwp_bin: str = "rhwp-batch") -> tuple[str, dict | None]:
    lower = filename.lower()
    if lower.endswith((".hwp", ".hwpx")):
        doc_json = parse_hwp_json(data, rhwp_bin=rhwp_bin)
        return json.dumps(doc_json, ensure_ascii=False), doc_json
    suffix = Path(filename).suffix or ".bin"
    text = parse_bytes_markitdown(data, suffix)
    return text, None
