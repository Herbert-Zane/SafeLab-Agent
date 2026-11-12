# Held-out critic cases: MANIFEST

**SEALED.** Do not run the critic, `critic_bench.py` or any other scorer on these files, and do
not read them to tune rules, cards, prompts or thresholds, until the P4 pre-registration is
written and committed. They open exactly once, after that. If a case here is looked at before
then (for example to debug the builder), say so in the pre-registration and treat the set as
partly spent. Building this set, `pytest`'s format checks and the file hashes below touch no
critic.

## How it was built

```
.venv/Scripts/python.exe eval/variants/make_renamed.py
.venv/Scripts/python.exe eval/build_heldout.py --seed 20261110
```

- Variants: `runs/variants/` (git-ignored; derived from the platform's task files). Mapping seed
  7. Containers, tips, lids and devices carry neutral ids; liquid component
  names are unchanged.
- Cases: the construction functions of `eval/build_cases.py` (reference, fault, M1-M5, H1-H4, H6)
  run on the variants; labels from `eval/labels.py` (docs/sources.md). The `natural` source is
  not present.
- Seed 20261110: replaces the evenly spaced sampling of `build_cases.spread` by a seeded draw per
  bin, and thins reference to <= 55, mutation to <= 50,
  hard_negative to <= 40, spread over (task, operator) and preferring cases
  whose (task, step, operator, action) is not in the development set once names are mapped back.
- Ids are `ho-<development-style id>` (task part is `<task>_renamed`).
- Extra fields: `split` = `heldout`, `variant_of` = the original task name.

## Size and distribution

123 cases (46 unsafe, 77 safe).
70 of them (57%) coincide with a development case in (task, step,
operator, action) after the names are mapped back; the rest differ in sampled position or in
volume. So the set measures robustness to renaming and to a different sample of positions, with
the same label rules and operator families. It cannot measure new kinds of error.

By source and task:

| task | reference | fault | mutation | hard_negative | total |
|---|---:|---:|---:|---:|---:|
| cell_lysis_renamed | 3 | 2 | 8 | 9 | 22 |
| clean_transfer_diagnostic_renamed | 1 | 0 | 0 | 0 | 1 |
| concentration_gradient_renamed | 3 | 0 | 5 | 0 | 8 |
| dual_g2_dunk_renamed | 1 | 0 | 0 | 0 | 1 |
| dual_g2_manual_renamed | 1 | 0 | 0 | 0 | 1 |
| dual_g2_mobile_lid_check_renamed | 1 | 0 | 0 | 0 | 1 |
| dual_g2_mobile_tube_dunk_renamed | 1 | 0 | 0 | 0 | 1 |
| dual_g2_passive_dunk_outward_renamed | 1 | 0 | 0 | 0 | 1 |
| dual_g2_passive_dunk_renamed | 1 | 0 | 0 | 0 | 1 |
| dual_g2_tube_dunk_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_blocked_cover_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_blocked_plate_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_cover_open_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_early_removal_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_laboratory_blocked_cover_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_laboratory_blocked_plate_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_laboratory_cover_open_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_laboratory_early_removal_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_laboratory_normal_renamed | 1 | 0 | 0 | 0 | 1 |
| dunk_tank_normal_renamed | 1 | 0 | 0 | 0 | 1 |
| generic_receiving_deferred_renamed | 1 | 0 | 0 | 0 | 1 |
| generic_receiving_renamed | 1 | 0 | 0 | 0 | 1 |
| generic_receiving_wipe_renamed | 1 | 0 | 0 | 0 | 1 |
| hood_pickup_diagnostic_renamed | 1 | 0 | 0 | 0 | 1 |
| liquid_pour_renamed | 1 | 1 | 0 | 0 | 2 |
| multi_reagent_plate_renamed | 3 | 0 | 10 | 0 | 13 |
| pathogen_inactivation_thermal_renamed | 3 | 0 | 0 | 0 | 3 |
| plate_washing_renamed | 3 | 1 | 10 | 4 | 18 |
| rna_column_purification_renamed | 4 | 0 | 0 | 1 | 5 |
| sequential_staining_renamed | 4 | 0 | 4 | 4 | 12 |
| suspension_dispensing_renamed | 4 | 0 | 0 | 0 | 4 |
| tank_transfer_diagnostic_renamed | 1 | 0 | 0 | 0 | 1 |
| waste_segregation_renamed | 4 | 1 | 4 | 4 | 13 |

By source, label, category and operator:

| source | label | category | operator | n |
|---|---|---|---|---:|
| fault | unsafe | incompatible_mix | - | 1 |
| fault | unsafe | spill | - | 1 |
| fault | unsafe | tip_carryover | - | 1 |
| fault | unsafe | tip_into_stock | - | 2 |
| hard_negative | safe | none | H1 | 4 |
| hard_negative | safe | none | H3 | 6 |
| hard_negative | safe | none | H4 | 3 |
| hard_negative | safe | none | H6 | 9 |
| mutation | unsafe | incompatible_mix | M1 | 3 |
| mutation | unsafe | open_agitation | M2 | 6 |
| mutation | unsafe | overfill | M5 | 6 |
| mutation | unsafe | tip_into_stock | M3 | 18 |
| mutation | unsafe | tip_into_stock | M4 | 8 |
| reference | safe | none | - | 55 |

Known gaps: H2 is absent (it recognises reagent stocks by container name, which no longer
carries one); `incompatible_mix` is limited to `waste_segregation` as in the development set.

## SHA-256

| file | cases | sha256 |
|---|---:|---|
| `reference.jsonl` | 55 | `77708f1415a0116ed035d5e53fb9e3ec00689d4e8ae8dc3f0c83fa74a4da551e` |
| `fault.jsonl` | 5 | `342e4155df2f5bf85c985e0541155f8f4f028138ec54178285a11614ef0a8750` |
| `mutation.jsonl` | 41 | `ce93df6f955e173082fe6e7867a12aee05c5896ad335cfcb63440d88682e37eb` |
| `hard_negative.jsonl` | 22 | `44a485837b215e008486909313dee639d47892b3ecaab82229ff76c10afd702e` |

Task variants the cases were built from (regenerable with the commands above):

| file under `runs/variants/tasks/` | sha256 |
|---|---|
| `cell_lysis_renamed.json` | `2d27b4755bcf10b1f31c96ef074f268d81a1c6dd44584cd6ba1c8f36a03918ed` |
| `clean_transfer_diagnostic_renamed.json` | `1c78f6e2ce51249c01bff20aa999727fd43fa2f82715ed69d2084e6d459e0b9a` |
| `concentration_gradient_renamed.json` | `9f732ab25a4c3512b434d81d005e878678c6a675eaead22008c1acd55195667a` |
| `dual_g2_dunk_renamed.json` | `502888303609e1ee10639efe725f53eb71d9e5c0414b6d582293f101b5995765` |
| `dual_g2_manual_renamed.json` | `0f76e8e94cc4fadfc63ec3aa90a6f3aa99f0ab1cc05244e1c0a3cb938a409c9d` |
| `dual_g2_mobile_lid_check_renamed.json` | `a6d8931a17fb8b1265b6e93524a64ea072e170dce6f11b51ac5f5e57ea4ff029` |
| `dual_g2_mobile_tube_dunk_renamed.json` | `c200e06432d5bd19200f67bc3bc5af71d4db2cd3936715a0dfa69789128e61b8` |
| `dual_g2_passive_dunk_outward_renamed.json` | `10d17f5a1403a5e1787064237e2980157a135eb59618c91b54b9694fac8f4eaf` |
| `dual_g2_passive_dunk_renamed.json` | `ed9802a2be28752e5bb308515ca1f523aa4342cf1890d78b7bf996050b2ddca7` |
| `dual_g2_tube_dunk_renamed.json` | `6d7b9ff60a1b38c24409252bed7ab6b0be099c1c97e29cf86f7f85391505ecbc` |
| `dunk_tank_blocked_cover_renamed.json` | `44ae61e589fdb32b75b76394ce6249e06b22f3b8f00f5b4dec439fc10bc594f9` |
| `dunk_tank_blocked_plate_renamed.json` | `ef2df0b9741abb847692e70f325f0cc9b88db5c9468e84612dba6e0a28dcf9b3` |
| `dunk_tank_cover_open_renamed.json` | `cecb2c426123178931b3b0970e786bcfcccf61cdfd4bcc54da9548b00efe75ed` |
| `dunk_tank_early_removal_renamed.json` | `4bf31c0b30a6cf05a18eac96b7de0b771dd5f5817d5af4b896147c58999737f1` |
| `dunk_tank_laboratory_blocked_cover_renamed.json` | `74c6b705b852de27ab2543dc2aa06276d02aa64d18684790f331c8719f3f6eeb` |
| `dunk_tank_laboratory_blocked_plate_renamed.json` | `ea0624dc50fe2db791ad07ad13b74c88aa80d20e94fd96aa16124d769ecc66ed` |
| `dunk_tank_laboratory_cover_open_renamed.json` | `f740f9e5268cf3af8c4652126cc935998dcd74a478ff4846211b45bf5973373c` |
| `dunk_tank_laboratory_early_removal_renamed.json` | `1ef1435893b0569e940f1df879905a0ef8df89ec6838e4c676656aa99cbd8303` |
| `dunk_tank_laboratory_normal_renamed.json` | `6966b520993a4625289d005578d77d5a1cba462eca4dfb3cf350a677a78d5756` |
| `dunk_tank_normal_renamed.json` | `5c6549a44c97c7feca8bdfe930395c11de6e3cd625a3824b32c71555c6d19d3b` |
| `cell_lysis_stage_b_skip_fault_renamed.json` | `2ff548dc1e2a875ad6789ee16db53b69b4171abdc56872279b731e7b6392fe0a` |
| `cell_lysis_tip_reuse_fault_renamed.json` | `6e1b53dc4fad3d0bdef58080cd28454f3869d3146e6b9ef443bf4faf34cd1013` |
| `liquid_knockover_renamed.json` | `fa09ab6e7e3d39510adb13133809802ba418b68a986a80a500841e8edc72a62c` |
| `plate_washing_tip_reuse_renamed.json` | `17a37bf47e608e973d9b1dc3ccdd647c885db7161d0e0adef62bb19617d9dba8` |
| `waste_segregation_mix_fault_renamed.json` | `8b156201fd7497e32576844271412dacdab397ca13d7947e145f123ea08f1821` |
| `generic_receiving_deferred_renamed.json` | `fd7a9012bcfd0104da699f4e13b1c4e6965faa235e5ba12a1bf815654cb8148d` |
| `generic_receiving_renamed.json` | `ba0fe6b2c7d111ae7e63e977f778978a6db8a4631072352de05427e4c7819a81` |
| `generic_receiving_wipe_renamed.json` | `0e4ca0fdd7cbaa604260d0891415654991e3a1caa3ba7242a20a30bc07ce7ffa` |
| `hood_pickup_diagnostic_renamed.json` | `e6dbb4829a45562245081b9f968290182d8e1c8da28274dd63be35931af624eb` |
| `liquid_pour_renamed.json` | `f02842cc7c1236f3689c1e9543379620923b839da33d5281749951b6b54f44c8` |
| `multi_reagent_plate_renamed.json` | `608f0c126dcccac22f81f62322e574f38edfa029e2b723a460e28e8b25c88f0a` |
| `pathogen_inactivation_thermal_renamed.json` | `ea32a7d6595cb4109852ef448800d5b5194397e11376bf714a32bf7f3a34167b` |
| `plate_washing_renamed.json` | `440aa172df48af769c449ebf613c46a81446c823b61a2f4228b1ab7d1d6f8df9` |
| `rna_column_purification_renamed.json` | `56112b65ec71fbe20e56ef12346eefbe4be49e229d360e01485f7df6f9449f43` |
| `sequential_staining_renamed.json` | `bcd8b0901a30f2ff0f490b46e002981dcdaed0a9e6a6166feef5d52893b2db0a` |
| `suspension_dispensing_renamed.json` | `3c24cdc55199321f78a781359025e1a086cecf03d1f24f9e771c34e3b9c972c1` |
| `tank_transfer_diagnostic_renamed.json` | `89eeec0f6fcd93d0a81c36642591e7afa170ab4afd28d15086d56fcddfc286dc` |
| `waste_segregation_renamed.json` | `ecabdbf7a5c32c46b57c6606493af5bf3d8cdf4d6a9dccc1f57f74d2bf7bb7b6` |
