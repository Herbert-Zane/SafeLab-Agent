# 勘误（正式 110 次结果文档）

本目录的 `results.md`、`results_literal_rule.md`、`manual_review.md`、`unexecuted_402_runs.md` 写于预注册流程内，并由 `recheck_independent.py` 与运行目录里的分析副本逐字节比对，因此正文不改，勘误统一记在这里。

## 2026-11-19

- `manual_review.md` 第 49 行“裂解 60 次（四个条件开放式 + 三个条件程序式）”计数有误：按运行矩阵为开放式 4 条件 × 10 次 + 程序式 3 条件 × 5 次 = **55 次**，与 `results.md` 主表一致。只改这个计数，数据和其他结论不变。
- 同一段“评测器能否检出仍然没有确认、写未评估”的说法，已由之后的 S6 核实更新：评测器能检出“用过的枪头回到试剂瓶”这类污染（记在完整性维度），但正式运行中没有出现。见 `../evaluator_coverage_lysis/report.md`。
