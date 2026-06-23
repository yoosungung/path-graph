"""Wheel must include subpackages (hatch only-packages + __init__.py)."""

import importlib.util


def test_steps_package_importable():
    spec = importlib.util.find_spec("path_graph.steps.ingest_manifest")
    assert spec is not None, "path_graph.steps missing from installed package"
