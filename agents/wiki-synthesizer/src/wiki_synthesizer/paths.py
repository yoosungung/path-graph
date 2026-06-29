"""Bundle-safe path helpers (agents-runtime sets __spec__.origin, not __file__)."""

from __future__ import annotations

import sys
from pathlib import Path


def read_prompt(filename: str) -> str:
    spec = sys.modules[__name__].__spec__
    if spec is None or not spec.origin:
        return ""
    base = Path(spec.origin).resolve().parent
    path = base / "prompts" / filename
    return path.read_text(encoding="utf-8") if path.exists() else ""
