# S4 新危险类别离线集

规格：experiments/prereg_explore_v2.md，含修订 1，提交 6466f5a；平台 36914f5。

构造命令（PowerShell，仓库根目录）：

```powershell
$env:SAFELAB_BENCH_ROOT='D:\科学具身仿真\Benchmark\bench_wt_safelab_target'
.venv\Scripts\python.exe eval/build_novel.py
```

冻结说明：**标签在运行任何审查器之前定稿；之后不改**。本构造任务没有提交或推送；提交冻结由接收方完成。
同一项目方构造，构造方未读取审查器或知识卡片；不是第三方基准。仅 dry-run 账本，不是仿真后果或闭环安全结果。
源场景只经 common.load_scene 加载；原有液体 id 中性化、原有组分改为 water；新增容器和四个处置目标均记录在 scene_setup。
cell_lysis 的 autoclave 在内存中从 waste_segregation 复制同类设备，两个场景均已实际重放。未手改快照。
依修订 1，N7 仅含甲醛族、phenol_chloroform 和腐蚀品；已装载易燃有机溶剂的高压灭菌动作返回无规则适用，三个 source 均不构造此情形。
N1–N5 每类前三条为左侧组分入右侧，后两条反向；N4/N10 词表本身只有一种指定配对/感染性组分。
N6 难负例仅反转两端组分的方向，两端体积、移液体积、动作和前缀不变；加完后酸占比 <= 20%。
普通安全 25 条直接截取上述危险/难负例推演前缀：attach_tip 7、全新枪头吸单组分原液 10、同组分 dispense 5、敞口水相 instrument_load 3。

## source × category（难负例按 twin_category）

| 类别 | mutation | hard_negative | reference |
|---|---:|---:|---:|
| azide_acid | 5 | 3 | 0 |
| azide_metal | 5 | 3 | 0 |
| nitric_organic | 5 | 3 | 0 |
| peroxide_ketone | 5 | 3 | 0 |
| formaldehyde_hcl | 5 | 3 | 0 |
| acid_dilution_order | 5 | 3 | 0 |
| autoclave_chemical | 5 | 3 | 0 |
| autoclave_sealed | 5 | 3 | 0 |
| drain_disposal | 5 | 3 | 0 |
| contaminated_tip_trash | 5 | 3 | 0 |
| none | 0 | 0 | 25 |
| 合计 | 50 | 30 | 25 |

## 基础场景

| 场景 | mutation | hard_negative | reference | 合计 |
|---|---:|---:|---:|---:|
| cell_lysis | 30 | 20 | 15 | 65 |
| waste_segregation | 20 | 10 | 10 | 40 |

## SHA-256

| 文件 | SHA-256 |
|---|---|
| mutation.jsonl | 1f8ae6f8a25ec143b6631f48f47766ca5ba258c30b70ab226e7036af0af9ec95 |
| hard_negative.jsonl | 6b7aeec23da87a68340d7e7e6ecd7577094e134cb0081e8ee0e04f456141a1be |
| reference.jsonl | 5d8e330774a3e52bfeca551c09a5045dbe90a56c6d9d14a6d7ab5be696ab52ee |

## 一致性检查

预注册的四项及任务书追加的第五项均通过；第 3 项同时检查动作 schema 与候选动作可执行。

```text
CHECK 1 PASS: legacy rule unsafe = 0/105
CHECK 2 PASS: novel rule unsafe on development references = 0/193
CHECK 3 PASS: prefix snapshot + observation replay = 105/105 (candidate executable; schema valid)
CHECK 4 PASS: single preregistered twin detail = 30/30
CHECK 5 PASS: stored label + category + basis agreement = 105/105
```

## 与开发集、旧留出集的重合

条数按用例计（同一用例同一组分只计一次）；统计快照容器/枪头的 components_ul 及接触记录，含体积为 0 的记名组分；开发集包含 natural 历史记录。
动作键严格取 (action, target, volume_ul)，缺失字段记为 null；设备启动的 device 不替代 target。

### cases（315 条）

危险类别交集：[]（0 类）。

| 重合组分 | 新集条数 | 该旧集条数 |
|---|---:|---:|
| ethanol_95 | 2 | 140 |
| pbs | 8 | 50 |
| water | 105 | 26 |

动作键完全相同：23/105 条新用例。

| 新集基础场景 | 新集条数 | 开发集同名场景条数 |
|---|---:|---:|
| cell_lysis | 65 | 72 |
| waste_segregation | 40 | 50 |

### cases_heldout（123 条）

危险类别交集：[]（0 类）。

| 重合组分 | 新集条数 | 该旧集条数 |
|---|---:|---:|
| ethanol_95 | 2 | 40 |
| pbs | 8 | 13 |
| water | 105 | 12 |

动作键完全相同：7/105 条新用例。

