"""Agent bundle compatibility with agents-runtime dynamic import."""

from __future__ import annotations

import ast
import hashlib
import importlib
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


@pytest.mark.parametrize("agent_name,package_name,entrypoint,prompt_file,needle", AGENT_CASES)
def test_agent_bundle_zip_is_directly_importable(
    tmp_path,
    agent_name: str,
    package_name: str,
    entrypoint: str,
    prompt_file: str,
    needle: str,
) -> None:
    zip_path = tmp_path / f"{agent_name}.zip"
    zip_path.write_bytes(_zip_src_dir(_agent_src(agent_name)))
    for mod in list(sys.modules):
        if mod == package_name or mod.startswith(f"{package_name}."):
            sys.modules.pop(mod)
    sys.path.insert(0, str(zip_path))
    try:
        module_name, attr_name = entrypoint.split(":", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attr_name))
    finally:
        sys.path.remove(str(zip_path))
        for mod in list(sys.modules):
            if mod == package_name or mod.startswith(f"{package_name}."):
                sys.modules.pop(mod)


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


@pytest.mark.parametrize("agent_name,package_name,entrypoint,prompt_file,needle", AGENT_CASES)
def test_agent_package_has_no_runtime_absolute_self_imports(
    agent_name: str,
    package_name: str,
    entrypoint: str,
    prompt_file: str,
    needle: str,
) -> None:
    """BundleLoader only rewrites absolute imports during module exec.

    Function-body ``from <package>.X import ...`` fails at invoke time with
    ``No module named '<package>'`` because the checksum namespace is not on
    ``sys.path``. Keep self-imports at module top level (or relative).
    """
    pkg_root = _agent_src(agent_name) / package_name
    for path in sorted(pkg_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module:
                    if child.module == package_name or child.module.startswith(
                        f"{package_name}."
                    ):
                        pytest.fail(
                            f"{path.relative_to(REPO_ROOT)}:{child.lineno} "
                            f"runtime absolute import {child.module!r} "
                            f"inside {node.name}()"
                        )
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        if alias.name == package_name or alias.name.startswith(
                            f"{package_name}."
                        ):
                            pytest.fail(
                                f"{path.relative_to(REPO_ROOT)}:{child.lineno} "
                                f"runtime absolute import {alias.name!r} "
                                f"inside {node.name}()"
                            )


def test_graph_extractor_batching_works_under_bundle_loader(bundle_loader, tmp_path) -> None:
    """Regression: lazy imports in batching.py broke agent:compiled_graph invoke."""
    BundleLoader, SourceMeta = bundle_loader
    agent_name = "graph-extractor"
    package_name = "graph_extractor"
    bundle_bytes = _zip_src_dir(_agent_src(agent_name))
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(bundle_bytes)
    checksum = "sha256:" + hashlib.sha256(bundle_bytes).hexdigest()
    meta = SourceMeta(
        kind="agent",
        name=agent_name,
        version="test",
        runtime_pool="agent:compiled_graph",
        entrypoint="graph_extractor.agent:factory",
        bundle_uri=f"file://{zip_path}",
        checksum=checksum,
    )
    loader = BundleLoader(cache_dir=str(tmp_path / "cache"), max_entries=4)
    assert callable(loader.load(meta))

    batching_key = next(k for k in sys.modules if k.endswith(f".{package_name}.batching"))
    batching = sys.modules[batching_key]
    batches = batching.split_chunk_batches([{"text": "alpha"}, {"text": "beta"}], max_batch_chars=100)
    assert batches == ["alpha\n\nbeta"]
    merged = batching.merge_graph_parts(
        [{"entities": [{"id": "e1", "name": "E1"}], "edges": []}]
    )
    assert merged["entities"][0]["id"] == "e1"
