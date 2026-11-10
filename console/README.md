# SafeLab 控制台（基础版）

只读地查看 `runs/` 下的运行目录：智能体想做什么、审查器怎么判、依据是什么、实际执行了什么、状态怎么变。
纯 Python 标准库后端加原生 HTML、CSS、JS，不依赖任何 CDN 或联网安装，断网可用。

## 启动

```powershell
.venv\Scripts\python.exe console\server.py --runs runs
```

浏览器打开 <http://127.0.0.1:8765/>。选项：`--port`、`--host`（默认只监听本机）。
直接打开某个运行：`http://127.0.0.1:8765/?run=dry/C_flash_wsopen_1`。
Ctrl+C 退出；由页面启动的子进程会一并结束。

## 文件

| 文件 | 作用 |
|---|---|
| `server.py` | HTTP 服务、JSON 接口、离线运行的启动 |
| `runstore.py` | 数据层：读运行目录，把 trace 事件归到每一步，重建账本，判定来源 |
| `web/index.html`、`web/app.js`、`web/style.css` | 单页界面 |
| `tests/test_console_runstore.py`、`tests/test_console_server.py` | 测试 |

## 数据来源与读取的文件

运行目录里只读这些：`agent_run.json`、`agent_steps.jsonl`、`agent_plan.json`、`agent_conversation.json`、
`agent_system_prompt.txt`、`trajectory_evaluation.json`、`safelab_trace.jsonl`。
不读平台的 `configs/knowledge/`，也不读任务的 criteria；评测器内容只来自运行目录里已有的 `trajectory_evaluation.json`。

页面顶部固定显示数据来源：

- **仿真**：`agent_run.json` 的 `environment.environment` 是 `simulation`。
- **干跑（离线推演）**：`environment` 是 `dry_run`，或观测的 `source` 是 `dry_run`。干跑不给任何安全、完整性、目标结论。
- **录像回放**：回放模式下显示，旁边保留“原始运行”的来源。
- **来源未知**：目录里没有说明来源，按未评估处理。仅有评测文件不足以判定为仿真。

评测器面板的措辞规则：评测器的 `no_detected_consequence` 显示为“未检出后果（仅限已声明覆盖范围，不等于安全）”；
`not_assessed`、`unknown` 和任何没见过的状态都显示为“未评估”。干跑旁边若有评测文件（计划级推演），会加黄色横幅说明它不是仿真结果。

## 面板

1. **运行列表**：按条件、任务、模型、来源筛选。“启动离线运行”只开放 `configs/agents/safelab_B.json`、`safelab_C.json`
   （均为 `plan_replay`，规则通道，不调用模型），调用 `scripts/run_dry.py`，产物写到 `runs/dry/<条件>_<任务>_console_<时间>`。
   启动前服务端会再检查配置：任一角色不是 `plan_replay`、审查器不是纯规则、或文件里出现 `api_key`/`base_url` 就拒绝。
2. **阶段计划**：当前计划版本及每个阶段的状态，随回放或日志推进；重规划后显示新版本和原因。
3. **每步时间线**：候选动作 → 审查结论 → 实际执行 → 回读变化。审查结论分规则通道（规则 id、知识卡片 id、证据路径及取值、
   改写建议）和 LLM 通道（是否触发、结论、卡片、证据、置信度）。驳回的步骤红色左边框，改写的橙色；同一步内多次提议、
   驳回后重提议都按顺序列出，并标注是按驳回理由重提议还是重规划后提议。反思、重规划、阶段切换列在同一步下面。
4. **账本**：容器、枪头（状态与接触史）、设备、未确认项，以及本步 diff；本步变化的条目高亮。点击任一步切换。
5. **Token、费用、时延**：合计、按角色、每步“可见时延”条形图（超过 15 秒标红，对应执行规划 S3.4 的目标）。
6. **评测器**：见上。

## 三种查看方式

- **静态查看**：显示整个运行。
- **实时跟踪**：每 1.5 秒按文件签名轮询，日志文件增长时自动追加新步骤并跟随最新一步；运行结束后自动转为静态。
  最近 120 秒内有写入且没有 `run_end` 的运行被视为“进行中”，选择它时默认进入实时跟踪。
- **录像回放**：按日志里每个事件的原始时间戳回放，可播放、暂停、单步、退一步、拖动进度，倍速 1/2/5/10/30/100，
  可勾选“空档最多等 2 秒”压缩模型思考的长空档。

## 没有 safelab_trace 的运行（条件 A、脚本回放）

用 `agent_steps.jsonl` 退化显示：每个平台调用一步，标“无审查器”，没有阶段计划；回读变化来自相邻两次观测的差，
账本面板是由观测还原的状态（没有枪头接触史），并明确标注。

## JSON 接口

`GET /api/runs`、`/api/run?id=<id>[&sig=<sig>]`（签名未变时返回 `{"unchanged": true}`）、`/api/ledger?id=&call=`、
`/api/step?id=&step=`（完整的平台记录，含完整回复和推理）、`/api/options`、`/api/jobs`；`POST /api/start`。
`id` 是相对 `--runs` 的路径，例如 `dry/C_flash_wsopen_1`；含 `..` 或指向目录外的 id 一律拒绝。
`POST` 带有 `Origin` 且与 `Host` 不同时返回 403。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_console_*.py
```

用合成运行目录测数据层和接口；用到真实录像（`runs/dry/C_flash_wsopen_1`）的用例在文件缺失时跳过；
真正启动离线运行的用例用 `bench` 夹具，平台不可用时跳过。

## 已知限制

- 只做过静态检查和接口测试，以及在内置浏览器里的冒烟检查；没有做过多浏览器、多分辨率的视觉验收。
- 仿真运行没有真实样本：`trajectory_evaluation.json` 的显示按平台 `evaluator.py` 的输出结构编写，没有拿真实仿真产物验证过。
- 执行规划 S3.3 第 6 项里“用平台 `scripts/consequence_trace.py` 得到后果对应到哪一步”没有做：控制台不调用平台脚本；
  评测器面板只列出评测文件里的后果记录。
- 实时跟踪靠轮询文件，每次整文件重解析（约几百 KB 内无感）；日志特别大时会变慢。
- “进行中”只按文件最近修改时间和有无 `run_end` 判断，进程被杀死的运行 120 秒后显示“日志已停止更新”。
- `agent_conversation.json`、`agent_system_prompt.txt` 不在界面显示；模型回复与推理摘要在页面里截断为 4000 字符，完整内容见 `/api/step`。
- 回放以事件时间戳为准：同一毫秒内的事件逐个间隔至少 30 毫秒显示；没有 `safelab_trace` 的运行，同一步的所有事件共用平台记录时间，回放时一步一跳。
- 页面启动的运行只能是条件 B/C 的离线脚本配置，任务限 `waste_segregation`、`cell_lysis`；不提供带模型、费用的配置。
- 按设计只监听本机；没有登录，不要把 `--host` 改成对外地址。
