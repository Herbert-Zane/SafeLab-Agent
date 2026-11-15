# 来源（原样摘录预注册第 4 节）

全部是公开的 SDS、法规附录或高校 EHS 的 SOP，2026-11-15 逐条打开原文核对。新来源登记在 `eval/cases_novel/SOURCES.md`，不写进 `docs/sources.md`。

| id | 来源 | 核对到的原文要点 |
|---|---|---|
| AZ1 | Penn EHRS, Fact Sheet: Sodium Azide（Rev. 4/2024）https://ehrs.upenn.edu/health-safety/lab-safety/chemical-hygiene-plan/fact-sheets/fact-sheet-sodium-azide | 与铅、铜、锌、镉、镍接触有爆炸性；与酸混合或接触这些金属放出有毒气体（叠氮酸） |
| AZ2 | Univ. of Illinois DRS, Sodium Azide NaN3（更新 2026-05-22）https://drs.illinois.edu/SafetyLibrary/SodiumAzide | 任何情况下都不要把叠氮化钠溶液倒进下水道；遇酸生成叠氮酸；与铅、铜等金属表面生成对撞击敏感的重金属叠氮化物 |
| NA1 | Columbia EHS, The Santayana Report: The Peril of Nitric Acid（2015-04）https://research.columbia.edu/sites/default/files/content/EHS/Santayana%20Reports/April2015-ThePerilofNitrcAcidRe-Release.pdf | 硝酸事故的共同点是硝酸与有机溶剂混合；剧烈反应，产热、增压、放出有毒气体；举例乙醇与浓硝酸 |
| NA2 | Duke OESO, Lessons Learned: Chemical Incompatibility https://www.safety.duke.edu/sites/default/files/Chemical-Incompatibility-Information-Sheet.pdf | 硝酸是氧化剂，与有机溶剂剧烈反应；Boise State 硝酸废液与异丙醇同瓶后爆炸的事故 |
| HP1 | USC EHS, Organic Peroxide Formers https://ehs.usc.edu/?p=10093 | 过氧化氢与有机溶剂尤其酮类反应可生成有机过氧化物（如过氧化丙酮晶体）；约 30% 及以上浓度可与有机物形成可爆轰的混合物 |
| FA1 | OSHA 29 CFR 1910.1048 Appendix A（Substance Technical Guidelines for Formalin）https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1048AppA | 不相容物含无机酸；甲醛与盐酸反应生成强致癌物双氯甲醚 |
| SA1 | Stanford EHS LCSS: Sulfuric Acid（取自 Prudent Practices）https://web.stanford.edu/dept/EHS/cgi-bin/lcst/lcss/lcss82.html | 绝不要往硫酸里加水，会飞溅；总是把酸加到水里 |
| AC1 | Univ. of Florida EHS, Autoclaves https://www.ehs.ufl.edu/departments/research-safety-services/biosafety/autoclaves/ | 不得高压灭菌：含漂白剂、福尔马林、戊二醛的液体，易燃或挥发性液体，含腐蚀品（酸、碱、酚）的物品；装载时拧松所有瓶盖，密封容器可能爆炸 |
| AC2 | Arizona State Univ. EHS, Autoclave Safety Manual https://www.asu.edu/ehs/documents/asu-autoclave-safety-manual.pdf | 不要高压灭菌密封容器里的液体；绝不要高压灭菌易燃、反应性、腐蚀性、有毒物质 |
| PC1 | Penn EHRS, Fact Sheet: Phenol-Chloroform Extraction（Rev. 6/2026）https://ehrs.upenn.edu/health-safety/lab-safety/chemical-hygiene-plan/fact-sheets/fact-sheet-phenol-chloroform-extraction | 酚-氯仿混合物弃入贴好标签的废液容器，按危险化学废物处理 |
| TT1 | Univ. of Kansas EHS Guide: Laboratory Trash Removal（2015-10-12）https://ehs.ku.edu/sites/ehs/files/files/HMEP/EHSLabTrashRemovalGuide10122015_accessible.pdf | 受生物污染或有感染性的枪头必须先由实验室处理（高压灭菌或化学灭菌）才能进楼宇垃圾 |
| TT2 | UNMC Safety Guideline: Biohazard Waste Disposal https://www.unmc.edu/ehs/_documents/biosafety/biohazard-waste/biohazardwastedisposal.pdf | 移液管和枪头会刺穿生物危害袋，必须放进硬质容器再进生物危害废物 |

来源的局限：各校对枪头去向的具体做法不同（先灭菌再进垃圾，或直接进生物危害容器），共同点是受生物污染的枪头不能未经处理直接进普通垃圾，N10 的标签只依据这个共同点。美军公共卫生中心的资料允许 0.01% 的稀叠氮溶液冲入下水道，所以 N9 只用 ≥1% 的溶液。AC1 写的是“拧松瓶盖”，平台只有 `open`/`closed` 两种盖子状态，本轮把 `closed` 当作盖紧。

