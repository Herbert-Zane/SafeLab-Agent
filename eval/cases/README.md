# 开发集迁移记录（2026-11-12）

当前平台：`5837ec3`。主集从任务场景和计划生成，`eval/labels.py` 未改。
本次没有调用模型 API 或运行仿真。

## 历史 natural 数据

`natural.jsonl` 原样保留，来自旧平台 A/B 日志；动作、库存和工具状态采用旧语义，
在新平台账本下不再适用。`build_cases.py` 不再重新生成它。
`critic_bench.py` 默认在打开文件前跳过它；仅历史复查可传 `--include-legacy-natural`。
原有 `--no-natural` 仍可使用。

文件 SHA-256：`896aa2846d5f5db98455c58c63c42db26db6d609c227bc353a455f0786939698`。

## 数量对比

| 文件 | 迁移前 | 迁移后 |
|---|---:|---:|
| `fault.jsonl` | 7 | 5 |
| `hard_negative.jsonl` | 39 | 28 |
| `mutation.jsonl` | 49 | 40 |
| `natural.jsonl` | 49 | 49 |
| `reference.jsonl` | 128 | 193 |
| 主集（默认评测） | 223 | 266 |
| 含历史 natural 的全部文件 | 272 | 315 |

逐文件、类别、算子对比（`-` 表示没有 operator 字段）：

| 文件 | 字段 | 类别/算子 | 迁移前 | 迁移后 |
|---|---|---|---:|---:|
| `fault.jsonl` | category | incompatible_mix | 1 | 1 |
| `fault.jsonl` | category | spill | 1 | 1 |
| `fault.jsonl` | category | tip_carryover | 2 | 1 |
| `fault.jsonl` | category | tip_into_stock | 3 | 2 |
| `fault.jsonl` | operator | - | 7 | 5 |
| `hard_negative.jsonl` | category | none | 39 | 28 |
| `hard_negative.jsonl` | operator | H1 | 4 | 4 |
| `hard_negative.jsonl` | operator | H2 | 9 | 6 |
| `hard_negative.jsonl` | operator | H3 | 12 | 6 |
| `hard_negative.jsonl` | operator | H4 | 6 | 3 |
| `hard_negative.jsonl` | operator | H6 | 8 | 9 |
| `mutation.jsonl` | category | incompatible_mix | 3 | 3 |
| `mutation.jsonl` | category | open_agitation | 12 | 6 |
| `mutation.jsonl` | category | overfill | 6 | 6 |
| `mutation.jsonl` | category | tip_into_stock | 28 | 25 |
| `mutation.jsonl` | operator | M1 | 3 | 3 |
| `mutation.jsonl` | operator | M2 | 12 | 6 |
| `mutation.jsonl` | operator | M3 | 18 | 16 |
| `mutation.jsonl` | operator | M4 | 10 | 9 |
| `mutation.jsonl` | operator | M5 | 6 | 6 |
| `natural.jsonl` | category | incompatible_mix | 6 | 6 |
| `natural.jsonl` | category | none | 27 | 27 |
| `natural.jsonl` | category | tip_into_stock | 16 | 16 |
| `natural.jsonl` | operator | - | 49 | 49 |
| `reference.jsonl` | category | none | 128 | 193 |
| `reference.jsonl` | operator | - | 128 | 193 |

## 数量变化原因与可达性边界

- reference 128→193：新平台增加设备、双臂诊断、RNA 等任务；裂解和废液计划增加工具取放。
  旧 `viral_inactivation_chemical` 已移除，其 reference 17、fault 2、mutation 8、hard_negative 12 不再产生。
- 脚本 `hold_s` 没有原子 action，不能交给 DryRunEnvironment。
  纯停留场景 `generic_receiving_layout` 不纳入生成/改名集合；其他场景在脚本停留或首个干跑拒绝处停止采集，
  不生成该点以后的不可达状态。
- RNA 参考计划第 17 步（从 0 起）在干跑因容量失败，标签规则也判为 overfill。
  跳过该 safe 候选，未放宽规则或修改平台；截断前可达不代表整套 RNA 流程能干跑通过。
- fault 7→5：移除的旧病毒灭活任务贡献 2 条，其他任务不变。
- mutation 49→40：旧病毒灭活任务减少 8 条；裂解 M3 保留用过的移液器后不能执行中途需要空手的混匀步骤，
  因此少 1 条。M3 去掉换工具动作并保留其他操作，仍不可达的候选跳过。M1/M2/M4 的含义和标签不变。
- M5 仍为 6 条，但改用当前账本中同型号、fresh 且 available 的显式 tip_id；库存耗尽时跳过，绝不复用已用枪头。
- hard_negative 39→28：旧病毒灭活任务减少 12 条，新 RNA 任务新增 H6 1 条，其余不变。
- 参考计划的首个被拒原子动作仍可形成待审查状态，沿用旧生成器的边界。
  干跑不支持某动作或执行失败不代表安全结论。mutation、fault、hard_negative 的 prefix 均由干跑执行得到。

## 派生数据

- `eval/variants/renamed/` 从新 `runs/variants/{tasks,briefs,mappings}` 同步，清除平台已移除的旧派生任务。
  改名脚本保留 protocol 的角色和材料词汇，仅替换 vessels 的实体值；参数 provenance 保留原文。
- `eval/robustness/make_missing.py` 已重新生成。
  `cases.json` 的所有 task/brief 路径均可在仓库或目标平台解析，因此无需修改清单。
- `eval/sim_check/export.py` 仅选择被测动作前 prefix 长度 ≤40 的候选，含被测动作最多 41 步。
  20 个导出计划的 M1/M2/M3/M4/M5 分布为 3/6/6/4/1；物理可达性和后果标签仍须由 GPU 仿真确认。

## 留出集调查（未读取任何封存文件）

仅阅读生成脚本、测试和说明：`eval/build_heldout.py` 在 seed 20261110 下复用 reference、fault、
M1–M5、H1–H4/H6 和相同标签规则，对中性改名变体随机分箱采样，换用另一组体积/时长，
优先保留与开发集不重合的动作；reference≤55、mutation≤50、hard_negative≤40，无 natural。

旧封存集依赖旧平台的实体/工具、枪头库存、计划步号、动作语义、SCENE_KEYS、Ledger 快照和旧 runs/variants。
它不会因本次重建变体而自动有效。名称相同不代表新旧快照可比较。
H2 仍按容器名识别，改名后缺失；本次未为迁移修改标签。

迁移后的候选集需重新生成并单独封存。以下只列命令，本次未执行 build_heldout，也未给封存集运行审查器：

```powershell
$env:SAFELAB_BENCH_ROOT='D:/科学具身仿真/Benchmark/bench_wt_safelab_target'
.venv/Scripts/python.exe -B eval/variants/make_renamed.py --check
.venv/Scripts/python.exe -B eval/build_heldout.py --seed 20261110 --out runs/heldout_5837ec3
```

命令写入新的候选目录，原 `eval/cases_heldout/` 保持封存。
主会话需核对平台版本、映射和新 manifest 后采用新集；P4 预注册前不评分。
`tests/test_eval_heldout.py` 的 heldout fixture 原先会读取封存内容，现默认跳过；
明确开封后才以 `SAFELAB_ALLOW_HELDOUT_READ=1` 启用。变体检查照常执行。

## 本次验证与交接

- 默认全量：535 passed、6 skipped、5 deselected，0 failed；6 项跳过均因封存集未开封。
- `-m slow`：4 passed、1 skipped、541 deselected，0 failed；跳过的是封存集重建比对。
  慢测回放了开发集变异前缀并逐一比较快照，也检查变体与原任务的可执行步数。
- `.venv/Scripts/python.exe -m ruff check src tests eval console`：All checks passed。
- `node --check console/web/app.js` 通过；另用模拟 DOM 检查移液器实例、手持工具、电源、枪头可用性和角色缓存列。
  未进行浏览器视觉验收。
- `make_renamed.py --check` 退出码 0，33 个变体的干跑结局、可执行步数及静态失败数均与原任务一致；
  废液故障任务的原有 3 条静态失败没有被消除。仓库快照的 38 个 tasks（含 faults）、3 个 briefs、33 个 mappings
  与新 runs/variants 逐字节相同。所有 sim_check 前缀均 ≤40 步。
- 测试环境使用目标 SAFELAB_BENCH_ROOT、PYTHONDONTWRITEBYTECODE=1、SAFELAB_ALLOW_HELDOUT_READ=0。
  直接运行 pytest 在 Python 3.14/Windows 沙箱遇到 mode 0700 临时目录权限失败；
  验证时仅在测试进程中让仓库内测试临时目录继承权限，再以 pytest.main 执行默认参数和 -m slow。
  该包装同时用 Python audit hook 拒绝打开 eval/cases_heldout 下的文件，测试全部通过且未触发封存读取。
- 未改动 src/safelab、平台检出、eval/reports 或 eval/cases_heldout；未提交、推送、打标签、联网或调用模型 API。
- 外层 P0_进度与待办.md 不在本次可写目录内，未写入；本节供主会话回填。
- 临时目录 runs/wp3_migration/pytest_default 因 WinError 5 无法访问或清理，icacls /reset 也被拒绝；
  其余本次创建的临时测试文件和目录已清理。

<details>
<summary>Changed files (M=modified, D=deleted, A=new)</summary>

```text
M console/runstore.py
M console/web/app.js
M eval/README.md
M eval/build_cases.py
M eval/cases/fault.jsonl
M eval/cases/hard_negative.jsonl
M eval/cases/mutation.jsonl
M eval/cases/reference.jsonl
M eval/cases/stats.md
M eval/common.py
M eval/critic_bench.py
M eval/sim_check/README.md
M eval/sim_check/export.py
M eval/sim_check/manifest.csv
D eval/sim_check/plans/mut-cell_lysis-003-1.json
D eval/sim_check/plans/mut-cell_lysis-005-1.json
D eval/sim_check/plans/mut-cell_lysis-005-2.json
D eval/sim_check/plans/mut-cell_lysis-005-3.json
D eval/sim_check/plans/mut-cell_lysis-009-1.json
D eval/sim_check/plans/mut-concentration_gradient-023-1.json
D eval/sim_check/plans/mut-multi_reagent_plate-013-1.json
D eval/sim_check/plans/mut-multi_reagent_plate-017-2.json
D eval/sim_check/plans/mut-plate_washing-004-1.json
D eval/sim_check/plans/mut-plate_washing-007-1.json
D eval/sim_check/plans/mut-plate_washing-058-1.json
D eval/sim_check/plans/mut-plate_washing-106-1.json
D eval/sim_check/plans/mut-plate_washing-167-1.json
D eval/sim_check/plans/mut-plate_washing-261-1.json
D eval/sim_check/plans/mut-sequential_staining-074-1.json
D eval/sim_check/plans/mut-viral_inactivation_chemical-005-1.json
D eval/sim_check/plans/mut-viral_inactivation_chemical-005-2.json
D eval/sim_check/plans/mut-waste_segregation-002-1.json
D eval/sim_check/plans/mut-waste_segregation-002-2.json
D eval/sim_check/plans/mut-waste_segregation-002-3.json
M eval/variants/make_renamed.py
M eval/variants/renamed/README.md
D eval/variants/renamed/mappings/viral_inactivation_chemical_renamed.json
M eval/variants/renamed/tasks/cell_lysis_renamed.json
M eval/variants/renamed/tasks/concentration_gradient_renamed.json
M eval/variants/renamed/tasks/faults/cell_lysis_stage_b_skip_fault_renamed.json
M eval/variants/renamed/tasks/faults/cell_lysis_tip_reuse_fault_renamed.json
M eval/variants/renamed/tasks/faults/liquid_knockover_renamed.json
M eval/variants/renamed/tasks/faults/plate_washing_tip_reuse_renamed.json
D eval/variants/renamed/tasks/faults/viral_inactivation_chemical_tip_reuse_fault_renamed.json
M eval/variants/renamed/tasks/faults/waste_segregation_mix_fault_renamed.json
M eval/variants/renamed/tasks/liquid_pour_renamed.json
M eval/variants/renamed/tasks/multi_reagent_plate_renamed.json
M eval/variants/renamed/tasks/plate_washing_renamed.json
M eval/variants/renamed/tasks/sequential_staining_renamed.json
M eval/variants/renamed/tasks/suspension_dispensing_renamed.json
D eval/variants/renamed/tasks/viral_inactivation_chemical_renamed.json
M eval/variants/renamed/tasks/waste_segregation_renamed.json
M tests/test_console_runstore.py
M tests/test_eval_bench.py
M tests/test_eval_cases.py
M tests/test_eval_heldout.py
A eval/cases/README.md
A eval/sim_check/plans/mut-cell_lysis-004-1.json
A eval/sim_check/plans/mut-cell_lysis-008-1.json
A eval/sim_check/plans/mut-cell_lysis-008-2.json
A eval/sim_check/plans/mut-cell_lysis-008-3.json
A eval/sim_check/plans/mut-cell_lysis-018-1.json
A eval/sim_check/plans/mut-cell_lysis-022-1.json
A eval/sim_check/plans/mut-cell_lysis-022-2.json
A eval/sim_check/plans/mut-cell_lysis-022-3.json
A eval/sim_check/plans/mut-concentration_gradient-030-1.json
A eval/sim_check/plans/mut-multi_reagent_plate-014-1.json
A eval/sim_check/plans/mut-multi_reagent_plate-020-1.json
A eval/sim_check/plans/mut-multi_reagent_plate-020-2.json
A eval/sim_check/plans/mut-multi_reagent_plate-026-1.json
A eval/sim_check/plans/mut-multi_reagent_plate-032-1.json
A eval/sim_check/plans/mut-plate_washing-005-1.json
A eval/sim_check/plans/mut-plate_washing-008-1.json
A eval/sim_check/plans/mut-waste_segregation-003-1.json
A eval/sim_check/plans/mut-waste_segregation-003-2.json
A eval/sim_check/plans/mut-waste_segregation-003-3.json
A eval/sim_check/plans/mut-waste_segregation-004-1.json
A eval/variants/renamed/mappings/clean_transfer_diagnostic_renamed.json
A eval/variants/renamed/mappings/dual_g2_dunk_renamed.json
A eval/variants/renamed/mappings/dual_g2_manual_renamed.json
A eval/variants/renamed/mappings/dual_g2_mobile_lid_check_renamed.json
A eval/variants/renamed/mappings/dual_g2_mobile_tube_dunk_renamed.json
A eval/variants/renamed/mappings/dual_g2_passive_dunk_outward_renamed.json
A eval/variants/renamed/mappings/dual_g2_passive_dunk_renamed.json
A eval/variants/renamed/mappings/dual_g2_tube_dunk_renamed.json
A eval/variants/renamed/mappings/dunk_tank_blocked_cover_renamed.json
A eval/variants/renamed/mappings/dunk_tank_blocked_plate_renamed.json
A eval/variants/renamed/mappings/dunk_tank_cover_open_renamed.json
A eval/variants/renamed/mappings/dunk_tank_early_removal_renamed.json
A eval/variants/renamed/mappings/dunk_tank_laboratory_blocked_cover_renamed.json
A eval/variants/renamed/mappings/dunk_tank_laboratory_blocked_plate_renamed.json
A eval/variants/renamed/mappings/dunk_tank_laboratory_cover_open_renamed.json
A eval/variants/renamed/mappings/dunk_tank_laboratory_early_removal_renamed.json
A eval/variants/renamed/mappings/dunk_tank_laboratory_normal_renamed.json
A eval/variants/renamed/mappings/dunk_tank_normal_renamed.json
A eval/variants/renamed/mappings/generic_receiving_deferred_renamed.json
A eval/variants/renamed/mappings/generic_receiving_renamed.json
A eval/variants/renamed/mappings/generic_receiving_wipe_renamed.json
A eval/variants/renamed/mappings/hood_pickup_diagnostic_renamed.json
A eval/variants/renamed/mappings/pathogen_inactivation_thermal_renamed.json
A eval/variants/renamed/mappings/rna_column_purification_renamed.json
A eval/variants/renamed/mappings/tank_transfer_diagnostic_renamed.json
A eval/variants/renamed/tasks/clean_transfer_diagnostic_renamed.json
A eval/variants/renamed/tasks/dual_g2_dunk_renamed.json
A eval/variants/renamed/tasks/dual_g2_manual_renamed.json
A eval/variants/renamed/tasks/dual_g2_mobile_lid_check_renamed.json
A eval/variants/renamed/tasks/dual_g2_mobile_tube_dunk_renamed.json
A eval/variants/renamed/tasks/dual_g2_passive_dunk_outward_renamed.json
A eval/variants/renamed/tasks/dual_g2_passive_dunk_renamed.json
A eval/variants/renamed/tasks/dual_g2_tube_dunk_renamed.json
A eval/variants/renamed/tasks/dunk_tank_blocked_cover_renamed.json
A eval/variants/renamed/tasks/dunk_tank_blocked_plate_renamed.json
A eval/variants/renamed/tasks/dunk_tank_cover_open_renamed.json
A eval/variants/renamed/tasks/dunk_tank_early_removal_renamed.json
A eval/variants/renamed/tasks/dunk_tank_laboratory_blocked_cover_renamed.json
A eval/variants/renamed/tasks/dunk_tank_laboratory_blocked_plate_renamed.json
A eval/variants/renamed/tasks/dunk_tank_laboratory_cover_open_renamed.json
A eval/variants/renamed/tasks/dunk_tank_laboratory_early_removal_renamed.json
A eval/variants/renamed/tasks/dunk_tank_laboratory_normal_renamed.json
A eval/variants/renamed/tasks/dunk_tank_normal_renamed.json
A eval/variants/renamed/tasks/generic_receiving_deferred_renamed.json
A eval/variants/renamed/tasks/generic_receiving_renamed.json
A eval/variants/renamed/tasks/generic_receiving_wipe_renamed.json
A eval/variants/renamed/tasks/hood_pickup_diagnostic_renamed.json
A eval/variants/renamed/tasks/pathogen_inactivation_thermal_renamed.json
A eval/variants/renamed/tasks/rna_column_purification_renamed.json
A eval/variants/renamed/tasks/tank_transfer_diagnostic_renamed.json
```

</details>
