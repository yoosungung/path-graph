"""Agent bundle compatibility with agents-runtime dynamic import."""

from __future__ import annotations

import ast
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_RUNTIME_COMMON = REPO_ROOT.parent / "agents-runtime" / "packages" / "common" / "src"

AGENT_CASES = [
    (
        "graph-extractor",
        "graph_extractor",
        "graph_extractor.agent:factory",
        "extract_graph.txt",
        "entity",
    ),
    (
        "wiki-synthesizer",
        "wiki_synthesizer",
        "wiki_synthesizer.agent:factory",
        "community_report.txt",
        "community",
    ),
]


def _agent_src(agent_name: str) -> Path:
    return REPO_ROOT / "agents" / agent_name / "src"


@pytest.mark.parametrize("agent_name,package_name,entrypoint,prompt_file,needle", AGENT_CASES)
def test_agent_module_has_no_top_level_file_path(
    agent_name: str,
    package_name: str,
    entrypoint: str,
    prompt_file: str,
    needle: str,
) -> None:
    agent_path = _agent_src(agent_name) / package_name / "agent.py"
    tree = ast.parse(agent_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            if isinstance(value.func.value, ast.Name) and value.func.value.id == "Path":
                for arg in value.args:
                    if isinstance(arg, ast.Name) and arg.id == "__file__":
                        pytest.fail(f"{agent_path.name} must not use Path(__file__) at module level")


def _zip_src_dir(src_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            zf.write(path, str(path.relative_to(src_dir)))
    return buf.getvalue()


@pytest.fixture
def bundle_loader():
    if not AGENTS_RUNTIME_COMMON.is_dir():
        pytest.skip("agents-runtime not checked out beside path-graph")
    sys.path.insert(0, str(AGENTS_RUNTIME_COMMON))
    try:
        from runtime_common.loader import BundleLoader
        from runtime_common.schemas import SourceMeta

        yield BundleLoader, SourceMeta
    finally:
        if str(AGENTS_RUNTIME_COMMON) in sys.path:
            sys.path.remove(str(AGENTS_RUNTIME_COMMON))


@pytest.mark.parametrize("agent_name,package_name,entrypoint,prompt_file,needle", AGENT_CASES)
def test_agent_bundle_imports_and_reads_prompt(
    bundle_loader,
    tmp_path,
    agent_name: str,
    package_name: str,
    entrypoint: str,
    prompt_file: str,
    needle: str,
) -> None:
    BundleLoader, SourceMeta = bundle_loader
    src_dir = _agent_src(agent_name)
    bundle_bytes = _zip_src_dir(src_dir)
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)
    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    meta = SourceMeta(
        kind="agent",
        name=agent_name,
        version="test",
        runtime_pool="agent:compiled_graph",
        entrypoint=entrypoint,
        bundle_uri=f"file://{zip_path}",
        checksum=checksum,
    )
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=4)
    factory = loader.load(meta)
    assert callable(factory)

    paths_key = next(k for k in sys.modules if k.endswith(f".{package_name}.paths"))
    read_prompt = getattr(sys.modules[paths_key], "read_prompt")
    assert needle in read_prompt(prompt_file).lower()
