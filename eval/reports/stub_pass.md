# Critic offline evaluation

- cases: 223 main, 49 natural (limit: none)
- critic: STUB pass (pipeline test, not a critic)
- intervals: Wilson 95%

## Main set

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| stub-pass | 0.0% (0/56) [0.0, 6.4] | 0.0% (0/167) [0.0, 2.2] | 0.0% (0/128) [0.0, 2.9] | fail | 0.00000 | 0.00 | 0 |

### Main set: by category

| config | category | metric | result |
|---|---|---|---|
| stub-pass | incompatible_mix | recall | 0.0% (0/4) [0.0, 49.0] |
| stub-pass | none | false_block | 0.0% (0/167) [0.0, 2.2] |
| stub-pass | open_agitation | recall | 0.0% (0/12) [0.0, 24.3] |
| stub-pass | overfill | recall | 0.0% (0/6) [0.0, 39.0] |
| stub-pass | spill | recall | 0.0% (0/1) [0.0, 79.3] |
| stub-pass | tip_carryover | recall | 0.0% (0/2) [0.0, 65.8] |
| stub-pass | tip_into_stock | recall | 0.0% (0/31) [0.0, 11.0] |

### Main set: by source

| config | source | metric | result |
|---|---|---|---|
| stub-pass | fault | recall | 0.0% (0/7) [0.0, 35.4] |
| stub-pass | hard_negative | false_block | 0.0% (0/39) [0.0, 9.0] |
| stub-pass | mutation | recall | 0.0% (0/49) [0.0, 7.3] |
| stub-pass | reference | false_block | 0.0% (0/128) [0.0, 2.9] |

## Natural errors (own file, own table)

| config | recall (unsafe caught) | false block (safe blocked) | reference false block | G2 | USD/call | s/call | errors |
|---|---|---|---|---|---|---|---|
| stub-pass | 0.0% (0/22) [0.0, 14.9] | 0.0% (0/27) [0.0, 12.5] | n/a | - | 0.00000 | 0.00 | 0 |

### Natural errors (own file, own table): by category

| config | category | metric | result |
|---|---|---|---|
| stub-pass | incompatible_mix | recall | 0.0% (0/6) [0.0, 39.0] |
| stub-pass | none | false_block | 0.0% (0/27) [0.0, 12.5] |
| stub-pass | tip_into_stock | recall | 0.0% (0/16) [0.0, 19.4] |

### Natural errors (own file, own table): by source

| config | source | metric | result |
|---|---|---|---|
| stub-pass | natural/safe | false_block | 0.0% (0/27) [0.0, 12.5] |
| stub-pass | natural/unsafe | recall | 0.0% (0/22) [0.0, 14.9] |

