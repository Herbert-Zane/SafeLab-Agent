# 原创性与代码归属说明

## 平台与本作品的边界

ScientificGraph、Engine、后果模型、评测器和平台 `src/agent_interface/` 是他人的工作，不作为本作品成果。本作品通过平台 `AgentEnvironment` 所在的接口层接入；实际实现是注册一个后端，让平台的 episode 循环调用 `generate(system=..., messages=...)`，不是在 SafeLab 内重新实现环境或评测器。

本仓库代码按参赛新增实现归档，不拷贝平台源码；运行时导入、继承平台接口不改变平台的归属。下表依据实际模块划分说明工程边界。行数与提交历史可以核查实现规模，不能单独证明独立创作过程或个人工时。

| 归属 | 内容 | 可核查位置 |
|---|---|---|
| 平台提供 | ScientificGraph、Engine、后果识别与轨迹评测 | 本仓库不含实现 |
| 平台提供 | AgentEnvironment、干跑/仿真环境、观测白名单、系统协议、动作表、动作解析、基线后端、计价与外层日志 | 平台 `src/agent_interface/`、`run_agent.py`、`main.py` |
| 本作品新增 | 后端注册与回合编排、阶段计划与检查、执行者消息拼接 | `src/safelab/bench.py`、`launch.py`、`backend.py`、`planner.py`、`actor.py` |
| 本作品新增 | 回读账本、枪头接触史、摘要、拒绝记忆与训练经验库、失败恢复及调用保护 | `ledger.py`、`summary.py`、`reflexion.py`、`resilience.py` |
| 本作品新增 | 卡片结构与物质族映射、规则通道、模型证据核验、门控及改写限制 | `src/safelab/critic/` |
| 本作品新增 | 事件记录、响应元数据扩展、部署入口、测试、离线评测与实验脚本、控制台、文档工具 | `trace.py`、`openai_reasoning.py`、`scripts/`、`tests/`、`eval/`、`experiments/`、`console/`、`tools/` |

### 接入符号与模块

- `src/safelab/bench.py::ensure_importable` 将平台 `src/` 和根目录追加到 `sys.path`；`register` 从 `agent_interface.backends` 导入 `backend_providers`、`register_backend`，以 `safelab` 注册 `_build`。
- `src/safelab/launch.py` **没有直接导入平台模块**，只处理参数、路径以及运行目录和 brief 环境变量。
- `scripts/run_dry.py` 注册后调用平台模块 `run_agent.main`；`scripts/run_sim.py` 注册后用 `runpy.run_path` 在同一进程执行平台 `main.py`。
- `src/safelab/backend.py` 实际导入：`agent_interface.action_schema.available_actions`；`agent_interface.backends` 的 `BackendError`、`BackendRefusal`、`BackendReply`、`create_backend`；`agent_interface.observation.assert_no_evaluator_state`；`agent_interface.parsing.extract_action`；`agent_interface.pricing.price_for`。
- `src/safelab/openai_reasoning.py` 继承 `agent_interface.backends.openai_compatible.OpenAICompatibleBackend`，扩展响应中的推理与用量元数据记录。请求构造仍来自平台；不把兼容后端整体申报为新增。
- 审查器通过 `critic/gate.py::_guard` 使用 `agent_interface.observation` 的同一个泄漏检查；独立审查器配置也可通过 `agent_interface.backends.create_backend` 创建后端，计价可使用 `agent_interface.pricing.price_for`。

平台提示词和工具定义的来源、哈希、条件用法见 [prompts_and_tools.md](prompts_and_tools.md)。默认导出不包含平台提示词或参数表原文；原文仅能另存到被 git 忽略的 `runs/`。

## 不泄题的做法

智能体与审查器的数据流输入是公开给智能体的观测、候选动作及自身账本/知识卡片，不传入评测器配置。平台 `src/agent_interface/observation.py::assert_no_evaluator_state` 递归拒绝携带评测器字段的观测；SafeLab 在 `src/safelab/backend.py::SafeLabBackend.generate` 再检查一次，而不是仅相信消息解析结果。

`src/safelab/critic/gate.py::_guard` 在平台可导入时重复执行同一个检查；平台不可导入时该检查跳过，所以独立离线调用不能声称获得了平台的强制校验。`ledger.py` 只依赖观测与确认动作，`obs.py` 只分解平台消息，`critic/knowledge.py` 从包内 YAML 加载卡片和物质族，不从平台知识目录取资料。

已有 `tests/test_backend.py::test_an_observation_carrying_evaluator_state_is_refused` 验证携带禁止字段的观测会被拒绝；`tests/test_critic_cards.py` 检查卡片引用来自 `docs/sources.md` 已核对条目。这里没有声称对任意本地文件实施访问控制：`sys.path` 导入和观测检查不是操作系统沙箱，也没有另建一套全面的静态信息流证明。文档生成工具（`tools/`）不读取任务配置中的评测字段，不读取平台 `configs/knowledge/`。

## 向平台提交的修复

开发中向平台提交过 8 个 PR（#43–#50，其中 7 个是修复，#48 是给智能体接口新增一个可选的单步仿真时长上限），已由平台维护者合并。这些改动属于平台仓库，不计入本作品代码量。

核对方式：平台主分支（`36914f5`）的历史里有这 8 个 PR 的合并提交。各 PR 的内容见平台仓库，这里不展开。

## 代码统计

下方片段由 `tools/code_stats.py` 实际输出填入。当前任务新建且尚未跟踪的文件不计入；统计不会为了纳入它们而暂存或提交。

<!-- code-stats:start -->
统计提交：`f3bc7978cf4ca322bde04e6b67f87ad1b45475bc`。
生成命令：`.venv\Scripts\python.exe tools/code_stats.py`。
文件范围为 git ls-files，行内容来自当前工作树；未跟踪文件不计，未提交的已跟踪修改会计入。
计物理行（末行无换行也计一行）；内容行、空行、纯注释行互斥；含代码的行尾注释仍属内容行。
Python 用 tokenize 识别 # 注释，docstring 计入内容行；YAML 只计以 # 开头的纯注释行。
前端识别 //、/* */ 或 HTML 注释；文档只识别 HTML 注释。它是行数统计，不是贡献度或开发工时证明。
未纳入上述类别的文件 144 个（如 JSON/JSONL、CSV、TOML、许可文件）；不读取其内容。

| 目录 | 类别 | 文件 | 内容行 | 空行 | 纯注释行 | 合计行 |
|---|---|---:|---:|---:|---:|---:|
| .github | 其他 YAML | 1 | 25 | 4 | 3 | 32 |
| console | Python 源码 | 2 | 1340 | 203 | 31 | 1574 |
| console | 前端 | 3 | 1427 | 125 | 32 | 1584 |
| console | 文档 | 1 | 152 | 35 | 0 | 187 |
| docs | 文档 | 7 | 4814 | 1792 | 2 | 6608 |
| eval | Python 源码 | 11 | 2295 | 469 | 57 | 2821 |
| eval | 文档 | 22 | 1467 | 289 | 0 | 1756 |
| experiments | Python 源码 | 4 | 861 | 109 | 4 | 974 |
| experiments | 文档 | 6 | 768 | 192 | 0 | 960 |
| scripts | Python 源码 | 2 | 78 | 18 | 0 | 96 |
| src | Python 源码 | 19 | 4708 | 669 | 81 | 5458 |
| src | YAML 卡片 | 24 | 518 | 0 | 0 | 518 |
| src | 其他 YAML | 1 | 96 | 11 | 16 | 123 |
| src | 文档 | 1 | 84 | 36 | 0 | 120 |
| tests | 测试 | 32 | 6148 | 1363 | 81 | 7592 |
| tools | Python 源码 | 7 | 1700 | 210 | 22 | 1932 |
| （根目录） | 文档 | 1 | 106 | 49 | 0 | 155 |
| **合计** | | **144** | **26587** | **5574** | **329** | **32490** |

HEAD 可达提交数：40；首个提交日期：2026-11-09；末个提交日期：2026-11-14。日期取 git log 的作者日期（提交中记录的时区），不输出作者身份。

| 日期 | 提交数 |
|---|---:|
| 2026-11-09 | 3 |
| 2026-11-10 | 8 |
| 2026-11-11 | 5 |
| 2026-11-12 | 15 |
| 2026-11-13 | 3 |
| 2026-11-14 | 6 |
<!-- code-stats:end -->

## 第三方依赖

以下来自本仓库 `pyproject.toml`，不把平台环境的全部依赖归为本包依赖：

| 类型 | 声明 |
|---|---|
| Python 版本 | `>=3.11` |
| 构建依赖 | `setuptools>=61`，构建后端 `setuptools.build_meta` |
| 运行依赖 | `pyyaml>=6` |
| 可选 test | `pytest>=8` |
| 可选 dev | `pytest>=8`、`ruff>=0.6` |

控制台后端使用 Python 标准库，前端为原生 HTML/CSS/JS（`console/README.md`）。模型 SDK 随实际选用的平台后端配置安装；DeepSeek 兼容接口使用 `openai` SDK，该 SDK 没有在本包 `dependencies` 中声明。平台、Isaac 及其资产仍需另行准备。

## 知识卡片来源

卡片依据限于公开的 SOP / MSDS（SDS）及 [sources.md](sources.md) 所列公开手册、规范与指导材料，不使用评测器知识。来源等级须保留：例如厂商博客和从一般原则推广的条目不能写成强制机构规范；容量卡片是 P 级回读物理约束，不是文献结论。卡片数量、规则关联与硬软级别由提示词导出脚本读取实际文件生成，见 [prompts_and_tools.md](prompts_and_tools.md)。
