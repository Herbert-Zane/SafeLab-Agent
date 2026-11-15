"""Documentation must reproduce live source text and keep platform text private."""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest
from tools import export_prompts as export


@pytest.fixture
def tmp_path():
    # Python 3.14's Windows mkdir(0o700), used by pytest, excludes the managed
    # sandbox token. Inherit the workspace ACL instead; artifacts remain ignored.
    parent = export.REPO / "runs" / "_document_tests"
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / uuid4().hex
    target.mkdir()
    try:
        yield target
    finally:
        assert target.resolve().is_relative_to(parent.resolve())
        shutil.rmtree(target, ignore_errors=True)


def run_export(*args):
    return subprocess.run(
        [sys.executable, str(export.REPO / "tools/export_prompts.py"), *map(str, args)],
        cwd=export.REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ.copy(),
    )


def test_cli_runs_and_output_is_byte_stable(bench, tmp_path):
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    for target in (first, second):
        result = run_export("--output", target)
        assert result.returncode == 0, result.stderr
        assert "keyword_hits=" in result.stdout
    assert first.read_bytes() == second.read_bytes()
    assert b"\r" not in first.read_bytes()


def test_formal_run_note_lists_changes_since_the_formal_commit(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/planner.py").write_text("PROMPT = 'one'\n", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "one")
    monkeypatch.setattr(export, "FORMAL_RUN_COMMIT", "HEAD")
    same = "\n".join(export.formal_run_note(tmp_path))
    assert "没有改动" in same and "git show 3f97f1e:docs/prompts_and_tools.md" in same
    # The export reads the working tree, so an uncommitted prompt change is listed too.
    (tmp_path / "src/planner.py").write_text("PROMPT = 'two'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("outside src\n", encoding="utf-8")
    changed = "\n".join(export.formal_run_note(tmp_path))
    assert "`src/planner.py`" in changed and "README" not in changed
    assert "改动之后的" in changed
    monkeypatch.setattr(export, "FORMAL_RUN_COMMIT", "0" * 40)
    assert "无法列出" in "\n".join(export.formal_run_note(tmp_path))


def test_every_prompt_hash_matches_the_exact_exported_text(bench):
    document = export.render_document()
    blocks = re.findall(
        r"### `([^`]+)`\n\n来源：`[^`]+`。\nSHA-256：`([0-9a-f]{64})`。"
        r"\n\n````text\n(.*?)\n````",
        document,
        re.DOTALL,
    )
    prompts = {p.name: p for p in export.collect_prompts()}
    assert len(blocks) == len(prompts)
    for name, digest, text in blocks:
        assert text == prompts[name].text
        assert digest == hashlib.sha256(text.encode("utf-8")).hexdigest()
    root, parts, _, _ = export.platform_parts()
    assert export.git_head(root) in document
    for text in parts.values():
        assert hashlib.sha256(export.lf(text).encode("utf-8")).hexdigest() in document


def test_default_document_does_not_copy_platform_system_or_tool_table(bench):
    from agent_interface import action_schema, prompt

    unique_sentence = prompt.PROTOCOL.split("\n\n")[1]
    assert len(unique_sentence) > 150
    document = export.render_document()
    assert unique_sentence not in document
    assert prompt.PROTOCOL not in document
    assert action_schema.action_reference(action_schema.available_actions()) not in document
    # The plan schema is local and deliberately published.
    schema = export.canonical_json(export.planner.PLAN_SCHEMA)
    assert schema in document
    assert hashlib.sha256(schema.encode("utf-8")).hexdigest() in document


def test_platform_text_outside_runs_is_rejected_before_export(tmp_path):
    target = export.REPO / "docs" / f"_private_rejected_{tmp_path.name}.md"
    result = run_export("--include-platform-text", target, "--output", tmp_path / "public.md")
    assert result.returncode != 0
    assert "runs/" in result.stderr
    assert not target.exists()
    assert not (tmp_path / "public.md").exists()


def test_private_path_resolves_traversal_and_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "REPO", tmp_path)
    (tmp_path / "runs").mkdir()
    assert export.private_output_path(tmp_path / "runs" / "p.md") == tmp_path / "runs" / "p.md"
    with pytest.raises(ValueError):
        export.private_output_path(tmp_path / "runs" / ".." / "p.md")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    try:
        (tmp_path / "runs" / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        return  # Windows may deny symlink creation; traversal was still checked.
    with pytest.raises(ValueError):
        export.private_output_path(tmp_path / "runs" / "link" / "p.md")


def test_private_export_contains_platform_text_but_public_export_does_not(
    bench, tmp_path, monkeypatch
):
    from agent_interface import prompt

    # Redirect only the allowed private destination. Keep source/commit lookup real.
    private = tmp_path / "private.md"
    monkeypatch.setattr(export, "private_output_path", lambda value: private)
    public = tmp_path / "public.md"
    assert export.main(["--output", str(public), "--include-platform-text", "runs/private.md"]) == 0
    assert prompt.PROTOCOL in private.read_text(encoding="utf-8")
    assert prompt.PROTOCOL not in public.read_text(encoding="utf-8")


def test_keyword_matches_are_literal_and_critic_is_exempt():
    prompts = [
        export.Prompt("safelab.actor.sample", "test", "SafeLab\n危险 safety"),
        export.Prompt("safelab.critic.sample", "test", "danger"),
    ]
    hits = export.keyword_hits(prompts)
    assert [(word, line) for _, word, line, _, _ in hits] == [
        ("safe", 1),
        ("safe", 2),
        ("safety", 2),
        ("危险", 2),
    ]


def test_configuration_values_and_locations_are_from_source():
    rows = {
        name: (default, value, source)
        for name, default, value, source in export.configuration_rows()
    }
    default, current, source = rows["backend.planner.max_empty_retries"]
    assert (default, current) == ("2", "1")  # Deliberately different in the selected config.
    filename, number = source.split("; ", 1)[0].rsplit(":", 1)
    assert (
        'planner.get("max_empty_retries", 2)'
        in (export.REPO / filename).read_text(encoding="utf-8").splitlines()[int(number) - 1]
    )
