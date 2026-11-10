# Critic offline evaluation

- cases: 223 main, 49 natural (limit: none)
- critic: safelab.critic
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call (list) | USD/call (cache-adjusted) | s/call | errors |
|---|---|---|---|---|---|---|---|---|
| llm:deepseek-flash | 96.4% (54/56) [87.9, 99.0] | 0.0% (0/167) [0.0, 2.2] | 0.0% (0/128) [0.0, 2.9] | pass | 0.00210 | 0.00080 | 4.67 | 0 |
| dual:deepseek-flash | 98.2% (55/56) [90.6, 99.7] | 0.0% (0/167) [0.0, 2.2] | 0.0% (0/128) [0.0, 2.9] | pass | 0.00151 | 0.00067 | 3.88 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| llm:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| llm:deepseek-flash | none | false_block | 0.0% (0/167) [0.0, 2.2] |
| llm:deepseek-flash | open_agitation | recall | 100.0% (12/12) [75.7, 100.0] |
| llm:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-flash | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| llm:deepseek-flash | tip_carryover | recall | 50.0% (1/2) [9.5, 90.5] |
| llm:deepseek-flash | tip_into_stock | recall | 100.0% (31/31) [89.0, 100.0] |
| dual:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| dual:deepseek-flash | none | false_block | 0.0% (0/167) [0.0, 2.2] |
| dual:deepseek-flash | open_agitation | recall | 100.0% (12/12) [75.7, 100.0] |
| dual:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-flash | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| dual:deepseek-flash | tip_carryover | recall | 100.0% (2/2) [34.2, 100.0] |
| dual:deepseek-flash | tip_into_stock | recall | 100.0% (31/31) [89.0, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| llm:deepseek-flash | fault | recall | 71.4% (5/7) [35.9, 91.8] |
| llm:deepseek-flash | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| llm:deepseek-flash | mutation | recall | 100.0% (49/49) [92.7, 100.0] |
| llm:deepseek-flash | reference | false_block | 0.0% (0/128) [0.0, 2.9] |
| dual:deepseek-flash | fault | recall | 85.7% (6/7) [48.7, 97.4] |
| dual:deepseek-flash | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| dual:deepseek-flash | mutation | recall | 100.0% (49/49) [92.7, 100.0] |
| dual:deepseek-flash | reference | false_block | 0.0% (0/128) [0.0, 2.9] |

## Natural errors (own file, own table)

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call (list) | USD/call (cache-adjusted) | s/call | errors |
|---|---|---|---|---|---|---|---|---|
| llm:deepseek-flash | 100.0% (22/22) [85.1, 100.0] | 0.0% (0/27) [0.0, 12.5] | n/a | - | 0.00276 | 0.00146 | 8.23 | 0 |
| dual:deepseek-flash | 100.0% (22/22) [85.1, 100.0] | 0.0% (0/27) [0.0, 12.5] | n/a | - | 0.00222 | 0.00118 | 6.72 | 0 |

### Natural errors (own file, own table): by category

| config | category | metric | result |
|---|---|---|---|
| llm:deepseek-flash | incompatible_mix | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-flash | none | false_block | 0.0% (0/27) [0.0, 12.5] |
| llm:deepseek-flash | tip_into_stock | recall | 100.0% (16/16) [80.6, 100.0] |
| dual:deepseek-flash | incompatible_mix | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-flash | none | false_block | 0.0% (0/27) [0.0, 12.5] |
| dual:deepseek-flash | tip_into_stock | recall | 100.0% (16/16) [80.6, 100.0] |

### Natural errors (own file, own table): by source

| config | source | metric | result |
|---|---|---|---|
| llm:deepseek-flash | natural/safe | false_block | 0.0% (0/27) [0.0, 12.5] |
| llm:deepseek-flash | natural/unsafe | recall | 100.0% (22/22) [85.1, 100.0] |
| dual:deepseek-flash | natural/safe | false_block | 0.0% (0/27) [0.0, 12.5] |
| dual:deepseek-flash | natural/unsafe | recall | 100.0% (22/22) [85.1, 100.0] |

