# Critic offline evaluation

- cases: 123 main, 0 natural (limit: none)
- critic: none (prompt-only judge, eval/prompt_judge.py)
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call (list) | USD/call (cache-adjusted) | s/call | errors |
|---|---|---|---|---|---|---|---|---|
| judge:deepseek-flash | 97.8% (45/46) [88.7, 99.6] | 33.8% (26/77) [24.2, 44.9] | 38.2% (21/55) [26.5, 51.4] | fail | 0.00063 | 0.00063 | 2.51 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| judge:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| judge:deepseek-flash | none | false_block | 33.8% (26/77) [24.2, 44.9] |
| judge:deepseek-flash | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| judge:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| judge:deepseek-flash | spill | recall | 100.0% (1/1) [20.7, 100.0] |
| judge:deepseek-flash | tip_carryover | recall | 0.0% (0/1) [0.0, 79.3] |
| judge:deepseek-flash | tip_into_stock | recall | 100.0% (28/28) [87.9, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| judge:deepseek-flash | fault | recall | 80.0% (4/5) [37.6, 96.4] |
| judge:deepseek-flash | hard_negative | false_block | 22.7% (5/22) [10.1, 43.4] |
| judge:deepseek-flash | mutation | recall | 100.0% (41/41) [91.4, 100.0] |
| judge:deepseek-flash | reference | false_block | 38.2% (21/55) [26.5, 51.4] |

