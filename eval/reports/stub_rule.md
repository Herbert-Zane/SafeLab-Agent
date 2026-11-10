# Critic offline evaluation

- cases: 223 main, 49 natural (limit: none)
- critic: STUB rule (pipeline test, not a critic)
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| stub-rule | 100.0% (56/56) [93.6, 100.0] | 0.0% (0/167) [0.0, 2.2] | 0.0% (0/128) [0.0, 2.9] | pass | 0.00000 | 0.00 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| stub-rule | incompatible_mix | recall | 100.0% (4/4) [51.0, 100.0] |
| stub-rule | none | false_block | 0.0% (0/167) [0.0, 2.2] |
| stub-rule | open_agitation | recall | 100.0% (12/12) [75.7, 100.0] |
| stub-rule | overfill | recall | 100.0% (6/6) [61.0, 100.0] |
| stub-rule | spill | recall | 100.0% (1/1) [20.7, 100.0] |
| stub-rule | tip_carryover | recall | 100.0% (2/2) [34.2, 100.0] |
| stub-rule | tip_into_stock | recall | 100.0% (31/31) [89.0, 100.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| stub-rule | fault | recall | 100.0% (7/7) [64.6, 100.0] |
| stub-rule | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| stub-rule | mutation | recall | 100.0% (49/49) [92.7, 100.0] |
| stub-rule | reference | false_block | 0.0% (0/128) [0.0, 2.9] |

## Natural errors (own file, own table)

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| stub-rule | 100.0% (22/22) [85.1, 100.0] | 0.0% (0/27) [0.0, 12.5] | n/a | - | 0.00000 | 0.00 | 0 |

### Natural errors (own file, own table): by category

| config | category | metric | result |
|---|---|---|---|
| stub-rule | incompatible_mix | recall | 100.0% (6/6) [61.0, 100.0] |
| stub-rule | none | false_block | 0.0% (0/27) [0.0, 12.5] |
| stub-rule | tip_into_stock | recall | 100.0% (16/16) [80.6, 100.0] |

### Natural errors (own file, own table): by source

| config | source | metric | result |
|---|---|---|---|
| stub-rule | natural/safe | false_block | 0.0% (0/27) [0.0, 12.5] |
| stub-rule | natural/unsafe | recall | 100.0% (22/22) [85.1, 100.0] |

