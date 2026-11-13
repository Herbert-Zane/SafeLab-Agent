"""Markdown counts for tracked worktree files; never open task/evaluator JSON."""

from __future__ import annotations

import argparse
import io
import subprocess
import tokenize
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], encoding="utf-8")


def category(path):
    if path.suffix == ".py":
        return "测试" if path.parts[0] == "tests" else "Python 源码"
    if path.suffix in (".yaml", ".yml"):
        return (
            "YAML 卡片" if path.parts[:4] == ("src", "safelab", "critic", "cards") else "其他 YAML"
        )
    if path.suffix in (".html", ".css", ".js", ".ts", ".tsx", ".jsx"):
        return "前端"
    if path.suffix in (".md", ".rst", ".txt"):
        return "文档"
    return None


def comment_only_lines(text, suffix):
    """Physical lines containing only comments; docstrings count as Python content."""
    lines = text.splitlines()
    if suffix == ".py":
        comments = set()
        for item in tokenize.generate_tokens(io.StringIO(text).readline):
            if (
                item.type == tokenize.COMMENT
                and not lines[item.start[0] - 1][: item.start[1]].strip()
            ):
                comments.add(item.start[0])
        return comments
    if suffix in (".yaml", ".yml"):
        return {i for i, line in enumerate(lines, 1) if line.lstrip().startswith("#")}
    # Strip comment spans while respecting quoted JS/CSS/HTML strings and JS templates.
    html = suffix in (".html", ".md", ".rst", ".txt")
    block_start, block_end = ("<!--", "-->") if html else ("/*", "*/")
    line_comments = suffix in (".js", ".ts", ".tsx", ".jsx")
    in_block = False
    quote = None
    comments = set()
    for number, line in enumerate(lines, 1):
        i, code, saw_comment = 0, False, in_block
        while i < len(line):
            if in_block:
                end = line.find(block_end, i)
                if end < 0:
                    break
                i, in_block = end + len(block_end), False
            elif quote:
                code = True
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == quote:
                    quote = None
                i += 1
            elif line.startswith(block_start, i):
                in_block, saw_comment = True, True
                i += len(block_start)
            elif line_comments and line.startswith("//", i):
                saw_comment = True
                break
            else:
                if not html and line[i] in "\"'`":
                    quote = line[i]
                code |= not line[i].isspace()
                i += 1
        if not code and saw_comment and line.strip():
            comments.add(number)
        if quote != "`":
            quote = None
    return comments


def line_counts(text, suffix):
    lines = text.splitlines()
    blank = sum(not line.strip() for line in lines)
    comments = len(comment_only_lines(text, suffix))
    return Counter(
        files=1,
        total=len(lines),
        blank=blank,
        comments=comments,
        content=len(lines) - blank - comments,
    )


def collect(root=REPO):
    root = Path(root)
    files = git(root, "ls-files", "-z").split("\0")
    groups = {}
    excluded = 0
    for filename in sorted(filter(None, files)):
        path = Path(filename)
        kind = category(path)
        if kind is None:
            excluded += 1
            continue  # In particular, never read task JSON, case JSONL or generated binary files.
        key = (path.parts[0] if len(path.parts) > 1 else "（根目录）", kind)
        counts = line_counts((root / path).read_text(encoding="utf-8"), path.suffix)
        groups.setdefault(key, Counter()).update(counts)
    dates = git(root, "log", "--format=%ad", "--date=short").splitlines()
    return {
        "head": git(root, "rev-parse", "HEAD").strip(),
        "groups": groups,
        "dates": Counter(dates),
        "excluded_files": excluded,
        "total": sum(groups.values(), Counter()),
    }


def render(stats):
    dates, total = stats["dates"], stats["total"]
    out = [
        "<!-- code-stats:start -->",
        f"统计提交：`{stats['head']}`。",
        "生成命令：`.venv\\Scripts\\python.exe tools/code_stats.py`。",
        "文件范围为 git ls-files，行内容来自当前工作树；未跟踪文件不计，未提交的已跟踪修改会计入。",
        "计物理行（末行无换行也计一行）；内容行、空行、纯注释行互斥；含代码的行尾注释仍属内容行。",
        "Python 用 tokenize 识别 # 注释，docstring 计入内容行；YAML 只计以 # 开头的纯注释行。",
        "前端识别 //、/* */ 或 HTML 注释；文档只识别 HTML 注释。它是行数统"
        "计，不是贡献度或开发工时证明。",
        f"未纳入上述类别的文件 {stats['excluded_files']} 个"
        "（如 JSON/JSONL、CSV、TOML、许可文件）；不读取其内容。",
        "",
        "| 目录 | 类别 | 文件 | 内容行 | 空行 | 纯注释行 | 合计行 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for (directory, kind), row in sorted(stats["groups"].items()):
        out.append(
            f"| {directory} | {kind} | {row['files']} | {row['content']} | "
            f"{row['blank']} | {row['comments']} | {row['total']} |"
        )
    out += [
        f"| **合计** | | **{total['files']}** | **{total['content']}** | "
        f"**{total['blank']}** | **{total['comments']}** | **{total['total']}** |",
        "",
        f"HEAD 可达提交数：{sum(dates.values())}；首个提交日期：{min(dates)}；"
        f"末个提交日期：{max(dates)}。"
        "日期取 git log 的作者日期（提交中记录的时区），不输出作者身份。",
        "",
        "| 日期 | 提交数 |",
        "|---|---:|",
    ]
    out += [f"| {date} | {count} |" for date, count in sorted(dates.items())]
    out += ["<!-- code-stats:end -->", ""]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)
    print(render(collect(args.root)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
