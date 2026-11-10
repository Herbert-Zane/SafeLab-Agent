"""Locating the platform, registering the provider, resolving launch paths."""
import json

import pytest

from safelab import bench as bench_module
from safelab import launch


def test_the_platform_root_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(bench_module.ENV_VAR, str(tmp_path))
    assert bench_module.root() == tmp_path
    assert bench_module.available() is False
    with pytest.raises(bench_module.BenchNotFound):
        bench_module.ensure_importable()


def test_without_the_variable_the_default_checkout_is_used(monkeypatch):
    monkeypatch.delenv(bench_module.ENV_VAR, raising=False)
    assert bench_module.root() == bench_module.DEFAULT_ROOT


def test_agent_configs_must_run_the_requested_condition(tmp_path):
    assert launch.resolve_agent("B").name == "safelab_B.json"
    other = tmp_path/"a.json"
    other.write_text(json.dumps({"backend": {"provider": "safelab", "condition": "C"}}))
    with pytest.raises(launch.LaunchError, match="condition 'C'"):
        launch.resolve_agent("B", other)
    other.write_text(json.dumps({"backend": {"provider": "plan_replay"}}))
    with pytest.raises(launch.LaunchError, match="provider"):
        launch.resolve_agent("B", other)


def test_task_paths_fall_back_to_the_platform_root(tmp_path):
    (tmp_path/"configs").mkdir()
    (tmp_path/"configs"/"t.json").write_text("{}")
    assert launch.resolve_file("configs/t.json", tmp_path) == (tmp_path/"configs"/"t.json")
    with pytest.raises(launch.LaunchError):
        launch.resolve_file("configs/missing.json", tmp_path)


def test_registration_is_idempotent_and_reaches_create_backend(bench):
    from agent_interface.backends import backend_providers, create_backend
    bench_module.register()
    bench_module.register()
    assert "safelab" in backend_providers()
    backend = create_backend({"provider": "safelab", "condition": "B", "roles": {
        "actor": {"provider": "scripted", "replies": ["```json\n{}\n```"]}}})
    assert type(backend).__name__ == "SafeLabBackend"


def test_shipped_safelab_configs_load_and_are_stateless(bench):
    from agent_interface.config import AgentRunConfig
    paths = sorted(launch.CONFIG_DIR.glob("safelab_*.json"))
    assert paths
    for path in paths:
        config = AgentRunConfig.load(path)
        assert config.backend["provider"] == "safelab"
        assert config.policy["conversation"] == "stateless"
