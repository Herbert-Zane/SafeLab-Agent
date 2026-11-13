"""Counts reconcile and exclude untracked files and forbidden task contents."""

import subprocess
import sys

from tools import code_stats

from test_export_prompts import tmp_path as tmp_path


def test_python_comments_do_not_count_hashes_inside_strings_or_docstrings():
    text = '# comment\n\n"""documentation\n# inside a string\n"""\nx = "#"  # inline\n'
    counts = code_stats.line_counts(text, ".py")
    assert (counts["total"], counts["content"], counts["blank"], counts["comments"]) == (6, 4, 1, 1)


def test_frontend_block_comments_and_urls():
    text = '/* first\n * second\n */\nconst url = "https://example.invalid"; // inline\n// only\n\n'
    row = code_stats.line_counts(text, ".js")
    assert (row["total"], row["content"], row["blank"], row["comments"]) == (6, 1, 1, 4)
    html = "<!-- first\nsecond -->\n<div>content</div>\n"
    assert code_stats.line_counts(html, ".html")["comments"] == 2


def test_tracked_only_groups_dates_and_cli(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "x.py").write_text("# comment\nx = 1\n\n", encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text("assert True\n", encoding="utf-8")
    # Invalid UTF-8 ensures collect() cannot silently read excluded task files.
    (tmp_path / "task.json").write_bytes(b"\xff")
    git("add", "src/x.py", "tests/test_x.py", "task.json")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "fixture",
    )
    (tmp_path / "untracked.py").write_text("raise RuntimeError\n", encoding="utf-8")
    stats = code_stats.collect(tmp_path)
    assert stats["total"]["files"] == 2
    assert stats["total"]["total"] == 4
    assert stats["excluded_files"] == 1
    assert sum(stats["dates"].values()) == 1
    assert ("tests", "测试") in stats["groups"]
    assert stats["total"]["total"] == sum(
        stats["total"][k] for k in ("content", "blank", "comments")
    )
    result = subprocess.run(
        [sys.executable, str(code_stats.REPO / "tools/code_stats.py"), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert stats["head"] in result.stdout
    assert "Fixture" not in result.stdout
    assert "fixture@example.invalid" not in result.stdout
