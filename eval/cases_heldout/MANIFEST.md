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

142 cases (57 unsafe, 85 safe).
58 of them (41%) coincide with a development case in (task, step,
operator, action) after the names are mapped back; the rest differ in sampled position or in
volume. So the set measures robustness to renaming and to a different sample of positions, with
the same label rules and operator families. It cannot measure new kinds of error.

By source and task:

| task | reference | fault | mutation | hard_negative | total |
|---|---:|---:|---:|---:|---:|
| cell_lysis_renamed | 7 | 2 | 8 | 9 | 26 |
| concentration_gradient_renamed | 7 | 0 | 5 | 0 | 12 |
| liquid_pour_renamed | 1 | 1 | 0 | 0 | 2 |
| multi_reagent_plate_renamed | 8 | 0 | 9 | 0 | 17 |
| plate_washing_renamed | 8 | 1 | 11 | 4 | 24 |
| sequential_staining_renamed | 8 | 0 | 5 | 4 | 17 |
| suspension_dispensing_renamed | 6 | 0 | 0 | 0 | 6 |
| viral_inactivation_chemical_renamed | 7 | 2 | 8 | 9 | 26 |
| waste_segregation_renamed | 3 | 1 | 4 | 4 | 12 |

By source, label, category and operator:

| source | label | category | operator | n |
|---|---|---|---|---:|
| fault | unsafe | incompatible_mix | - | 1 |
| fault | unsafe | spill | - | 1 |
| fault | unsafe | tip_carryover | - | 2 |
| fault | unsafe | tip_into_stock | - | 3 |
| hard_negative | safe | none | H1 | 4 |
| hard_negative | safe | none | H3 | 12 |
| hard_negative | safe | none | H4 | 6 |
| hard_negative | safe | none | H6 | 8 |
| mutation | unsafe | incompatible_mix | M1 | 3 |
| mutation | unsafe | open_agitation | M2 | 11 |
| mutation | unsafe | overfill | M5 | 6 |
| mutation | unsafe | tip_into_stock | M3 | 22 |
| mutation | unsafe | tip_into_stock | M4 | 8 |
| reference | safe | none | - | 55 |

Known gaps: H2 is absent (it recognises reagent stocks by container name, which no longer
carries one); `incompatible_mix` is limited to `waste_segregation` as in the development set.

## SHA-256

| file | cases | sha256 |
|---|---:|---|
| `reference.jsonl` | 55 | `93e55f28a6c7c07bbae7ff187ce5f858e99b773e144dd948835109da86c21b14` |
| `fault.jsonl` | 7 | `92604253076531a22281e1d8e2c67e47fb857a9504b7ca85cebf9bf95f7130e0` |
| `mutation.jsonl` | 50 | `28e450cec1eeda9c358799990af04e726a2f43c96ff40eaa7fd99ea5ff61d5a2` |
| `hard_negative.jsonl` | 30 | `c0299b932fa82aefdf9e0c31d9a1167e506bb2902c1edda95250dc77920f29f8` |

Task variants the cases were built from (regenerable with the commands above):

| file under `runs/variants/tasks/` | sha256 |
|---|---|
| `cell_lysis_renamed.json` | `2ac636ef1416008132e5555a8b95d3456c86ca4c3dc7d06005b4f9df10f4a241` |
| `concentration_gradient_renamed.json` | `5f7b323b0cf16558787f09b702dc7fc90689324f338e24064b6571df576c38b7` |
| `cell_lysis_stage_b_skip_fault_renamed.json` | `54d06cb0cb80291e1f672fa2c0aa3d28ede81d12c92616f52babf5cbc4db6468` |
| `cell_lysis_tip_reuse_fault_renamed.json` | `72c44650a46459e319c132543335d30838b81c07ef9296cc437df7109cd62cd6` |
| `liquid_knockover_renamed.json` | `f4b66a831825de279e8bf25d2da51b10655c3d9c728ac48438716d8fee5d531a` |
| `plate_washing_tip_reuse_renamed.json` | `17101345271fbfc5aa8325bb0ad449eb2ce986ec20bc4cb34d393554175449d6` |
| `viral_inactivation_chemical_tip_reuse_fault_renamed.json` | `40c732bfc7e705735f26f110459fefcbe2abfa93a0a719bf7642a42e905c0766` |
| `waste_segregation_mix_fault_renamed.json` | `e8d100e5b6fa8b4e7acaf7852fdfbe1177085d94322995b34af5583d688e710b` |
| `liquid_pour_renamed.json` | `ac3ffe2b38cc23f0a1eceacafe9eba06e87dba20e9ec82c8a6df0feee2568c87` |
| `multi_reagent_plate_renamed.json` | `cb1877539de5e8a3772f72f9c480b317c054c47fb4f1cc67eeffb129593aa8af` |
| `plate_washing_renamed.json` | `a0bb3328bee392afffc4d22aae5d5740445d4175c0aca31dadcb641910a3863e` |
| `sequential_staining_renamed.json` | `037b941cf5ca696dc71d060efe9f39fc550b040ab41b1fc29fdbeacfe7026f62` |
| `suspension_dispensing_renamed.json` | `1d85a6c1674c0cb04716d7a40fb689d17d1120063a7e3895971cafa6cd933f23` |
| `viral_inactivation_chemical_renamed.json` | `5538e2d3dae7fb020c0727d9288286e42ddd676eb1b47022a96b15931c61f202` |
| `waste_segregation_renamed.json` | `0dc0350d5671f82434d69a657e5c0bd3cbd76bc765973aaed7974b0041403ea3` |
