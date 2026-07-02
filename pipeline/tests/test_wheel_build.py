"""Wheel build smoke tests for GitHub Packages publish."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from email import message_from_string
from pathlib import Path

import tomllib

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PIPELINE_ROOT / "dist"

_REQUIRED_MODULE_PREFIXES = (
    "path_graph/admin/",
    "path_graph/rag/",
    "path_graph/contracts/",
    "path_graph/config.py",
)


def _read_project_meta() -> tuple[str, str]:
    data = tomllib.loads((PIPELINE_ROOT / "pyproject.toml").read_text())
    project = data["project"]
    return project["name"], project["version"]


def _run_uv_build() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    subprocess.run(
        ["uv", "build"],
        cwd=PIPELINE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _latest_wheel() -> Path:
    wheels = sorted(DIST_DIR.glob("*.whl"))
    assert wheels, f"no wheel in {DIST_DIR}"
    return wheels[-1]


def _wheel_metadata(wheel_path: Path) -> message_from_string:
    with zipfile.ZipFile(wheel_path) as zf:
        meta_name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        return message_from_string(zf.read(meta_name).decode())


def test_wheel_build_contains_runtime_modules() -> None:
    _run_uv_build()
    wheel = _latest_wheel()
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    for prefix in _REQUIRED_MODULE_PREFIXES:
        assert any(n.startswith(prefix) or n == prefix for n in names), prefix


def test_wheel_metadata_matches_pyproject() -> None:
    _run_uv_build()
    wheel = _latest_wheel()
    meta = _wheel_metadata(wheel)
    name, version = _read_project_meta()
    assert meta["Name"] == name
    assert meta["Version"] == version
    assert re.match(r"^path_graph-\d+\.\d+\.\d+", wheel.name)
