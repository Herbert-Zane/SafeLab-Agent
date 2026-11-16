# Critic offline evaluation

- cases: 266 main, 0 natural (limit: none)
- critic: none (prompt-only judge, eval/prompt_judge.py)
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call (list) | USD/call (cache-adjusted) | s/call | errors |
|---|---|---|---|---|---|---|---|---|
| judge:deepseek-flash | 100.0% (45/45) [92.1, 100.0] | 21.3% (47/221) [16.4, 27.1] | 23.3% (45/193) [17.9, 29.8] | fail | 0.00059 | 0.00059 | 2.26 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| judge:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| judge:deepseek-flash | none | false_block | 21.3% (47/221) [16.4, 27.1] |
| judge:deepseek-flash | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| judge:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| judge:deepseek-flash | spill | recall | 100.0% (1/1) [20.7, 100.0] |
| judge:deepseek-flash | tip_carryover | recall | 100.0% (1/1) [20.7, 100.0] |
| judge:deepseek-flash | tip_into_stock | recall | 100.0% (27/27) [87.5, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| judge:deepseek-flash | fault | recall | 100.0% (5/5) [56.6, 100.0] |
| judge:deepseek-flash | hard_negative | false_block | 7.1% (2/28) [2.0, 22.6] |
| judge:deepseek-flash | mutation | recall | 100.0% (40/40) [91.2, 100.0] |
| judge:deepseek-flash | reference | false_block | 23.3% (45/193) [17.9, 29.8] |

