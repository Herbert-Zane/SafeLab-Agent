"""Write docs/architecture.svg: the system diagram, coloured by ownership.

Blue is this package (SafeLab-Agent), orange is the platform it runs on (someone
else's work, not claimed), grey dashed is an external service. The text states
only what the code does; see README.md "架构" and docs/originality.md for the
file-level mapping. Standard library only; the output is deterministic.

    python tools/draw_architecture.py            # writes docs/architecture.svg

PNG (Windows, any Chromium browser):

    msedge --headless --disable-gpu --hide-scrollbars --window-size=1800,1120 \
        --screenshot=docs/architecture.png docs/architecture.svg
"""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

W, H = 1800, 1120
FONT = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif"

OURS = {"fill": "#e6f0fa", "stroke": "#1f5fa8", "head": "#174a85"}
OURS_INNER = {"fill": "#ffffff", "stroke": "#1f5fa8", "head": "#174a85"}
PLAT = {"fill": "#fdf0df", "stroke": "#b0661a", "head": "#8a4d10"}
PLAT_INNER = {"fill": "#ffffff", "stroke": "#b0661a", "head": "#8a4d10"}
EXT = {"fill": "#f4f4f4", "stroke": "#6b6b6b", "head": "#444444"}
INK = "#222222"
RED = "#c0392b"

out: list[str] = []


def text(x, y, s, size=14, weight="normal", fill=INK, anchor="start"):
    out.append(
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}">{escape(s)}</text>'
    )


def box(x, y, w, h, style, title=None, lines=(), sub=None, dash=None, width=1.6,
        title_size=16, line_size=14, gap=21):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{style["fill"]}" '
        f'stroke="{style["stroke"]}" stroke-width="{width}"{extra}/>'
    )
    cy = y + 26
    if title:
        text(x + 14, cy, title, size=title_size, weight="bold", fill=style["head"])
        if sub:
            text(x + w - 14, cy, sub, size=12, fill=style["head"], anchor="end")
        cy += gap + 4
    for line in lines:
        text(x + 14, cy, line, size=line_size)
        cy += gap


def arrow(points, color=INK, dash=None, both=False, width=1.8):
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    marker = "red" if color == RED else "ink"
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    start = f' marker-start="url(#s-{marker})"' if both else ""
    out.append(
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{extra}'
        f' marker-end="url(#e-{marker})"{start}/>'
    )


def build() -> str:
    out.clear()
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}">'
    )
    out.append("<defs>")
    for name, color in (("ink", INK), ("red", RED)):
        out.append(
            f'<marker id="e-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
            f'markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{color}"/>'
            "</marker>"
        )
        out.append(
            f'<marker id="s-{name}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" '
            f'markerHeight="8" orient="auto"><path d="M10 0 L0 5 L10 10 z" fill="{color}"/>'
            "</marker>"
        )
    out.append("</defs>")
    out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

    # ---- title and legend -------------------------------------------------
    text(40, 58, "SafeLab-Agent 系统架构", size=28, weight="bold")
    text(40, 88, "按归属着色：智能体只通过平台的后端注册接口接入，", size=14)
    text(40, 110, "拿不到评测器的任何状态。", size=14)

    box(1280, 30, 480, 178, {"fill": "#ffffff", "stroke": "#999999", "head": INK},
        title="图例", width=1.0)
    for i, (style, label, dash) in enumerate((
        (OURS, "本次参赛新增：SafeLab-Agent（独立包）", None),
        (PLAT, "平台 BSLBench：既有平台，作为运行环境，不申报", None),
        (EXT, "外部服务", "6 4"),
    )):
        yy = 78 + i * 30
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(
            f'<rect x="1296" y="{yy - 15}" width="34" height="20" rx="4" fill="{style["fill"]}" '
            f'stroke="{style["stroke"]}" stroke-width="1.6"{extra}/>'
        )
        text(1342, yy, label, size=14)
    arrow([(1296, 168), (1330, 168)])
    text(1342, 173, "数据流", size=14)
    arrow([(1420, 168), (1454, 168)], color=RED, dash="6 4")
    text(1466, 173, "驳回 / 不允许的通路", size=14)

    # ---- external LLM ------------------------------------------------------
    box(340, 126, 440, 72, EXT, title="LLM 服务（外部）", sub="DeepSeek API",
        lines=["规划器、执行者、审查器 LLM 通道的模型调用"], dash="6 4")
    arrow([(560, 198), (560, 240)], both=True)

    # ---- SafeLab container -------------------------------------------------
    box(40, 240, 1040, 680, OURS, width=2.4)
    text(58, 272, "SafeLab-Agent（本次参赛新增 · 独立包 · 不拷贝平台代码）", size=18,
         weight="bold", fill=OURS["head"])

    box(60, 295, 1000, 70, OURS_INNER, title="接入与回合编排",
        sub="backend.py · bench.py · launch.py",
        lines=["注册 safelab 后端；入口处再做一次防泄漏检查（assert_no_evaluator_state）；"
               "每回合向平台返回一个动作"])

    box(60, 395, 240, 365, OURS_INNER, title="记忆", sub="ledger.py · summary.py",
        lines=[
            "执行账本（工作记忆）",
            "　容器成分与体积、开闭盖、",
            "　枪头状态与接触史、设备",
            "短期窗口",
            "　最近 6 步的动作与结果",
            "拒绝清单",
            "　平台拒绝与审查器驳回，",
            "　连同理由保留整次运行",
            "反思经验库（长期）",
            "　只有训练任务写入，",
            "　任何运行只读训练条目",
            "安全知识卡片 24 张",
            "　来源：公开 SOP / MSDS",
        ])
    box(60, 790, 240, 100, OURS_INNER, title="运行记录", sub="trace.py",
        lines=["每个事件一行：提议、审查、", "执行、反思、用量与费用"])

    box(340, 395, 440, 105, OURS_INNER, title="规划器（LLM）", sub="planner.py",
        lines=["把目标拆成阶段：子目标、前置条件、预期观测",
               "按账本逐步检查；偏离时重规划（上限 3 次）"])
    box(340, 540, 440, 105, OURS_INNER, title="执行者（LLM）", sub="actor.py",
        lines=["每回合在当前阶段提出一个原子动作",
               "系统提示词原样采用平台的中性提示，不加安全提示"])
    box(340, 685, 440, 205, OURS_INNER, title="审查器（执行前审查，仅条件 C）", sub="critic/")
    for (bx, bw, head, l1, l2) in (
        (352, 134, "规则通道", "R1–R6", "依据账本证据"),
        (494, 148, "LLM 通道", "按风险触发", "卡片 + 证据核验"),
        (650, 118, "门控", "硬规则优先", "改写受限"),
    ):
        out.append(
            f'<rect x="{bx}" y="724" width="{bw}" height="92" rx="6" fill="{OURS["fill"]}" '
            f'stroke="{OURS["stroke"]}" stroke-width="1.2"/>'
        )
        text(bx + bw / 2, 747, head, size=15, weight="bold", fill=OURS["head"], anchor="middle")
        text(bx + bw / 2, 772, l1, size=13, anchor="middle")
        text(bx + bw / 2, 794, l2, size=13, anchor="middle")
    arrow([(486, 770), (494, 770)], width=1.4)
    arrow([(642, 770), (650, 770)], width=1.4)
    text(354, 846, "结论：放行 / 驳回 / 改写", size=14)
    text(354, 868, "每条结论带规则号、卡片号和证据路径，可事后核查", size=14)

    box(820, 395, 220, 205, OURS_INNER, title="反思与恢复", sub="reflexion.py",
        lines=["平台拒绝 → 局部纠正；", "　同类两次 → 重规划",
               "审查器驳回 → 换动作；", "　再驳回 → 重规划 → 终止",
               "预期观测不符 → 重规划", "没有独立的反思 LLM"])
    box(820, 630, 220, 130, OURS_INNER, title="调用保护", sub="resilience.py",
        lines=["模型调用超时与退避重试", "单次运行费用预算熔断", "故障注入（测试用）"])

    # flows inside SafeLab
    arrow([(180, 365), (180, 395)])
    text(190, 385, "观测回读", size=12)
    for yy in (447, 592, 760):
        arrow([(300, yy), (340, yy)])
    arrow([(640, 500), (640, 540)])
    text(650, 525, "当前阶段与子目标", size=12)
    arrow([(640, 645), (640, 685)])
    text(650, 670, "候选动作", size=12)
    arrow([(440, 685), (440, 645)], color=RED, dash="6 4")
    text(430, 670, "驳回 + 理由", size=12, fill=RED, anchor="end")
    arrow([(820, 447), (780, 447)])
    arrow([(780, 852), (1054, 852), (1054, 365)])
    text(1046, 842, "放行或改写后的动作", size=12, anchor="end")

    # ---- platform container -----------------------------------------------
    box(1280, 240, 480, 680, PLAT, width=2.4)
    text(1298, 272, "BSLBench 平台（既有平台 · 运行环境 · 不申报）", size=18,
         weight="bold", fill=PLAT["head"])
    box(1300, 295, 440, 125, PLAT_INNER, title="Agent 接口", sub="src/agent_interface/",
        lines=["AgentEnvironment；观测白名单（防泄漏）",
               "系统提示词与动作表、动作解析、计价",
               "基线后端：条件 A / A′ 不经过 SafeLab"])
    box(1300, 450, 440, 115, PLAT_INNER, title="原子动作执行", sub="Engine + Isaac Sim",
        lines=["拿放、开闭盖、装卸枪头、吸液、排液、涡旋、",
               "孵育、倾倒等，由仿真中的机器人执行；",
               "返回执行回读，或拒绝并给出原因"])
    box(1300, 595, 440, 85, PLAT_INNER, title="ScientificGraph 科学状态图",
        lines=["执行观测 → 带证据的科学事件"])
    box(1300, 720, 440, 170, PLAT_INNER, title="隔离的评测器（智能体与审查器不可见）",
        lines=["后果模型：不相容混合、交叉污染等",
               "输出：危险后果 / 完整性失败 / 终态目标",
               "只在回合结束后产出，不回传智能体",
               "未覆盖的情形记“未评估”，不当作安全"],
        dash="9 5", width=2.4)
    arrow([(1520, 420), (1520, 450)])
    arrow([(1520, 565), (1520, 595)])
    text(1530, 585, "执行观测", size=12)
    arrow([(1520, 680), (1520, 720)])
    text(1530, 705, "科学事件", size=12)

    # interface between the two
    arrow([(1300, 316), (1062, 316)])
    text(1180, 308, "观测（白名单）+ 上一步反馈", size=13, anchor="middle")
    arrow([(1060, 346), (1298, 346)])
    text(1180, 364, "每回合一个平台格式动作", size=13, anchor="middle")

    # the path that does not exist
    out.append(
        f'<path d="M 1300 805 L 1082 805" fill="none" stroke="{RED}" stroke-width="1.8" '
        f'stroke-dasharray="6 4"/>'
    )
    out.append(
        f'<path d="M 1170 793 L 1194 817 M 1194 793 L 1170 817" stroke="{RED}" '
        f'stroke-width="3.2" fill="none"/>'
    )
    text(1182, 783, "评测结果不回传", size=13, fill=RED, anchor="middle")
    text(1182, 838, "判据、后果模型", size=12, fill=RED, anchor="middle")
    text(1182, 856, "对智能体不可见", size=12, fill=RED, anchor="middle")

    # ---- console -----------------------------------------------------------
    box(40, 960, 1720, 104, OURS, title="控制台（本次参赛新增 · 只读日志，不参与决策）",
        sub="console/", width=2.4,
        lines=["运行列表 · 阶段计划 · 每步时间线（候选动作 → 审查结论 → 实际执行 → 回读变化）"
               "· 账本 · Token / 费用 / 时延 · 评测器结果（回合结束后）",
               "静态查看 / 实时跟踪 / 录像回放；离线干跑没有评测，界面标“未评估”，不冒充仿真结果"])
    arrow([(180, 890), (180, 960)])
    text(192, 946, "safelab_trace.jsonl", size=12)
    arrow([(1520, 920), (1520, 960)])
    text(1532, 946, "平台日志与评测输出（回合结束后）", size=12)

    text(40, 1096, "条件 A / A′：平台基线后端，不经过 SafeLab（A′ 在任务 brief 里加一句安全提示）；"
         "条件 B：SafeLab 去掉审查器；条件 C：完整版。", size=13, fill="#444444")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="docs/architecture.svg")
    args = parser.parse_args()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(), encoding="utf-8", newline="\n")
    print(path)


if __name__ == "__main__":
    main()
