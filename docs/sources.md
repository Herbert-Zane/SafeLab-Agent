# 安全知识原始资料清单

审查器知识卡片（P2 / S2.1）只能引用本表中的公开资料，不得引用 BSLBench 评测器的配置或后果模型（`configs/knowledge/`、任务 `criteria` 等）。

核对状态说明：
- **待核对**：没有打开原文确认措辞和页码。写卡片前必须打开原文，补上页码或章节号。
- **已核对**：已打开原文，页码或章节已填写，“相关内容”与原文一致。
- **部分核对**：版本、文号或存在性已确认，但卡片要用的条文还没读到。卡片不得引用未读到的部分。

整理日期：2026-11-09。第一轮核对日期：2026-11-09（下表“访问日期”列）。

核对说明：
- “页码”是文档印刷页码；PDF 没有印刷页码时写“PDF 第 N 页”。网页没有页码，写栏目或章节名。
- 原文摘录每条不超过一句、不超过 15 个英文词。摘录只用于核对，写卡片时仍须自己改写。
- 链接前缀不同会跳到搜索页（QIAGEN 的 `KitHandbook` 与 `kitHandbookAndProtocol` 大小写敏感），表中链接已改为核对时实际能打开的版本。

## 1. 不相容化学品（废液处置）

| # | 资料 | 链接 | 与本项目相关的内容（已按原文改写） | 出处位置 | 访问日期 | 核对状态 |
|---|---|---|---|---|---|---|
| C1 | QIAGEN, QIAamp Viral RNA Mini Accessory Set 产品说明（文档号 1063054，04/2010） | https://www.qiagen.com/en-US/resources/download/kitHandbookAndProtocol/en-qiaamp-viral-rna-mini-accessory-set | 含 Buffer AVL 的废液不得直接加入漂白剂或酸性溶液；Buffer AVL 含胍盐，与漂白剂混合可形成高反应性化合物。原文：“DO NOT add bleach or acidic solutions directly to waste containing Buffer AVL.” 洒漏处理：先用实验室清洁剂和水清洁；若可能含感染性物质，再用 1%（v/v）次氯酸钠 | p.2，Safety Information 段 | 2026-11-09 | 已核对 |
| C2 | QIAGEN, QIAamp DSP 96 Virus MDx Kit Handbook（10/2004；原标题写作 “QIAamp DSP Virus MDx Kit Handbook”，该链接实际指向此文件） | https://www.qiagen.com/en-US/resources/download/kitHandbookAndProtocol/en-qiaamp-dsp-virus-mdx-kit-handbook | 同类漂白剂警示，但针对的是 Lysis buffer (AL) 和 Wash buffer 1 (AW1) 中的盐酸胍，不是 Buffer AVL。该手册还写明液体废物应按感染性处理。原文：“DO NOT add bleach or acidic solutions directly to the sample-preparation waste.” 注意：这是 2004 年的旧版手册，引用时标注版本 | p.7，Safety Information 段 | 2026-11-09 | 已核对 |
| C3 | QIAGEN, QIAamp Viral RNA Mini Handbook（HB-0354-007，06/2023） | https://www.qiagen.com/en-US/resources/download/kitHandbookAndProtocol/hb-0354-007-hb-qa-viral-rna-mini-0720-ww | Buffer AVL 和 AW1 含胍盐，与漂白剂混合可形成高反应性化合物；封面“Kit Contents”脚注写明“含离液盐，与含漂白剂的消毒试剂不相容”；操作步骤页脚注重复此点；末页有 “CAUTION: 不要把漂白剂或酸性溶液直接加入样品制备废液” 的框 | p.6（Safety Information 与 CAUTION 框）；p.4（Kit Contents 脚注） | 2026-11-09 | 已核对 |
| C4 | Stanford EHS（现址 EHS Library），Sodium Hypochlorite (Bleach) | https://ehs-library.stanford.edu/reference/sodium-hypochlorite-bleach （原链接 ehs.stanford.edu 会 302 跳转到此） | 页面警告：部分 DNA/RNA 试剂盒的成分会与漂白剂反应，加粗写明不要对这类试剂盒使用漂白剂。胍盐（如硫氰酸胍）与漂白剂混合可释放氯胺、氯气、氰化氢等有毒气体；醇类（乙醇、甲醇、异丙醇）与漂白剂混合可生成氯仿。**修改**：原摘要写“产物包括氯仿等”，实际氯仿对应醇类，胍盐对应氯胺/氯气/氰化氢，已拆开写。页面还要求漂白剂废液与试剂盒废液分开收集、不与酸性溶液混合 | 网页，无页码；DNA/RNA 试剂盒警示栏、Disposal 栏 | 2026-11-09 | 已核对 |
| C5 | Columbia University EHS, FAQ Sheet: Bleach Incompatibilities | https://research.columbia.edu/sites/default/files/content/EHS/Lab Safety/FAQ_Sheets/FAQ-BleachIncompatibilities.pdf | 1 页 FAQ，“Incompatibility Quick Guide”列出漂白剂的不相容物：酸性化合物、胍盐（常见于商品缓冲液）、含氨化合物、有机化学品、金属、过氧化氢、还原剂、氧化剂、日光/紫外。后果包括氯气、二氧化氯、氰化氢等有毒气体，形成爆炸性化合物，形成氯代有机物。**修改**：原摘要只写“不相容物清单”；该表没有单独列出乙醇，只有笼统的“有机化学品”，乙醇与漂白剂的证据请用 C4、C6。该文件是图文 PDF，已逐页看过 | p.1/1 | 2026-11-09 | 已核对 |
| C6 | Wayne State OEHS, Choosing an Appropriate Disinfectant | https://research.wayne.edu/oehs/bio-safety/disinfectant-selection-lab | 在 “Laboratory Disinfectants Considerations” 的漂白剂条目下：原文 “Do not mix bleach and ethanol as this will form chloroform.” 并说明还会生成盐酸等其他化合物 | 网页，无页码；Laboratory Disinfectants Considerations → Bleach | 2026-11-09 | 已核对 |
| C7 | 硫氰酸胍（Guanidine Thiocyanate，CAS 593-84-0）SDS，BioSpectra, Inc.（文件名 safety-data-sheet_gthi_december-2024.pdf，共 6 页） | https://biospectra.us/media/wnvc5mbx/safety-data-sheet_gthi_december-2024.pdf | 第 2.2 节危害说明含 EUH032（与酸接触释放剧毒气体）和 EUH071；第 10.2 节“应避免的条件”写明与酸接触释放剧毒气体，不相容物为强酸、强氧化剂、氰化物；第 7 节写明不要存放在酸附近。**修改**：原链接（Merck Millipore 产品页）已失效，跳转到 MilliporeSigma 首页，且页面超时无法读取 SDS，改用 BioSpectra 的 SDS。该 SDS 的强氧化剂不相容项是 C7 与“次氯酸盐”挂钩的依据（次氯酸盐是氧化剂，见 C8、C9） | p.1（第 2.2 节）；p.4（第 10.2 节）；p.3（第 7 节） | 2026-11-09 | 已核对 |
| C8 | 次氯酸钠溶液 SDS，ERCO Worldwide（Sodium Hypochlorite 4%-30%，Rev. 8，2022-03-31，共 13 页） | https://www.ercoworldwide.com/wp-content/uploads/2022/04/SAFETY-DATA-SHEET-US-Sodium-Hypochlorite-Solution-rev-8.pdf | 第 10 节：与强酸剧烈反应，酸接触产生氯气；与胺接触生成氯胺；不相容物为强氧化剂、酸、金属、有机化合物、氨。第 7 节：存放时远离且不要混合酸、氧化剂、有机物、还原剂。第 2 节补充信息：“Contact with acids liberates toxic gas.” **修改**：原摘要写“酸、氨、醇等”，该 SDS 没有单独写“醇”，只写“有机化合物”，已改。乙醇的证据用 C4、C6 | p.7（第 10 节）；p.4-5（第 7 节）；p.2（第 2 节补充信息） | 2026-11-09 | 已核对 |
| C9 | NOAA CAMEO Chemicals：Sodium Hypochlorite 数据表；反应性分组浏览页 | https://cameochemicals.noaa.gov/chemical/4503 ；https://cameochemicals.noaa.gov/browse/react | 数据表（含别名 Sodium Hypochlorite Solution）：反应性分组为强氧化剂、碱性盐、水和水溶液；反应性概述写明受热或与酸接触产生含氯有毒烟气，与硫酸反应放热并放出氯气。浏览页列有 Oxidizing Agents, Strong 及多个酸类分组 | 网页，无页码；Reactive Groups、Reactivity Profile 栏 | 2026-11-09 | 已核对 |
| C10 | National Research Council, *Prudent Practices in the Laboratory: Handling and Management of Chemical Hazards, Updated Version*（2011），National Academies Press | https://www.nationalacademies.org/read/12654/chapter/1 （目录）；https://www.nationalacademies.org/read/12654/chapter/9 （第 8 章） | 第 8 章 Management of Waste（pp.183-210）§8.B.4.1 “Accumulation of Waste at the Location of Generation”：原文 “Take care not to mix incompatible waste.”；同节要求不相容物的容器物理分开存放。第 5 章 §5.E 讲化学品储存的相容分组（Table 5.1）。原链接 nap.edu 书名检索已改为具体章节页 | p.191（§8.B.4.1）；pp.83-104（第 5 章） | 2026-11-09 | 已核对 |

## 2. 交叉污染（枪头使用）

| # | 资料 | 链接 | 与本项目相关的内容（已按原文改写） | 出处位置 | 访问日期 | 核对状态 |
|---|---|---|---|---|---|---|
| P1 | Thermo Scientific, Good Laboratory Pipetting Guide | https://assets.thermofisher.com/TFS-Assets/LPD/manuals/Good-Lab-Pipetting-Guide-1517630-01-Brochure-EN.pdf | 原摘要“不建议清洗或重复使用枪头；即使是相似试剂也应换新枪头”未能核对 | — | 2026-11-09 | 待核对：链接 301 跳转到 documents.thermofisher.com，对自动抓取和浏览器都返回 HTTP 403；检索结果也没有返回正文。需要人工在浏览器里下载打开 |
| P2 | Ohio State CFAES, Standard Operating Procedure (SOP): Pipette Handling, Use, and Contamination Control（文件内日期 12/15/2025，共 7 页） | https://cfaessafety.osu.edu/sites/safety/files/imce/2022-07/Pipette_SOP%2012-15-2025.pdf | 每个样品或试剂用新的无菌枪头，除非协议明确允许复用（“Attaching a Pipette Tip”第 3 条）；一次性枪头不复用，除非特定应用明确要求并获批准（第 4 条）；“Prevention of Cross-Contamination”节要求每个样品、试剂或转移都用新的一次性枪头；工作流从干净到脏（先试剂后样品）。**注意**：该 SOP 没有明确写“不得把用过的枪头伸回试剂原液”，这一点见 P4、P5 | PDF 第 2 页（Attaching a Pipette Tip，第 3、4 条）；PDF 第 3 页（Prevention of Cross-Contamination → Tip Use and Handling） | 2026-11-09 | 已核对 |
| P3 | University of Waterloo Safety Office, Pipetting Guidance v1.0（2019-05，共 9 页） | https://uwaterloo.ca/safety-office/sites/default/files/uploads/files/pipetting_guidance_v.1.0_may2019.pdf | **修改**：原摘要“移液操作的安全与污染控制”过于笼统。实际内容是减少气溶胶的移液要点：浸入液体时不要按下活塞（会起泡产生气溶胶），不要用力吸液或松开活塞（会污染移液器内部或滤芯，造成交叉污染），不要用力排液，不要用力弹出枪头；带着用过的枪头时不要把移液器倒置。**该文件没有“换枪头/不得回插试剂瓶”的条文**，不能当作枪头交叉污染的依据，更适合作为气溶胶类资料（与 B 节并用） | p.4（§5.2.1 Reducing Aerosols & Good Pipetting）；p.5（§5.3 Internal or External Contamination） | 2026-11-09 | 已核对 |
| P4（新增） | E. R. Sanders, Aseptic Laboratory Techniques: Volume Transfers with Serological Pipettes and Micropipettors, J Vis Exp 2012;(63):e2754（PMC3941987） | https://pmc.ncbi.nlm.nih.gov/articles/PMC3941987/ | 明确写明不得把用过的吸管伸进无菌溶液：“Never go into a sterile solution with a used pipette”，即使该吸管一直小心保持无菌。**限制**：该句位于血清学吸管（serological pipette）的步骤里，不是微量移液器的枪头；用到枪头卡片时应说明“同理推广” | Protocol，Step 2 “Transferring Liquids Using Serological Pipettes”，加注说明 | 2026-11-09 | 已核对 |
| P5（新增） | K. Martin, The do’s and don’ts of re-using pipette tips, miniPCR bio（厂商教学博客） | https://www.minipcr.com/re-using-pipette-tips/ | 明确针对枪头：不要把用过的枪头放回试剂原液；将放回架子或冰箱再用的试剂，即使污染概率极低，也要每次换新枪头；原液被污染会影响之后很多次实验；枪头接触过一种以上试剂就丢弃。原文：“Don’t ever put a used tip back into a stock reagent.” **限制**：这是厂商博客，不是机构 SOP，答辩时应与 P4 并用，并说明权威性较低 | 网页，无页码；正文中 “When in doubt, throw it out” 之前的几条要点 | 2026-11-09 | 已核对 |

## 3. 气溶胶（未盖紧就振荡、离心）

| # | 资料 | 链接 | 与本项目相关的内容（已按原文改写） | 出处位置 | 访问日期 | 核对状态 |
|---|---|---|---|---|---|---|
| B1 | WHO, Laboratory Biosafety Manual, 4th edition（2020-12-21） | https://www.who.int/publications/i/item/9789240011311 | 出版信息已确认（页面可打开，2020-12-21 发布），但正文 PDF 无法读取 | — | 2026-11-09 | 待核对：iris.who.int 的 PDF 对自动抓取和 curl 均返回 HTTP 403。需人工下载后找气溶胶产生操作、振荡、离心相关段落。B2、B4 暂时可覆盖同类规则 |
| B2 | CDC/NIH, Biosafety in Microbiological and Biomedical Laboratories (BMBL), 6th edition | https://www.cdc.gov/labs/bmbl/ ；全文 PDF：https://www.cdc.gov/labs/media/pdfs/2025/08/SF__19a_308133-A_BMBL6_00-BOOK-WEB-final-3.pdf | 气溶胶是实验室获得性感染的重要来源；凡对微生物悬液施加能量的操作都会产生气溶胶，移液器、搅拌器、离心机、超声仪、涡旋混合器等都是潜在来源。BSL-2 特殊操作要求：在可能产生感染性气溶胶或飞溅的操作（含移液、离心、研磨、匀浆、振荡、混合、超声、开启容器）中，尽可能使用生物安全柜或其他物理防护装置。离心安全杯和密封转子被列为防护设备。**修改**：原摘要写“BSL-2 及以上离心用密封安全杯”，BMBL 6 对 BSL-2 的原文是“BSC 或其他物理防护装置”，安全杯/密封转子是举例，不是 BSL-2 的硬性规定 | p.16（Aerosols and droplets）；p.17（安全设备中的离心安全杯和密封转子）；p.41（Section IV，BSL-2，B. Special Practices，第 4 条） | 2026-11-09 | 已核对 |
| B3 | Public Health Agency of Canada, Procedures to Minimize Aerosol Hazards（McMaster 转载，1 页海报） | https://biosafety.mcmaster.ca/documents/doc047_PHAC_procedures_to_minimize_aerosol_hazards.pdf | **修改**：原摘要“振荡用密封容器；振荡后静置再开盖”与原文不完全相符。原文要点：开管时先稍微拧松盖子，等几秒再取下；混合与匀浆后等几秒再开盖；用涡旋混合器而不是倒置混匀；离心应使用密封安全杯或转子，离心后等 5 分钟让气溶胶沉降再开盖；在生物安全柜中操作感染性材料。海报没有写“振荡必须用密封容器” | 1 页海报：Opening Tubes、Mixing and Homogenizing、Centrifugation 三栏 | 2026-11-09 | 已核对 |
| B4 | University of Rhode Island, IBC Appendix E: Avoiding the Production of Biological Aerosols SOP（Rev. February 2025，共 3 页） | https://web.uri.edu/ehs/wp-content/uploads/sites/2063/2025-APPENDIX-E-Avoiding-Production-of-Biological-Aerosols-SOP-FINAL.pdf | **修改**：原摘要“振荡后静置时间（< 10 mL 至少 5 分钟）”在原文中找不到。实际内容：混合操作（超声、摇床、匀浆）应在生物安全柜内进行，使用带 O 形圈的重型螺旋盖和密封容器，混合后等待 20 分钟让可能产生的气溶胶沉降（理由：容器内压力积聚），然后在生物安全柜内开盖；离心须用不易碎管、O 形圈螺旋盖和密封安全杯，超速离心停稳后至少等 30 分钟再开盖；移液用管壁排液法，不要用抽吸与吹打来混匀 | p.1（Centrifuge Operations；Mixing Operations 第 1-3 条）；p.2（Pipettes） | 2026-11-09 | 已核对 |

## 4. 国内规范

| # | 资料 | 链接 | 内容 | 出处位置 | 访问日期 | 核对状态 |
|---|---|---|---|---|---|---|
| N1 | GB 19489-2008《实验室 生物安全通用要求》 | 国家标准全文公开系统 https://openstd.samr.gov.cn （按标准号检索；详情页链接是 JavaScript，无法直接给出） | 国家标准全文公开系统列表显示：强制性国家标准，状态现行，2008-12-26 发布，2009-07-01 实施。检索中未发现替代版本 | 列表页，无条款号 | 2026-11-09 | 部分核对：现行状态已确认，条文正文未读到，不能引用具体条款。需要人工打开全文找气溶胶、废物处置相关条款 |
| N2 | 教育部办公厅《关于做好 2026 年度高等学校实验室安全工作的通知》（教科信厅函〔2026〕8 号，2026-04-21），附件 2《高等学校实验室安全检查项目表（2026 年）》 | 北京大学实验室与设备管理部转载通知：https://lab.bjmu.edu.cn/docs/2026-05/118425ae5bd841a89d82d3313e97c215.pdf | **有更新版本**：原条目写的 2024 年版（教科信厅函〔2024〕11 号附件 2）已不是最新。通知要求各高校参照《高等学校实验室安全检查项目表（2026 年）》（附件 2）自查自纠，并把实验室分级分类、重要危险源台账动态更新。检索摘要显示还存在 2025 年版，未核对。设计方案（docx/pdf）里若引用 2024 年版，建议改为 2026 年版 | 通知 p.3（附件 2 的引用）、p.5（附件清单与日期）；附件 2 表格正文未读到 | 2026-11-09 | 部分核对：通知文号、日期、附件名称已核对。转载件只有通知 6 页，没有附件 2 的表格，危险化学品和废弃物条目的编号未核对；教育部官网原件也未打开 |
| N3 | 厦门大学《实验室安全管理规定》（厦大设备〔2024〕7 号，2024-07-01 印发，共 14 页，2024 年第 15 次校长办公会审议通过） | https://ceelims.xmu.edu.cn/upload/file/20251230/1767084353775669.pdf （厦门大学工程与应用科学学院实验室网站上的转载；文件由实验室与设备管理处解释） | 第七章“实验室危险化学品安全管理”：第 25 条危险化学品按化学试剂性质分类规范存放；第 28 条建立化学实验危废管理制度，委托有资质单位清运处置。第 31 条：本规定由实验室与设备管理处解释。它取代了 2020 年版（厦大设备〔2020〕2 号，已废止）。该规定没有写具体的“不相容化学品不得混合”条文，只有分类存放和危废处置的原则，答辩时只引用到这个程度 | p.12（第 25 条）；p.13（第 28、31 条）；p.14（废止条款） | 2026-11-09 | 已核对（转载件；校级原件的网址未找到，答辩前可去 lac.xmu.edu.cn 补查） |
| N4（新增） | 厦门大学《实验室生物安全管理规定》（厦大设备〔2021〕3 号，2021-12-03 印发，共 20 页） | https://lac.xmu.edu.cn/doc/xmdxsysswaxglgd.pdf | 第 31 条：病原微生物实验的废弃物先经高温高压灭菌或其他无害化处理；所有废弃物分类暂存、贴标签、按规定送中转站并登记；由有资质公司清运。**该规定中没有检索到“气溶胶/离心/振荡”的条文**，不能作为气溶胶规则的依据。注意：该文件可能已被后续版本取代，未核对 | p.10-11（第 31 条） | 2026-11-09 | 已核对（仅限废弃物条款） |

## 数据完整性（R7）

| # | 资料 | 链接 | 与本项目相关的内容（已按原文改写） | 出处位置 | 访问日期 | 核对状态 |
|---|---|---|---|---|---|---|
| D1 | FDA, Data Integrity and Compliance With Drug CGMP: Questions and Answers, Guidance for Industry（December 2018） | https://www.fda.gov/media/119267/download | 数据完整性指数据完整、一致、准确；ALCOA 包括准确性（Accurate）。R7 用此原则核对完成声明与平台确认动作、装载读数；该机器人实现不是指南原文，也不证明处理效果或法规合规。 | p.4（PDF 第 8 页），III.1.a | 2026-11-15 | 部分核对：指南名称、链接与 III.1.a 内容（数据完整、一致、准确；ALCOA）按已知资料核对；页码未对照原文 PDF |

## 5. 外部评测数据

| # | 资料 | 链接 | 用途 | 出处位置 | 访问日期 | 核对状态 |
|---|---|---|---|---|---|---|
| E1 | LabSafety Bench（Zhou et al., arXiv 2410.14182；MIT 许可） | https://huggingface.co/datasets/yujunzhou/LabSafety_Bench | 审查模型选型的外部依据（S4.5） | Hugging Face 数据集页：许可 MIT，关联 arXiv 2410.14182；含 MCQ 与 404 个场景（3,128 个开放问题） | 2026-11-09 | 已核对（仅核对数据集页；论文正文未读） |

## 使用规则

1. 卡片引用格式：`source: C1, p.<页码>` 或 `source: B1, §<章节>`。引用“已核对”条目；“部分核对”和“待核对”条目不得作为卡片依据。
2. 每张卡片的原文摘录不超过一句，不复制整段内容。
3. 原文 PDF 只存放在本机，不提交到仓库。
4. 卡片在 `cards-v1` tag 之后如有修改，在提交说明中写明原因，并说明修改前是否看过仿真评测结果。
5. 次氯酸盐与胍盐/乙醇相关的规则，各依据的对应关系：胍盐 + 漂白剂 → C1/C3（QIAGEN 手册）、C4、C5；乙醇 + 漂白剂 → C4、C6；酸 + 次氯酸盐/胍盐 → C7、C8、C9；废液不相容收集 → C10。
6. 枪头不得伸回试剂原液：P4（Sanders，血清学吸管）、P5（miniPCR 博客），再加 P2 的“每个样品/试剂用新枪头”。
