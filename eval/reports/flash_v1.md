# Critic offline evaluation

- cases: 223 main, 49 natural (limit: none)
- critic: safelab.critic
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| llm:deepseek-flash | 98.2% (55/56) [90.6, 99.7] | 4.2% (7/167) [2.0, 8.4] | 5.5% (7/128) [2.7, 10.9] | fail | 0.02301 | 13.04 | 0 |
| dual:deepseek-flash | 98.2% (55/56) [90.6, 99.7] | 4.2% (7/167) [2.0, 8.4] | 5.5% (7/128) [2.7, 10.9] | fail | 0.01472 | 9.45 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| llm:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| llm:deepseek-flash | none | false_block | 4.2% (7/167) [2.0, 8.4] |
| llm:deepseek-flash | open_agitation | recall | 100.0% (12/12) [75.7, 100.0] |
| llm:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-flash | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| llm:deepseek-flash | tip_carryover | recall | 100.0% (2/2) [34.2, 100.0] |
| llm:deepseek-flash | tip_into_stock | recall | 100.0% (31/31) [89.0, 100.0] |
| dual:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| dual:deepseek-flash | none | false_block | 4.2% (7/167) [2.0, 8.4] |
| dual:deepseek-flash | open_agitation | recall | 100.0% (12/12) [75.7, 100.0] |
| dual:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-flash | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| dual:deepseek-flash | tip_carryover | recall | 100.0% (2/2) [34.2, 100.0] |
| dual:deepseek-flash | tip_into_stock | recall | 100.0% (31/31) [89.0, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| llm:deepseek-flash | fault | recall | 85.7% (6/7) [48.7, 97.4] |
| llm:deepseek-flash | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| llm:deepseek-flash | mutation | recall | 100.0% (49/49) [92.7, 100.0] |
| llm:deepseek-flash | reference | false_block | 5.5% (7/128) [2.7, 10.9] |
| dual:deepseek-flash | fault | recall | 85.7% (6/7) [48.7, 97.4] |
| dual:deepseek-flash | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| dual:deepseek-flash | mutation | recall | 100.0% (49/49) [92.7, 100.0] |
| dual:deepseek-flash | reference | false_block | 5.5% (7/128) [2.7, 10.9] |

## Natural errors (own file, own table)

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| llm:deepseek-flash | 100.0% (22/22) [85.1, 100.0] | 40.7% (11/27) [24.5, 59.3] | n/a | - | 0.02163 | 22.59 | 0 |
| dual:deepseek-flash | 100.0% (22/22) [85.1, 100.0] | 33.3% (9/27) [18.6, 52.2] | n/a | - | 0.02074 | 20.96 | 0 |

### Natural errors (own file, own table): by category

| config | category | metric | result |
|---|---|---|---|
| llm:deepseek-flash | incompatible_mix | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-flash | none | false_block | 40.7% (11/27) [24.5, 59.3] |
| llm:deepseek-flash | tip_into_stock | recall | 100.0% (16/16) [80.6, 100.0] |
| dual:deepseek-flash | incompatible_mix | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-flash | none | false_block | 33.3% (9/27) [18.6, 52.2] |
| dual:deepseek-flash | tip_into_stock | recall | 100.0% (16/16) [80.6, 100.0] |

### Natural errors (own file, own table): by source

| config | source | metric | result |
|---|---|---|---|
| llm:deepseek-flash | natural/safe | false_block | 40.7% (11/27) [24.5, 59.3] |
| llm:deepseek-flash | natural/unsafe | recall | 100.0% (22/22) [85.1, 100.0] |
| dual:deepseek-flash | natural/safe | false_block | 33.3% (9/27) [18.6, 52.2] |
| dual:deepseek-flash | natural/unsafe | recall | 100.0% (22/22) [85.1, 100.0] |

