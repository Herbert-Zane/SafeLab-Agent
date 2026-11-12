# Critic offline evaluation

- cases: 266 main, 0 natural (limit: none)
- critic: safelab.critic
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call (list) | USD/call (cache-adjusted) | s/call | errors |
|---|---|---|---|---|---|---|---|---|
| llm:deepseek-flash | 95.6% (43/45) [85.2, 98.8] | 0.0% (0/221) [0.0, 1.7] | 0.0% (0/193) [0.0, 2.0] | pass | 0.00090 | 0.00090 | 3.29 | 0 |
| llm:deepseek-v4-pro | 97.8% (44/45) [88.4, 99.6] | 0.0% (0/221) [0.0, 1.7] | 0.0% (0/193) [0.0, 2.0] | pass | 0.00677 | 0.00677 | 25.12 | 0 |
| dual:deepseek-flash | 97.8% (44/45) [88.4, 99.6] | 0.0% (0/221) [0.0, 1.7] | 0.0% (0/193) [0.0, 2.0] | pass | 0.00018 | 0.00018 | 3.36 | 0 |
| dual:deepseek-v4-pro | 97.8% (44/45) [88.4, 99.6] | 0.0% (0/221) [0.0, 1.7] | 0.0% (0/193) [0.0, 2.0] | pass | 0.00010 | 0.00010 | 3.90 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| llm:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| llm:deepseek-flash | none | false_block | 0.0% (0/221) [0.0, 1.7] |
| llm:deepseek-flash | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-flash | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| llm:deepseek-flash | tip_carryover | recall | 100.0% (1/1) [20.7, 100.0] |
| llm:deepseek-flash | tip_into_stock | recall | 96.3% (26/27) [81.7, 99.3] |
| llm:deepseek-v4-pro | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| llm:deepseek-v4-pro | none | false_block | 0.0% (0/221) [0.0, 1.7] |
| llm:deepseek-v4-pro | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-v4-pro | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| llm:deepseek-v4-pro | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| llm:deepseek-v4-pro | tip_carryover | recall | 100.0% (1/1) [20.7, 100.0] |
| llm:deepseek-v4-pro | tip_into_stock | recall | 100.0% (27/27) [87.5, 100.0] |
| dual:deepseek-flash | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| dual:deepseek-flash | none | false_block | 0.0% (0/221) [0.0, 1.7] |
| dual:deepseek-flash | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-flash | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-flash | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| dual:deepseek-flash | tip_carryover | recall | 100.0% (1/1) [20.7, 100.0] |
| dual:deepseek-flash | tip_into_stock | recall | 100.0% (27/27) [87.5, 100.0] |
| dual:deepseek-v4-pro | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| dual:deepseek-v4-pro | none | false_block | 0.0% (0/221) [0.0, 1.7] |
| dual:deepseek-v4-pro | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-v4-pro | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| dual:deepseek-v4-pro | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| dual:deepseek-v4-pro | tip_carryover | recall | 100.0% (1/1) [20.7, 100.0] |
| dual:deepseek-v4-pro | tip_into_stock | recall | 100.0% (27/27) [87.5, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| llm:deepseek-flash | fault | recall | 80.0% (4/5) [37.6, 96.4] |
| llm:deepseek-flash | hard_negative | false_block | 0.0% (0/28) [0.0, 12.1] |
| llm:deepseek-flash | mutation | recall | 97.5% (39/40) [87.1, 99.6] |
| llm:deepseek-flash | reference | false_block | 0.0% (0/193) [0.0, 2.0] |
| llm:deepseek-v4-pro | fault | recall | 80.0% (4/5) [37.6, 96.4] |
| llm:deepseek-v4-pro | hard_negative | false_block | 0.0% (0/28) [0.0, 12.1] |
| llm:deepseek-v4-pro | mutation | recall | 100.0% (40/40) [91.2, 100.0] |
| llm:deepseek-v4-pro | reference | false_block | 0.0% (0/193) [0.0, 2.0] |
| dual:deepseek-flash | fault | recall | 80.0% (4/5) [37.6, 96.4] |
| dual:deepseek-flash | hard_negative | false_block | 0.0% (0/28) [0.0, 12.1] |
| dual:deepseek-flash | mutation | recall | 100.0% (40/40) [91.2, 100.0] |
| dual:deepseek-flash | reference | false_block | 0.0% (0/193) [0.0, 2.0] |
| dual:deepseek-v4-pro | fault | recall | 80.0% (4/5) [37.6, 96.4] |
| dual:deepseek-v4-pro | hard_negative | false_block | 0.0% (0/28) [0.0, 12.1] |
| dual:deepseek-v4-pro | mutation | recall | 100.0% (40/40) [91.2, 100.0] |
| dual:deepseek-v4-pro | reference | false_block | 0.0% (0/193) [0.0, 2.0] |

