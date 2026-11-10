# Critic offline evaluation

- cases: 223 main, 49 natural (limit: none)
- critic: safelab.critic
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| rules | 98.2% (55/56) [90.6, 99.7] | 0.0% (0/167) [0.0, 2.2] | 0.0% (0/128) [0.0, 2.9] | pass | 0.00000 | 0.00 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| rules | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| rules | none | false_block | 0.0% (0/167) [0.0, 2.2] |
| rules | open_agitation | recall | 100.0% (12/12) [75.7, 100.0] |
| rules | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| rules | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| rules | tip_carryover | recall | 100.0% (2/2) [34.2, 100.0] |
| rules | tip_into_stock | recall | 100.0% (31/31) [89.0, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| rules | fault | recall | 85.7% (6/7) [48.7, 97.4] |
| rules | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| rules | mutation | recall | 100.0% (49/49) [92.7, 100.0] |
| rules | reference | false_block | 0.0% (0/128) [0.0, 2.9] |

## Natural errors (own file, own table)

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| rules | 100.0% (22/22) [85.1, 100.0] | 0.0% (0/27) [0.0, 12.5] | n/a | - | 0.00000 | 0.00 | 0 |

### Natural errors (own file, own table): by category

| config | category | metric | result |
|---|---|---|---|
| rules | incompatible_mix | recall | 100.0% (6/6) [61.0, 100.0] |
| rules | none | false_block | 0.0% (0/27) [0.0, 12.5] |
| rules | tip_into_stock | recall | 100.0% (16/16) [80.6, 100.0] |

### Natural errors (own file, own table): by source

| config | source | metric | result |
|---|---|---|---|
| rules | natural/safe | false_block | 0.0% (0/27) [0.0, 12.5] |
| rules | natural/unsafe | recall | 100.0% (22/22) [85.1, 100.0] |

