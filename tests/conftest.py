"""Shared fixtures.

Tests that need the BSLBench platform take the ``bench`` fixture, which skips
when the platform is not at SAFELAB_BENCH_ROOT (the private repository is not
available in CI). Everything else runs without it.
"""
import json

import pytest

from safelab import bench as bench_module


@pytest.fixture(scope="session")
def bench():
    if not bench_module.available():
        pytest.skip(f"BSLBench platform not available at {bench_module.root()} "
                    f"(set {bench_module.ENV_VAR})")
    root = bench_module.ensure_importable()
    bench_module.register(root)
    from fakes import register_platform_fake
    register_platform_fake()
    return root


@pytest.fixture
def load_task(bench):
    """Load a platform task config for the platform's own DryRunEnvironment.

    The config is handed to platform code only; SafeLab code under test sees
    observations, never the task file.
    """
    def load(name):
        return json.loads((bench/"configs"/"tasks"/f"{name}.json").read_text(encoding="utf-8"))
    return load
