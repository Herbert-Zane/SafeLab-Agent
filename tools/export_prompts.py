"""Export source-derived prompt documentation without publishing platform text."""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from safelab import actor, bench, planner, reflexion, resilience, summary  # noqa: E402
from safelab.critic import knowledge, llm_critic  # noqa: E402

KEYWORDS = (
    "safe",
    "safety",
    "hazard",
    "danger",
    "careful",
    "caution",
    "risk",
    "安全",
    "危险",
    "小心",
)


def lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sha256(text):
    return hashlib.sha256(lf(text).encode("utf-8")).hexdigest()


def git_head(root):
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()


def source_ref(module, symbol):
    """Find definitions/assignments without embedding checkout-specific absolute paths."""
    path = Path(module.__file__)
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names = (
            [t.id for t in node.targets if isinstance(t, ast.Name)]
            if isinstance(node, ast.Assign)
            else []
        )
        if getattr(node, "name", None) == symbol or symbol in names:
            return f"{path.relative_to(REPO).as_posix()}:{node.lineno}::{symbol}"
    raise ValueError(f"Cannot locate {module.__name__}.{symbol}")


@dataclass(frozen=True)
class Prompt:
    name: str
    source: str
    text: str

    @property
    def digest(self):
        return sha256(self.text)


def collect_prompts():
    """Only local literals or the actual local critic system builder; no model calls."""
    prompts = []
    for module, names in (
        (planner, ("PLANNER_PROTOCOL", "REFUSALS_HEADING", "REFUSALS_PLAN_NOTE")),
        (actor, ("CLOSING", "REFUSALS_HEADING", "REFUSALS_NOTE")),
        (summary, ("REFUSED_HEADING",)),
        (llm_critic, ("SYSTEM",)),
    ):
        for name in names:
            prompts.append(
                Prompt(
                    f"{module.__name__}.{name}", source_ref(module, name), lf(getattr(module, name))
                )
            )
    for name, text in actor.RECOVERY_NOTES.items():
        prompts.append(
            Prompt(
                f"safelab.actor.RECOVERY_NOTES[{name}]",
                source_ref(actor, "RECOVERY_NOTES"),
                lf(text),
            )
        )
    prompts.append(
        Prompt(
            "safelab.critic.llm_critic.system_prompt",
            source_ref(llm_critic, "system_prompt"),
            lf(llm_critic.system_prompt(knowledge.Knowledge.load())),
        )
    )
    return prompts


def keyword_hits(prompts):
    """Literal, case-insensitive substring matches, including matches in SafeLab."""
    hits = []
    for prompt in prompts:
        if prompt.name.startswith("safelab.critic."):
            continue
        for number, line in enumerate(prompt.text.splitlines(), 1):
            for keyword in KEYWORDS:
                for match in re.finditer(re.escape(keyword), line, flags=re.IGNORECASE):
                    hits.append((prompt.name, keyword, number, match.start() + 1, line))
    return hits


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def platform_parts():
    root = bench.ensure_importable()
    from agent_interface import action_schema, prompt

    # No task or evaluator config is opened. These are the interface's default vocabulary.
    return (
        root,
        {
            "PROTOCOL": lf(prompt.PROTOCOL),
            "VISUAL_PROTOCOL": lf(prompt.VISUAL_PROTOCOL),
            "ACTION_PARAMETERS": canonical_json(action_schema.ACTION_PARAMETERS),
            "CONTROL_ACTIONS": canonical_json(action_schema.CONTROL_ACTIONS),
            "action_reference(default)": lf(
                action_schema.action_reference(action_schema.available_actions())
            ),
        },
        list(action_schema.available_actions()),
        list(action_schema.CONTROL_ACTIONS),
    )


def fenced(text, language="text"):
    # The final newline belongs to the Markdown delimiter, not the hashed text.
    return f"````{language}\n{text}\n````"


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def configuration_rows(platform_root=None):
    """Read the backend's get() defaults and the selected checked-in configuration."""
    filename = "src/safelab/backend.py"
    text = (REPO / filename).read_text(encoding="utf-8")
    tree = ast.parse(text)
    config = json.loads((REPO / "configs/agents/safelab_C_flash.json").read_text(encoding="utf-8"))
    prefixes = {
        "planner": "planner",
        "actor": "actor",
        "critic_settings": "critic",
        "reflexion": "reflexion",
        "resilience": "resilience",
    }
    config_lines = (
        (REPO / "configs/agents/safelab_C_flash.json").read_text(encoding="utf-8").splitlines()
    )

    def config_location(keys):
        start = 0
        for depth, key in enumerate(keys.split(".")):
            prefix = " " * (2 * depth + 2) + f'"{key}":'
            start = next(
                i for i in range(start, len(config_lines)) if config_lines[i].startswith(prefix)
            )
        return f"configs/agents/safelab_C_flash.json:{start + 1}"

    external = {}
    if platform_root is not None:
        platform_config = "src/agent_interface/config.py"
        nodes = ast.parse((platform_root / platform_config).read_text(encoding="utf-8"))
        for node in nodes.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            symbol = node.targets[0].id
            section = {"DEFAULT_LIMITS": "limits", "DEFAULT_POLICY": "policy"}.get(symbol)
            if section:
                for key, value in zip(node.value.keys, node.value.values, strict=True):
                    external[f"{section}.{ast.literal_eval(key)}"] = (
                        canonical_json(ast.literal_eval(value)),
                        f"平台 {platform_config}:{key.lineno}",
                    )
        sdk_file = "src/agent_interface/backends/openai_compatible.py"
        nodes = ast.parse((platform_root / sdk_file).read_text(encoding="utf-8"))
        for node in ast.walk(nodes):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in ("request_timeout_s", "max_retries")
            ):
                external[node.args[0].value] = (
                    canonical_json(ast.literal_eval(node.args[1])),
                    f"平台 {sdk_file}:{node.lineno}",
                )

    init = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    rows = []
    for node in sorted(ast.walk(init), key=lambda n: getattr(n, "lineno", 0)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in prefixes
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            continue
        section = prefixes[node.func.value.id]
        key = node.args[0].value
        try:
            default = (
                canonical_json(ast.literal_eval(node.args[1])) if len(node.args) > 1 else "null"
            )
        except ValueError:
            default = ast.get_source_segment(text, node.args[1])
        current = config["backend"].get(section, {}).get(key, "（未配置，取默认）")
        location = f"{filename}:{node.lineno}"
        if key in config["backend"].get(section, {}):
            location += "; " + config_location(f"backend.{section}.{key}")
        rows.append((f"backend.{section}.{key}", default, canonical_json(current), location))
    for key, value in asdict(resilience.RetryPolicy()).items():
        node = next(
            n
            for n in ast.walk(ast.parse(inspect.getsource(resilience)))
            if isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == key
        )
        current = config["backend"]["resilience"].get(key, value)
        location = f"src/safelab/resilience.py:{node.lineno}"
        if key in config["backend"]["resilience"]:
            location += "; " + config_location(f"backend.resilience.{key}")
        rows.append(
            (
                f"backend.resilience.{key} (RetryPolicy)",
                canonical_json(value),
                canonical_json(current),
                location,
            )
        )
    # Platform defaults are read from interface code, never task/evaluator configuration.
    for section in ("limits", "policy"):
        for key, value in config[section].items():
            name = f"{section}.{key}"
            default, location = external.get(name, ("外部默认值未读取", "平台 config.py"))
            rows.append(
                (name, default, canonical_json(value), location + "; " + config_location(name))
            )
    for role, values in config["backend"]["roles"].items():
        for key in ("request_timeout_s", "max_retries"):
            name = f"backend.roles.{role}.{key}"
            default, location = external.get(key, ("外部默认值未读取", "平台后端"))
            rows.append(
                (
                    name,
                    default,
                    canonical_json(values[key]),
                    location + "; " + config_location(name),
                )
            )
    return rows


def function_default(function, parameter):
    return inspect.signature(function).parameters[parameter].default


def code_line(filename, needle):
    for i, line in enumerate((REPO / filename).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return i, line.strip()
    raise ValueError(f"Missing code anchor {filename}: {needle}")


def mechanism_table():
    rows = []
    for label, function, parameter, module, symbol in (
        (
            "规划器重规划时的最近步窗口（调用 make 未传 k，独立于 actor.history_k）",
            planner.plan_request,
            "k",
            planner,
            "plan_request",
        ),
        (
            "平台旧拒绝摘要最多保留的失败种类",
            summary.render_refused,
            "limit",
            summary,
            "render_refused",
        ),
        ("训练经验库读取上限", reflexion.ReflectionLibrary.read, "limit", reflexion, "read"),
    ):
        rows.append((label, function_default(function, parameter), source_ref(module, symbol)))
    for name in ("DEFAULT_STAGE_ACTIONS", "MIN_MISMATCH_ACTIONS"):
        rows.append((name, getattr(planner, name), source_ref(planner, name)))
    rows.append(
        (
            "审查器最近动作窗口 RECENT_ACTIONS",
            llm_critic.RECENT_ACTIONS,
            source_ref(llm_critic, "RECENT_ACTIONS"),
        )
    )
    rows.append(
        (
            "固定回退计划 prepare 阶段 max_actions",
            planner.FALLBACK_STAGES[0]["max_actions"],
            source_ref(planner, "FALLBACK_STAGES"),
        )
    )
    for label, filename, needle in (
        ("账本摘要未确认项尾部截取", "src/safelab/summary.py", "unconfirmed[-5:]"),
        ("不合法计划的纠正重试上限", "src/safelab/planner.py", "if corrections >="),
        ("计划纠正请求最多列出的错误", "src/safelab/planner.py", "errors[:12]"),
        ("提前 finish 的额外重规划上限", "src/safelab/backend.py", "self.finish_replans <"),
        ("审查循环的最终保护上界", "src/safelab/backend.py", "range(2*self.reflexion"),
    ):
        number, expression = code_line(filename, needle)
        rows.append((label, expression, f"{filename}:{number}"))
    return "\n".join(
        [
            "| 项目 | 代码值或表达式 | 来源 |",
            "|---|---|---|",
            *(f"| {cell(a)} | `{cell(b)}` | `{c}` |" for a, b, c in rows),
        ]
    )


def rule_table():
    loaded = knowledge.Knowledge.load()
    # Descriptions are taken verbatim from the source's own R1-R6 documentation table.
    doc = inspect.getdoc(__import__("safelab.critic.rules", fromlist=["RuleChannel"]))
    descriptions = {}
    active = None
    for line in doc.splitlines():
        found = re.match(r"^(R\d+)\s+(.*)", line)
        if found:
            active = found[1]
            descriptions[active] = [line[5:69].strip()]
        elif active and line.startswith("     "):
            descriptions[active].append(line[5:69].strip())
        elif active:
            active = None
    out = [
        f"知识卡片共 {len(loaded.cards)} 张；来源与核对状态见 [sources.md](sources.md)。",
        "以下说明直接摘取 `src/safelab/critic/rules.py` 的规则表，不作效果评价。",
        "硬规则不能被 LLM 推翻；软规则单独在 rules 模式下只标记并放行。",
        "advisory 卡片仅供 LLM 上下文使用，不构成规则谓词。",
        "",
        "| 规则 | 代码说明（原文） | 级别及对应卡片 id |",
        "|---|---|---|",
    ]
    for rule in knowledge.RULE_IDS:
        cards = [c for c in loaded.cards.values() if rule in c.rules]
        groups = []
        for level in knowledge.ENFORCEMENTS:
            ids = sorted(c.id for c in cards if c.enforcement == level)
            if ids:
                groups.append(f"{level}: " + ", ".join(f"`{i}`" for i in ids))
        out.append(f"| {rule} | {cell(' '.join(descriptions[rule]))} | {'; '.join(groups)} |")
    return "\n".join(out)


def render_document(*, include_platform=False):
    root, platform, names, controls = platform_parts()
    prompts = collect_prompts()
    out = [
        "# 核心提示词与工具定义说明",
        "",
        "本文由 `tools/export_prompts.py` 从代码、卡片与配置生成；不调用模"
        "型，不读取任务或评测器配置。",
        "生成命令（仓库根目录，先设置 `SAFELAB_BENCH_ROOT`）：",
        "```powershell",
        ".venv\\Scripts\\python.exe tools/export_prompts.py",
        "```",
        f"SafeLab 提交：`{git_head(REPO)}`；平台提交：`{git_head(root)}`。",
        "提交号表示 HEAD；实际导出读取当前工作树，未提交改动不会另获提交号。无生成时间戳。",
        "哈希统一按 UTF-8、LF 换行计算，保留原文的首尾空白；代码块分隔符前的额外换行不计入。",
        "",
        "## 角色及用户消息的组成",
        "",
        "只有 planner、actor、critic 三个 LLM 角色（`backend.ROLES`）。反思是确定性代码，",
        "重规划复用 planner；没有独立的反思模型或反思系统提示词。",
        "",
        "### 规划与重规划",
        "",
        "`planner.planner_system` 把 `PLANNER_PROTOCOL` 与平台消息从动作标题起的尾部连接，",
        "并按 `PLANNER_HEADINGS` 改写两个标题。完整消息随实体、brief、动作"
        "集变化；下文导出作品自己的固定片段。",
        "`planner.plan_request` 顺序为：观测账本（`summary.render_ledger`）→",
        "训练经验 notes（`backend._start`、`ReflectionLibrary.read`、`lesson_text`）→",
        "本轮运行中审查器拒绝/替换的动作及理由（`Reflexion.refusal_lines`）→",
        "初始规划请求；若为重规划，改为最近动作（`summary.render_recent`）"
        "、已完成阶段、修订原因、剩余工作请求。",
        "不合法计划重试会追加上一次 assistant 回复、校验错误与纠正请求（`Planner.make`）。",
        "",
        "### 执行者",
        "",
        "`Actor.propose` 原样使用平台传入的 system；SafeLab 没有另设执行者系统提示词。",
        "`actor.build_message` 顺序为：阶段计划及检查（`PlanTracker.render`）→",
        "账本摘要（`render_ledger`，聚焦本阶段实体、手持物、枪头及其接触对象）→",
        "最近 k 步（`render_recent`）→更早的平台拒绝按失败种类合并（`render_refused`）→",
        "审查器拒绝/替换清单（`refusal_lines`）→上一回合反馈及无效回复 JSON→",
        "恢复策略短句（`RECOVERY_NOTES`）→剩余步数与实验时间→`CLOSING`。",
        "反馈由 `backend._propose` 合并平台消息与审查器理由；空回复立即重试。",
        "",
        "### 审查器 LLM 通道",
        "",
        "`llm_critic.system_prompt` = `SYSTEM` + 按 id 排序的全部 `Card.brief()` JSON 行；",
        "下文同时导出基础指令和实际拼接的固定系统消息。卡片摘要不是平台内容。",
        "`llm_critic.build_prompt` 顺序为：候选动作→账本相关实体与最近动作→账本未覆盖的命名实体→",
        "物质族→容器 id 提示（若有）→当前资源（`resources.inventory`）→审查请求。",
        "证据核验失败时追加错误清单与重答请求（`LLMChannel.review`）；耗尽"
        "后按 gate 回退，不能称为已确认安全。",
        "",
        "## 作品自己的固定提示词原文",
        "",
    ]
    for prompt in prompts:
        out += [
            f"### `{prompt.name}`",
            "",
            f"来源：`{prompt.source}`。",
            f"SHA-256：`{prompt.digest}`。",
            "",
            fenced(prompt.text),
            "",
        ]
    out += [
        "## 用户消息与系统消息拼接的代码依据",
        "",
        "以下为从源码直接提取的构造函数；动态消息没有一个通用哈希。不是一次真实运行的消息实例。",
        "",
    ]
    out += [
        f"标题替换来自 `{source_ref(planner, 'PLANNER_HEADINGS')}`：",
        "",
        "| 原标题 | 规划器标题 |",
        "|---|---|",
        *(f"| {cell(a)} | {cell(b)} |" for a, b in planner.PLANNER_HEADINGS),
        "",
    ]
    for module, symbol, function in (
        (planner, "planner_system", planner.planner_system),
        (planner, "plan_request", planner.plan_request),
        (planner, "make", planner.Planner.make),
        (actor, "build_message", actor.build_message),
        (llm_critic, "build_prompt", llm_critic.build_prompt),
        (llm_critic, "review", llm_critic.LLMChannel.review),
    ):
        out += [
            f"### `{source_ref(module, symbol)}`",
            "",
            fenced(lf(inspect.getsource(function)), "python"),
            "",
        ]
    schema = canonical_json(planner.PLAN_SCHEMA)
    out += [
        "## 作品自己的计划格式",
        "",
        f"来源：`{source_ref(planner, 'PLAN_SCHEMA')}`；",
        f"排序键、缩进 2 的 JSON 的 SHA-256：`{sha256(schema)}`。",
        "这是规划器回复的格式，不是机器人动作 API。",
        "",
        fenced(schema, "json"),
        "",
        "## 平台提供的提示词与动作定义（不计本作品成果）",
        "",
        "平台路径以下均相对于平台检出。默认只记录来源、名称和哈希，不复制原文。",
        "`src/agent_interface/prompt.py::build_system` 用协议、动作表、实"
        "体目录、brief 构造完整消息；",
        "完整消息依赖运行输入，未读取任务配置，故这里不声称得到某个任务的完整 system 哈希。",
        "`src/agent_interface/action_schema.py` 的参数表、控制动作表、`validate_action` 与",
        "`action_reference` 共同定义工具协议。实际接口使用文本 JSON 动作及校验，",
        "这里不把参数表改称为另一个已实现的 JSON Schema 或 SDK 函数调用接口。",
        "",
        "| 平台对象 | 来源 | SHA-256 |",
        "|---|---|---|",
    ]
    for name, text in platform.items():
        filename = "prompt.py" if name in ("PROTOCOL", "VISUAL_PROTOCOL") else "action_schema.py"
        out.append(f"| `{name}` | `src/agent_interface/{filename}` | `{sha256(text)}` |")
    out += [
        "",
        "协议及动作说明按原文 LF 计算；两张参数表按排序键、缩进 2 的 JSON 计算。",
        "默认动作名称：" + ", ".join(f"`{n}`" for n in names) + "。",
        "接口控制：" + ", ".join(f"`{n}`" for n in controls) + "。",
        "这是 `available_actions()` 的默认集合；显式 allowed_actions 可启"
        "用其他动作或缩小集合，参数细节请在平台文件中查看。",
        "",
        "| 条件 | 对平台提示词和动作表的使用 |",
        "|---|---|",
        "| A | 平台基线后端，使用平台完整系统消息与任务允许的动作表 |",
        "| A′ | 与 A 相同的构造器；brief 的 operating_notes 增加安全提示，因此完整消息不同 |",
        "| B | 执行者原样使用平台 system；规划器提取尾部并改写两个标题，动作仍交给平台解析执行 |",
        "| C | B 的接口加作品审查器；审查器自己的系统消息含知识卡片，动作仍属平台协议 |",
        "",
        "线下含平台原文版本：",
        "```powershell",
        ".venv\\Scripts\\python.exe tools/export_prompts.py --include-platfo"
        "rm-text runs/prompts_private.md",
        "```",
        "该选项只另存到 runs/ 内；默认文档仍不含平台原文。路径会解析 .. 和符号链接后校验。",
        "",
        "## 日志哈希的对应关系",
        "",
        "平台 `src/agent_interface/run_log.py::AgentRunLogger` 将完整输入 system 的 UTF-8 哈希写入",
        "`agent_steps.jsonl.system_prompt_sha256`，并保存 `agent_system_pr"
        "ompt.txt`。平台 digest 不主动规范换行。",
        "**对不上**：本文协议常量/角色片段的哈希不能直接对应这个字段；它还包括动作、实体和 brief。",
        "B/C 中此字段仍是平台外层 system（也是执行者实际使用的 system），"
        "不是规划器变换后的 system，",
        "也不是审查器 system。`safelab_trace.jsonl` 的 proposed.prompt 是执行者用户消息；",
        "当前 trace 未单独记录 planner/actor/critic 各系统消息的哈希（见 b"
        "ackend、trace、resilience）。",
        "未逐条核对既有运行文件；要核对某次运行，应比较它的完整原始 system"
        " 字符串，注意文件读写换行转换。",
        "",
        "## 规则通道",
        "",
        rule_table(),
        "",
        "## 中性提示词关键词检查",
        "",
        "关键词：" + ", ".join(f"`{word}`" for word in KEYWORDS) + "。",
        "检查区分两类：规划器自有系统片段 PLANNER_PROTOCOL；执行者没有自有系统提示词。",
        "为便于复核，也检查下文导出的规划/执行用户消息固定片段（含拒绝提示与恢复短句）。",
        "方法是不区分大小写的子串匹配；行号是所导出原文的行号，列号从 1 开始。",
        "`safe` 命中 `SafeLab` 也原样列出，不自动解释成安全指导。动态账本/"
        "反馈、平台 system 不在此次检查范围。",
        "审查器本身负责安全审查，其 SYSTEM 和含卡片版本不参加中性检查。",
        "A′ 的安全提示位于 `experiments/briefs/*.open.primed.json` 的 oper"
        "ating_notes，是独立对照条件。",
        "",
    ]
    hits = keyword_hits(prompts)
    system_hits = [h for h in hits if h[0] == "safelab.planner.PLANNER_PROTOCOL"]
    out += [
        f"规划器自有系统片段命中数：{len(system_hits)}；执行者自有系统提示词：无；",
        f"规划/执行固定片段全部命中数：{len(hits)}。",
        "",
        "| 片段 | 词 | 行 | 列 | 原行 |",
        "|---|---|---:|---:|---|",
    ]
    out += [
        f"| `{name}` | `{word}` | {line} | {column} | {cell(text)} |"
        for name, word, line, column, text in hits
    ]
    if not hits:
        out.append("| 无命中 | | | | |")
    out += [
        "",
        "## 上下文管理、反思与重试",
        "",
        "账本只接收平台观测与已确认动作（`ledger.Ledger.update`）；expect 只记待确认项，",
        "不按提议预先改变实验状态。完整账本、动作史保留在内存，短期窗口只限制展示，非全库截断。",
        "旧平台拒绝按动作名+去掉数字的错误合并，保留最新代表；审查器拒绝清单跨回合保留，",
        "含被替换动作与最新理由，不随重规划清空（`Reflexion._remember/refusal_lines`）。",
        "重试与触发条件的数字均来自下列表格对应源码/配置，不根据运行结果反推。",
        "",
        "| 配置项 | 代码缺省 | safelab_C_flash.json 的值 | 默认值/配置出处 |",
        "|---|---|---|---|",
    ]
    out += [
        f"| `{a}` | `{cell(b)}` | `{cell(c)}` | `{d}` |" for a, b, c, d in configuration_rows(root)
    ]
    out += [
        "",
        "默认值 null 表示未设置；critic.llm_trigger 的 null 在 gate 中按模式选择 risk/always。",
        "planner.mode 的条件表达式取决于有无 planner 角色。"
        "平台限额与后端缺省值也直接取自平台接口代码。",
        "",
        mechanism_table(),
        "",
        "触发逻辑：",
        "",
        "- 无效回复：Reflexion.assess 选择 self_correct，下一步带平台错误"
        "；它自身没有一次性的计数上限，停止上限由平台 limits 管。",
        "- 动作前置条件失败：先 remediate；连续失败或同类失败达到对应阈值"
        "时 replan。成功清连续计数，重规划清分类计数。",
        "- 阶段动作数达到 max(阶段 allowance, MIN_MISMATCH_ACTIONS) 且 expected 未满足时重规划；",
        "  提前 finish 且仍有未满足 expected 时，在额外重规划额度内再请求计划和动作。",
        "- 空回复在角色内重试；规划 JSON 无效会追加校验错误纠正。规划失败"
        "、未配置规划模型或重规划额度用尽时转固定计划。",
        "- 审查驳回先要求换动作，达到单步阈值时重规划，超过阈值时 finish；"
        "同动作跨回合达到重复上限也 finish。",
        "  动作键取动作名与字符串参数，排除 reason 与数值；改写记入清单，"
        "但不增加两种驳回停止计数。",
        "- 双通道 hard 规则优先；改写须通过白名单、当前资源可行性及无 hard"
        " 规则复查。LLM 无可用判断时按规则回退。",
        "- 角色调用异常只有可重试错误才退避；用尽重试转 BackendError。SDK "
        "的 max_retries 与 SafeLab 外层 retries 是不同层。",
        "  预算检查用累计估计费用加下次调用预留，可能超出预算时返回 finish"
        "；safe_terminate 是控制路径名称，不是安全评测结论。",
        "- ReflectionLibrary 只读取 train 条目、只有 train brief 可写；测"
        "试 brief 不写库。正式实验另按预注册在每次运行前隔离旧库。",
        "",
        "实现位置：`reflexion.Reflexion.assess/critic_rejection/replanned`"
        "、`planner.PlanTracker`、",
        "`backend.SafeLabBackend._decide/_replan/_review/_safe_stop`、`res"
        "ilience.GuardedRole/Budget`。",
        "",
    ]
    if include_platform:
        out += ["## 平台原文（仅供 runs/ 下线下核对）", ""]
        for name, text in platform.items():
            out += [f"### `{name}`", "", fenced(text), ""]
    return "\n".join(out)


def private_output_path(value):
    target = Path(value).expanduser().resolve()
    runs = (REPO / "runs").resolve()
    # A symlinked runs root must not alias another directory in the checkout.
    if runs != REPO.resolve() / "runs" or target == runs or not target.is_relative_to(runs):
        raise ValueError("含平台原文的输出路径必须在本仓库 runs/ 下")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "docs/prompts_and_tools.md")
    parser.add_argument("--include-platform-text", type=Path, metavar="OUTPUT")
    args = parser.parse_args(argv)
    try:
        private = (
            private_output_path(args.include_platform_text) if args.include_platform_text else None
        )
        if private is not None and private == args.output.resolve():
            raise ValueError("平台原文另存路径不能与默认文档输出相同")
        public_text = render_document()
        private_text = render_document(include_platform=True) if private else None
    except (bench.BenchNotFound, ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(public_text, encoding="utf-8", newline="\n")
    if private:
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(private_text, encoding="utf-8", newline="\n")
    for prompt in collect_prompts():
        print(f"{prompt.name}: {prompt.digest[:12]}")
    print(f"keyword_hits={len(keyword_hits(collect_prompts()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
