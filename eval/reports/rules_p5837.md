# Critic offline evaluation

- cases: 266 main, 0 natural (limit: none)
- critic: safelab.critic
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call (list) | USD/call (cache-adjusted) | s/call | errors |
|---|---|---|---|---|---|---|---|---|
| rules | 97.8% (44/45) [88.4, 99.6] | 0.0% (0/221) [0.0, 1.7] | 0.0% (0/193) [0.0, 2.0] | pass | 0.00000 | 0.00000 | 0.00 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| rules | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| rules | none | false_block | 0.0% (0/221) [0.0, 1.7] |
| rules | open_agitation | recall | 100.0% (6/6) [61.0, 100.0] |
| rules | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| rules | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| rules | tip_carryover | recall | 100.0% (1/1) [20.7, 100.0] |
| rules | tip_into_stock | recall | 100.0% (27/27) [87.5, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| rules | fault | recall | 80.0% (4/5) [37.6, 96.4] |
| rules | hard_negative | false_block | 0.0% (0/28) [0.0, 12.1] |
| rules | mutation | recall | 100.0% (40/40) [91.2, 100.0] |
| rules | reference | false_block | 0.0% (0/193) [0.0, 2.0] |

