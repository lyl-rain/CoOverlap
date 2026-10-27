# CoOverlap 项目状态

更新时间：2026-10-27（源码归档；研究证据截至2026-10-23，Graph GPU仍未运行）
当前阶段：M2保持已验收；M3未全面验收；B2仍候选，不自动进入M4。

## 2026-10-27 第二周源码归档

- 按用户要求整理 `codex/week2` 分支；纳入 `scripts/` 增量、M2/M3 选定源码及共享说明。原 `reports/` 下源码逐项加入，不整体加入报告目录。
- 源码归档不包含 checkpoint、凭据、运行 JSON、原始实验报告/数据、PPT、任务书或二进制。范围与静态检查见 `WEEK2_SOURCE_HANDOFF.md`，路径与 SHA 见 `WEEK2_SOURCE_INDEX.json`。
- 本轮只进行本地 Git/源码整理与远端源码同步，不启动模型、不 SSH、不部署、不写硬件配置；M2/M3/路线/Graph 的研究状态不变。最终发布状态以远端分支与提交核验为准。

## 当前补充：Graph r1 真实适配与执行包（PREPARED / NOT APPROVED / NOT RUN）

- 原 Pi0.5 数学函数只增加 stream 路由参数，AST 数学等价核验；四条件调用原 run_segment、VersionedKV、Event、留存与统计。真实 CUDAGraph 捕获/replay API 已实现但未调用GPU；fake仅在测试夹具。
- 修正按Expert奇偶选槽、自赋version/generation校验、账本结构、缺失分母和恢复自报风险；真实句柄/设备地址/完成Event身份检查；GPU与pinned留存均487,320,064 B，捕获额外GPU内存资源上限2GiB。
- CPU 30/30，配置dry-run与部署34项payload校验通过；含四条件8周期、8段连续、实际入口凭据哨兵、正负账本和恢复反例。只模拟CUDA/原生操作边界，不能证明Pi0.5 GPU数值。
- 拟议唯一批计时32C/64E，全批53C/73E，另列6次捕获Host调用（2C/2E等价）及36 Autotune请求；未批准、未部署、未运行。
- Graph GPU可捕获性/正确性/性能均NOT_RUN。M2已验收、M3未全面验收、B2仍候选，不自动进入M4。见 [r1设计](../reports/m3_b2/20261023/graph_prototype_v1_r1/DESIGN.md)、[修正](../reports/m3_b2/20261023/graph_prototype_v1_r1/REVISION.md)、[CPU](../reports/m3_b2/20261023/graph_prototype_v1_r1/CPU_RESULTS.json)、[待批准方案](../reports/m3_b2/20261023/graph_prototype_v1_r1/GPU_PLAN.md)。

## 历史：Graph v1 接口草模（实现范围已由 r1 更正）

> 以下为原记录。v1 只执行 bytearray/FakeDevice，无真实模型/Graph API或两策略调度，13项通过不能解释为真实集成通过。

- 原型：`reports/m3_b2/20261023/graph_prototype_v1/`。四条件 A/B/C/D（Eager/Graph × serial/boundary），two_9_9、单流、双槽、180 ms；共享同一数学后端与冻结 `VersionedKV`。
- Graph 后端：每槽 B1/B2/Expert10，最多 6 个实例；地址稳定缓冲、slot+address+generation+version 校验；独立 replay 账本（捕获调用序列与 replay 分离）。
- CPU：13/13 通过（配置驱动、同一数学输出、地址/generation/版本拒绝、未发布版本不能 bind、漏 replay/重复完成被拒、捕获前于 t0、窗口内 0 D2H、0 worker、冻结模型 SHA 未变）。
- **未运行**：Graph GPU 捕获、正确性、性能均 NOT_RUN；执行包（entry/controller/部署清单）尚未构建，本批当前**不可执行**。
- 预算（设计推导，未照抄 B10）：计时 64 Expert10 / 32 刷新；保留 487,320,064 B/段，payload 3,898,560,512 B，磁盘 10.09 GiB < 12 GiB。
- B10 恢复问题已带入方案审查：恢复成功不得只靠 scope 自报；独立读回失败必须保留并阻断硬件收尾。
- B2 仍候选；M3 未全面验收；不进入 M4。

## 当前补充：动作级搜索修正（r2，CPU，2026-10-23）

- 修正 r1 历史状态合并不保持目标、判据 B 漏刷新及代表轨迹排序；禁用全部去重/剪枝，评价使用未舍入完成时间，缺发布保留 INCOMPLETE。
- CPU 19/19 PASS，包含真实同键/不同目标反例与小规模无剪枝递归枚举对照；原执行器、冻结包、B9/B10 原始结果和 r1 目录未改。
- 原每段 100k 节点 / 10 s、零重试重算：**0/12 COMPLETE，12/12 WALL_CAP，333,432 决策节点，已探索部分 0 改善**。旧版“完整空间未找到改善”撤回；当前是**截断、结论不足**，不推出不存在更优调度。
- 本轮新增模型/worker/SSH/部署/硬件写入/scope 全为 0；不扩大搜索、不生成 B11。M2 已验收，M3 未全面验收，B2 仍候选，不进入 M4。
- [修正与结果](../reports/m3_b2/20261023/legal_schedule_gap_v1_r2/GAP_SUMMARY.md)、[决策](../reports/m3_b2/20261023/legal_schedule_gap_v1_r2/DECISION.md)、[核验](../reports/m3_b2/20261023/legal_schedule_gap_v1_r2/CPU_RESULTS.json)。

## 历史：动作级合法调度搜索（r1，完整性结论已撤回）

> 下列保留原记录；r1 去重不能保持历史评价目标，12/12 COMPLETE 不能解释为动作空间穷尽。r2 已禁用剪枝重算，见顶部。

- 在 12 段固定成本上实现**逐边界 E/C/I 动作搜索**（共享状态转移核心；前缀重放 DFS；状态键含时间/作业/Context 进度/版本/读者/发布）。
- 结果：**12/12 段搜索完成（COMPLETE）**，共约 16.6 万节点、26.4 s（每段 ≤3.3 s，未触及 100k/10 s 上限），**0 条改善**（判据 A/B 均未触发）；被生命周期拒绝的分支均保留原因。
- 决策：**在明确完成的动作空间内未找到改善**（分支 3），不是截断、也不是“仅预知未来”的机会。
- 成本模型相对实测偏乐观约 0.5–1.2 ms；54.5 ms 的 MU 残差已归因为**第 7 周期次序分歧**（模型 E7→尾块 vs 实测尾块→E7），非映射错误，未调参。
- 修正：前一版仅枚举 4 个全局策略，不能计作动作级完整搜索；本 r1 才是动作级结果。旧目录保留，旧结论标注为被取代。
- 不据此实现机制、不生成 B11/GPU 方案；B2 仍候选；M3 验收与路线由用户确认；不进入 M4。见 `reports/m3_b2/20261023/legal_schedule_gap_v1_r1/{GAP_SUMMARY.md,DECISION.md,RESIDUAL_CHECK.md}`。

## 历史：M3 固定义务下合法调度空间（全局策略族版，已被 r1 动作级搜索取代）

- 12 段（B9 140 四段、B10 150 四段、160 四段对照），逐段逐操作成本，不混池；残差报告：模型相对实测偏乐观约 0.5–1.2 ms（不回调参数）。
- 搜索范围：4 个已声明全局动作策略（E-first、C-first、延迟尾块及其组合）× 12 段 = 48 组合，全部完成、全部 DRAINED，**0 个满足改善判据 A/B**。
- **动作级 E/C/I 深度搜索（100k 节点 / 10 s）未实现**（`action_level_dfs=NOT_IMPLEMENTED`），因此整体问题“是否存在值得实现的新机制”**结论不足**；仅能说“已声明策略族内无改善”。
- 结论：不建议据此实现机制或生成 B11；若继续，唯一值得补的是离线动作级有界搜索。见 `reports/m3_b2/20261023/legal_schedule_gap_v1/GAP_SUMMARY.md` 与 `DECISION.md`。
- 本轮 0 模型/SSH/部署/硬件写入/scope；B2 仍候选；M3 验收与路线由用户确认；不进入 M4。

## 当前：M3阶段审阅与待确认决策

- 已整理任务书要求、B3–B10实测、开销与消融、计划预测反例、恢复/归档边界。
- 本地重建B4–B10共7批52段的416周期/208刷新，核心统计0差异；这些是核验覆盖量，不合并成总体性能率。
- **建议（未获用户确认）：** 分项接收已实现的合法切分/边界执行、已覆盖正确性与有限机制对照；暂不宣布M3整体通过。
- 尚未成立：可靠准入与相对标准boundary基线的独立方法收益；干扰条件化选计划；全部开销独立归因。任务书预捕获子图与当前非Graph范围差异须显式确认。
- B9给出错误接受反例，B10接受获样本支持但150 ms出现过度拒绝；选择器暂建议定位离线评价/诊断，不调阈值补点。
- B10官方64/64/32通过、双预留满足、恢复首次FAIL→后续PASS与root-only归档缺口全部保留；当前恢复确认不等于自动恢复链已证明可靠。
- 四项建议均PENDING_USER_CONFIRMATION；不自动定线B2、不生成B11、不授权M4。详见[一页结论](../reports/m3_b2/20261023/m3_stage_acceptance_review_v1/ONE_PAGE.md)、[阶段审阅](../reports/m3_b2/20261023/m3_stage_acceptance_review_v1/M3_STAGE_REVIEW.md)、[决策记录](../reports/m3_b2/20261023/m3_stage_acceptance_review_v1/DECISION_RECORD.json)。
- 本轮仅本地读取、重建与文档整理，新增模型/worker/SSH/部署/硬件写入/scope均0；原始数据、执行器和冻结包不改。

## 历史：B10收口状态快照（原文保留）


更新时间：2026-10-23（B10 r1 唯一执行完成并收口）
当前阶段：M2已验收；M3未全面验收——B10 r1 已执行一次：官方 64/64/32 全 PASS、双预留全部满足；150 ms 模型拒绝在本样本上表现为过度拒绝。B2仍候选；M3验收与定线由用户确认，不进入M4。

## 历史：B10 r1 唯一执行与收口（RUN / PASS(official)）

- 唯一一次：1 普通 nvidia 模型进程（48.63 s，278/278 检查、D1 逐字节、52C/70E、13,400 行账本）+ 1 次五节点 scope（自报 PASS、51.48 s、53 样本），零重试；`result.json` SHA256 `a4e6631831ecee4f09f7f762f9f9b2d115fe53fcc32bf6869cfc4428fc486c56`；身份 `config_sha256=23ed4382…`、`prediction.sha256=ad4da44a…`、selection `e4699243…` 与冻结包一致。
- **官方**：A two/160、B three/160、C two/150、D three/150 各两遍，**Expert 64 PASS、Cycle 64 PASS、Refresh 32 PASS**，无 FAIL/UNCERTAIN/INCOMPLETE。
- **双预留**（Expert 与 VLM 分别，10 ms，按完成区间）：8 段全部 SATISFIED；最紧 C 的 Expert 10.985/11.612 ms、D 的 VLM 10.374/11.361 ms。
- **推荐/拒绝**：160 ms 模型与实测一致；150 ms 模型 `NO_ACCEPTABLE`，实测两候选官方与双预留均满足 → **样本层面过度拒绝**（`OVER_REJECTION_ON_NOMINAL_SAMPLE_PERTURBATIONS_UNTESTED`）；3.5 ms 微扰未在实机执行。
- **预测**：480 行 × 8 段 = 960 次比较（2 来源 × typical/stress，32 组，非独立运行）；完成误差均值 0.60–4.94 ms、最大 9.58 ms；次序分歧 0；条件逐字段 MATCH；`EVALUATED_EXTRAPOLATION`。
- **恢复**：scope 自报 `restored=true`；首次独立读回 FAIL（`7ef9f2ad…`）→ 后续独立读回 PASS（`6ddce993…`）；当前五 min 与本批 preflight 一致；**恢复实施者与时间未核实**，首次 FAIL 原样保留。
- **备份**：**PASS_WITH_ROOT_ONLY_UNARCHIVED**——源 193 文件 / 5,090,523,419 B，本地 192 文件 / 5,090,520,439 B，逐文件 192/192 一致（大小/SHA 0 不符、无多余）；唯一未归档 `clock_before.json`（root 600，2,980 B）仅记元数据。见 [BACKUP_VERIFICATION.md](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/BACKUP_VERIFICATION.md)。
- 不回调 10 ms/3.5 ms/成本/预测；不称 WCET、长尾、违约率或安全界；n=8 的 p99/p99.9 只是样本最大值；不推 k_min、不宣称净收益。M3 验收与定线由用户确认。
- 交付：[B10_CLOSEOUT.md](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/B10_CLOSEOUT.md)、[RUN_REPORT.md](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/RUN_REPORT.md)（+diff）、[RECOVERY_CHAIN.md](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/RECOVERY_CHAIN.md)、[closeout_eval](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/gpu_run_01/closeout_eval/EVALUATION.json)（独立复算，与原评价逐字节一致）。

## 历史：v2/B10 r1 集成修复（未执行GPU，已被本次执行取代）

- 新包：`reports/m3_b2/20261023/credible_plan_selector_v2_r1/`与`credible_selector_validation_b10_v1_r1/`；初版完整保留。
- 修复G0来源/候选/生命周期门禁及消融旁路；推荐由真实选择器计算；入口/控制器/预测共用身份合同；评价器已适配。
- CPU：选择器22/22、B10入口与评价32/32、独立部署包5/5，共59/59；均为CPU或历史数据回归，不是B10 GPU证据。
- 预测480作业行、显式映射8段为960次比较；Expert完成与deadline状态分开，MU预留独立评价；未开始保留64/64/32分母。
- 最终部署清单37项；准确SHA与核验结果见新包FREEZE_VERIFICATION.json及APPROVAL_CHECKLIST.md。
- 完整输入下模型结论不变：160选two；150因Expert/VLM预留不足拒绝；S3无额外决策贡献。预算/阈值/矩阵/52C70E未改。
- 本轮模型、worker、SSH、部署、硬件写入、scope均0；仅本地源码修复与CPU核验。正式GPU及五节点scope仍需新的明确批准。
- [修复说明](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/REVISION.md)；[CPU证据](../reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/CPU_RESULTS.json)。

## 历史：初版v2/B10准备记录（原文保留，已由r1修订）


更新时间：2026-10-23（credible_plan_selector_v2 与 B10 有限前瞻批准备：PREPARED / NOT APPROVED / NOT RUN）
当前阶段：**M2 已按约定范围验收完成；M3 未全面验收**——v2 规则已离线实现并核验，B10 仅准备、未执行；B9-r2 的唯一执行仍是当前最近的实测证据。B2 仍候选；M3 验收与路线选择由用户确认；不进入 M4。

## 历史状态（2026-10-23 credible_plan_selector_v2 + B10 准备，PREPARED / NOT APPROVED / NOT RUN）

|项目|结果与边界|
|---|---|
|本轮性质|**离线实现与准备**：v2 选择规则、成本来源与门禁、单操作微扰、S0–S3 消融、CPU 核验（14/14），以及 B10 冻结包；0 模型/worker/SSH/部署/硬件写入/scope|
|v2 规则|G0 证据与生命周期；G1 官方（MC/ME/MU/MR ≥0，缺失/不确定不算通过）；G2 预留（ME≥10、MU≥10；MR 只按官方刷新期限）；G3 冻结单操作 +3.5 ms 微扰存活（不要求微扰后仍满足预留）。选择：块数少→MC 大→稳定候选 ID；证据齐全且全被拒才 `NO_ACCEPTABLE_PLAN_UNDER_RULE`|
|成本来源|主来源 B9 逐 cell 成本（typical 中位数/stress 最大值，stage 首/后续分开）；B8 仅历史比较、不合并；160/150 无目标条件成本，用 B9 180 与 B9 140 两个外推场景，全部来源×场景通过才给模型推荐；**来源匹配 ≠ 目标域验证**|
|S0–S3 结果|**160 ms**：两候选 G0–G3 全通过，选 `two_9_9`；S1–S3 未改变推荐。**150 ms**：两候选 G1 通过但 G2 均失败（two ME stress 9.48 ms；three MU 7.20–10.34 ms）→ `NO_ACCEPTABLE_PLAN_UNDER_RULE`；S1 会选 three、S2 取消，**MU 门是决定性的**。**140 ms 回顾性**：模型即拒绝两候选；B9 仅作回顾性，不是 v2 前瞻集|
|微扰|δ=3.5 ms 单操作（stage/block/Expert）；160：two 80、three 96 场景，0 失败、0 次序翻转；150：同样 80/96，0 失败；**S3 无独立决策贡献**（本数据）；多操作同时漂移未覆盖|
|CPU|`cps2/test_cps2_cpu.py` **14/14**：manifest 时间原点、phase 同步移动、刷新/周期原点、ME/MU 独立不足、MC=min(ME,MU) 冗余、单操作微扰只影响该操作、调度产生的次序翻转、10 ms 边界、缺证据/生命周期、真实的 160/150 选择结果|
|B10 准备|矩阵 A two/160、B three/160、C two/150、D three/150，顺序 A,B,C,D,D,C,B,A，8 周期/4 刷新；CONFIG `298d5171…`、BUDGET、逐作业 PREDICTION（B9 180/140 两来源）、SELECTION_FREEZE、GPU_PLAN、APPROVAL_CHECKLIST、EVALUATION_PROTOCOL、FREEZE；计时 32C/64E、全批 52C/70E、账本 13,400、Autotune 36、bank 597,617,152 B、payload 4,339,748,864 B、磁盘 5.83 GiB、周期和 9.92 s|
|未完成/待审|B10 部署包是 B9-r2 的重命名副本，其 CPU 校验器与评价入口**尚未按 B10 协议适配和核验**；B10 逐作业预测行数与评价入口需 Codex 复核。不声称 B10 可执行|
|状态|**PREPARED / NOT APPROVED / NOT RUN**；不 SSH、不部署、不申请 scope、不启动 GPU。M2 已验收；M3 未全面验收；B2 仍候选；路线选择由用户确认|

## 历史：2026-10-23 B9 前瞻验证批 r2（已执行并收口）

|项目|结果与边界|
|---|---|
|执行状态|用户批准后**已执行唯一一次**：1 个普通 nvidia 模型进程（`PASS_IN_PROCESS_EXPERT_RESERVE_VALIDATION`，45.97 s）+ 1 次五节点 scope（`PASS`，`restored=true`，48.53 s，50 样本），attempt 1/1，零重试；独立普通用户读回 `PASS`（uid 1001）。冻结身份 CONFIG `6af4210d…`、DEPLOY `f3b4f1b0…`、PREDICTION `30172655…`、SELECTION `6503989f…`；结果 SHA256 `d314f69bb36889e7802c61c11487c0d8398da579ee62dd2d9437961882db9672`。执行中发现并记录一处文档路径缺陷：控制器要求 `run == base/run_01`，运行目录须在 `deployment/` 内（GPU_PLAN 原写包根），控制器与入口代码未改、设计未变|
|结果摘要|**A 正确性 PASS**（278/278、D1 逐字节、两 gate、13,400 行账本、52C/70E、留存 64/76 entry）。**B 官方**：Expert 63 PASS/1 UNCERTAIN、Cycle 56 PASS/7 FAIL/1 UNCERTAIN、Refresh 32 PASS；180 两候选全 PASS；140 two = 15 PASS+1 UNCERTAIN 且 8 个 Expert 预留不足；140 three = Expert 预留满足但 7 个周期 FAIL（group 0：prefix+Encoder0–8，VLM 侧）。**C**：条件 MATCH、域内评价；S10 在 140 ms 未被验证可行，本批是其前瞻反例|
|边界|本轮为唯一一次执行：不追加实验、不改 RE/预算/成本/冻结预测、不宣布 M3 完成、不进入 M4；n=4 刷新/段、2 段/条件，不构成违约率/尾部/k_min/净收益结论。逐项修正见 [CORRECTION_MATRIX.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/CORRECTION_MATRIX.md)、[RUN_REPORT.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/gpu_run_01/RUN_REPORT.md)、[B9_CLOSEOUT.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/B9_CLOSEOUT.md)|
|备份状态|**PASS_WITH_ROOT_ONLY_UNARCHIVED**：源 192 文件 / 5,090,494,162 B，本地 191 文件 / 5,090,491,182 B，逐文件 191/191 一致（大小 0 不符、SHA 0 不符、无多余）；唯一未归档 `clock_before.json`（root 600，2,980 B）仅记元数据、不声称内容 SHA。见 `gpu_run_01/BACKUP_VERIFICATION.md` 与 `LOCAL_SHA256.txt`|

## 历史：2026-10-23 B9-r2 准备、冻结与修订（该批随后已执行，准备记录保留原文）

以下为执行前的准备状态记录（当时为 PREPARED / NOT APPROVED / NOT RUN、0 模型），保留原文不删。

|项目|结果与边界|
|---|---|
|本轮性质|**两项集中修复 + 针对性 CPU 核验 + 重新冻结**；协议仍 `m3_b9_expert_reserve_validation_v1`，修订包 `…_b9_v1_r2`（v1、r1 保留）。0 模型/worker/SSH/部署/硬件写入/scope；无 GPU PASS|
|实验设计不变|RE=10 ms；A two/180、B three/180、C two/140、D three/140；顺序 A,B,C,D,D,C,B,A；8 周期/4 刷新；`b2_boundary`、quiet、0 worker、phase +15 ms、lead 10 ms；固定矩阵两预算各跑两候选；1 进程 + 1 scope；170/180+10/420 s；0 重试；计时 32C/64E、全批 52C/70E、Autotune 36|
|修复一：真实 NOT_STARTED|真实入口预创建全部 8 段记录（含 `status=NOT_STARTED/planned_*`，无 `manifest/t0`）。r1 会 `KeyError('cell')` 与 `TypeError`（None 与 int 排序）。r2：声明身份与义务取自冻结 CONFIG（`declared_rows`），未执行段保留 cell/plan/预算、8/8/4 全 INCOMPLETE、`completion/response/margin=None`、不推断通过；有作业记录却无 manifest/t0 或身份冲突仍 `INVALID_EVIDENCE`；条件检查对缺失字段记 `UNKNOWN` 并列出未执行段，不崩溃|
|修复二：stress 超出方向|保留 `completion_error = predicted − actual`，另立 `exceedance = actual − predicted`（completion 与 response 分开，各自时间原点）；仅 `>0` 计入并输出正超出量；相等不算；缺失不比较、不算“未超出且通过”。输出改为 `stress_completion_exceed`/`stress_response_exceed` 并写明定义|
|反例（调用真实评价实现）|前 5 段完成 + 后 3 段真实 NOT_STARTED：分母仍 **64/64/32**，后 3 段贡献 **24/24/12 INCOMPLETE**，条件 `INSUFFICIENT_EVIDENCE`；全 8 段 NOT_STARTED：CLI 退出 0、64/64/32 全 INCOMPLETE、`reserve.unknown=64`、`prediction_status=NOT_EVALUABLE`；身份冲突 → 该段 INVALID、CLI 退出 2；stress 实际晚 10 ms → 超出 +10.0，实际早 10 ms → 不超出（误差 +10），相等 → 不超出|
|三/四条路径|见 [CPU_PATHS.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/CPU_PATHS.md)：正常 `EVALUATED`（64/32 PASS）、5+3 未开始 `INSUFFICIENT_EVIDENCE`、全未开始 `INSUFFICIENT_EVIDENCE`、条件不匹配 `CONDITION_MISMATCH`（仍保留 64/32 数值评价，不报域内通过）|
|r1→r2 内容对比|`PREDICTION.json`、`SELECTION_FREEZE.json`、入口 `pi05_m3_b9_validation.py`、控制器 `m3_b9_control.py` **逐字节相同**；`m3_b9_plan.py` 仅 `ANALYSIS_MODULES['evaluate_b9.py']` 改为新评价器 SHA（身份链），矩阵/工作量/预算/manifest 不变|
|CPU|`tests/run_cpu.py` → **75/75 PASS**（结构 56 + 评价链 19）；计数由实际运行生成，不手填|
|冻结身份|`freeze_docs.py` 生成完整 SHA 表与 `FREEZE.json`（32 项，无 stale）：CONFIG `6af4210da8df42b004c50169823ba4ba94d42cc7bbad283839ac6d2e44a04cc3`；DEPLOY `f3b4f1b0742721a0af1b45cb5fbde177910059ef50d0f7bf73d4684f7ec591c0`；PREDICTION `301726555eeefa43337d447803365778fe7fd3f0388d03cade7539fb99a53c49`；SELECTION `6503989f40577b358749b3cc01d0b0c774dc84220354e2d780738035fb31ffdf`；评价器 `1f741badf658ec6800787c3bab8b6e4a08fd172443af48382fe690f1d517d7c2`|
|状态/证据|**PREPARED / NOT APPROVED / NOT RUN**；未获新批准不得 SSH/部署/写硬件/提交 scope。见 [REVISION.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/REVISION.md)、[GPU_PLAN.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/GPU_PLAN.md)、[APPROVAL_CHECKLIST.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/APPROVAL_CHECKLIST.md)、[FREEZE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/FREEZE.json)、[CPU_RESULTS.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/CPU_RESULTS.json)|
|下一动作|一次性审批（同一 B9 批次，revision r2）；**批准前不执行**。M2 已验收；M3 未全面验收；B2 仍候选；不进入 M4|
|部分|结果|
|---|---|
|A 正确性|**PASS**：278/278 检查；D1 `byte_exact=True`；两个 gate PASS；观察账本 13,400 行（49/49/882/12,420）；完整工作量 52C/70E（计时 32C/64E）；留存两块 64/487,320,064 B、三块 76/597,617,152 B；Autotune 36 另账|
|B 官方性能（逐 cell）|180 two：E 16 PASS / C 16 PASS / R 8 PASS（最小余量 39.315 / 39.315 / 159.689 ms）；180 three：16/16/8（87.703 / 38.099 / 158.344）；140 two：E 15 PASS+1 UNCERTAIN、C 同、R 8 PASS（−0.059 / −0.059 / 5.717）；140 three：**E 16 PASS、C 9 PASS+7 FAIL、R 8 PASS**（20.890 / **−2.173** / 2.103）。合计 E 63/1/0、C 56/7/1、R 32/0/0|
|B 失败归因|140 three 的 7 个 FAIL 全为 **VLM/unit 侧**（`expert_status=PASS, unit_status=FAIL`，−0.67…−2.17 ms）；唯一 UNCERTAIN 是 140 two 的 cycle6/E6（−0.059 ms 跨 deadline）|
|C 条件/预测/预留|条件 **MATCH**（逐字段），域内 `EVALUATED_IN_DOMAIN`；S0/S10 复用 F2/F3（无额外 GPU 段）；预留 **8 不足 / 56 满足 / 0 未知**，8 个全部是 140 two 的 E0/E2/E4/E6×两遍（实际 0.34…1.54 与 −0.059 ms），**预测本已 <10 ms，误判 0**；预测-实测完成误差 180 为 2.3–4.0 ms（max 7.9），140 two 为 2.7–9.7 ms，140 three 为 **21.2–26.8 ms（max≈81）**；**误判可行 6/16** 段×场景；stress 超出 189 作业、最大 80.4 ms；派发次序 5/8 一致，版本 8/8 一致|
|结论边界|180 ms 两种切分都干净（三块 Expert 余量更大、留存更大）；140 ms **两者都不干净**：两块保住周期但 Expert 贴 deadline（预留违反），三块保住 Expert 余量（≥20.9 ms）却在 VLM 义务上丢 7/16 周期。**Expert-only 预留不是可行性证明**；n=4 刷新/段、2 段/条件，不构成违约率/尾部/k_min/净收益结论。不据此改 RE、成本或冻结预测，不追加实验，不进入 M4|

## 历史：2026-10-23 B9 前瞻验证批修订 r1（已被 r2 取代）

|项目|结果与边界|
|---|---|
|本轮性质|**集中修订 + CPU 核验 + 重新冻结**；协议仍 `m3_b9_expert_reserve_validation_v1`，修订包 `…_b9_v1_r1`（v1 保留）。0 模型/worker/SSH/部署/硬件写入/scope；无 GPU PASS|
|实验设计不变|RE=10 ms；A two/180、B three/180、C two/140、D three/140；顺序 A,B,C,D,D,C,B,A；每段 8 周期/4 刷新；`b2_boundary`、quiet、0 worker、phase +15 ms、lead 10 ms；固定矩阵两预算各跑两候选；1 进程 + 1 scope；170/180+10/420 s；0 重试；计时 32C/64E、全批 52C/70E、账本 13,400、Autotune 36、bank 597,617,152 B、payload 4,339,748,864 B、磁盘 5.83 GiB|
|评价链修复（8 项）|① Refresh 无 status（v1 把 32 次真实 PASS 计为 0）→ 复用冻结 `replay_stats`；② `response_upper_ns=None` 崩溃 → 缺失保持 None；③ UNCERTAIN 未统计 → 区间跨 deadline 按冻结 `classify` 记 UNCERTAIN，Expert 的 completion 与 deadline 分开；④ 未开始/部分段丢分母 → 分母取声明义务（**64 Expert / 64 Cycle / 32 Refresh**）；⑤ 预测未真正参与 → 逐作业比较（齐全性、次序与首次分歧、版本、completion/response 误差、deadline 状态、误判可行/不可行、stress 超出、预留误判）＋缺字段由冻结 B8 成本与规则代码补齐；⑥ 条件只看 label → 逐字段 MATCH/MISMATCH/UNKNOWN；⑦ 不校验冻结输入 → `verify_frozen`，不一致 `INVALID_EVIDENCE` 且退出码 2；⑧ 只测 helper → 真实运行 `evaluate_b9.main` 于 `fixture: true` 的 B9 结构夹具|
|B8 夹具核验|用修复后的统计链重算真实 B8 `result.json`：**64/64 Expert、64/64 Cycle、32/32 Refresh PASS**（v1 的 Refresh 会报 0）。仅证明统计链正确，**不是 B9 运行证据**|
|预测与选择|`PREDICTION.json` schema v2、240 行逐作业（Expert/Context块/Cycle/Refresh × typical/stress），含 release/deadline/dispatch/completion/response/margin/status/版本/义务组与时间原点；32 行释放点距离；段前 `SELECTION_FREEZE.json` 仍为 **180 S0=S10=two；140 S0=two、S10=three**|
|条件兼容|逐字段检查（协议、config SHA、段 ID/预算/phase/cycles、plan+policy、binding、block_plan、configuration label+S0/S1 SHA、observation、prediction/selection 身份、lead、quiet/worker、source fingerprints、逐 plan 留存、clock limits）；任一 MISMATCH→`CONDITION_MISMATCH`，仅 UNKNOWN→`INSUFFICIENT_EVIDENCE`，均不报 MATCH；不匹配时固定矩阵照常执行、保留域外数值比较，不伪造 `SELECTED`|
|冻结身份|统一由脚本 `freeze_docs.py` 从最终文件生成 `APPROVAL_CHECKLIST.md` 的**完整 SHA 表**与 `FREEZE.json`（30 项）。关键值：CONFIG `4db22946c2baad42df5d59ea59d5bf53a1226b2646043ed59c7688123025e7f4`；DEPLOY `04d292807e8d7c4d0dba7ee1f5a99dd564a41b3d23e647aedcd645e01d5cfbde`；PREDICTION `301726555eeefa43337d447803365778fe7fd3f0388d03cade7539fb99a53c49`；SELECTION `6503989f40577b358749b3cc01d0b0c774dc84220354e2d780738035fb31ffdf`；RULE `1e46e495a6994f756ad56985e386f58835b4575b59d8d7af4c897ed2d0692d60`；COSTS `ebee939dd571fe509767aaea3069e5bd4091ac25d8cdc823cd61541079026b26`；评价器 `d3efaa64d18e3fd313d1f21a4195c72888e1117a7c1b0657fe2efe3cd754ffc1`|
|SHA 不一致的来源（已查清）|v1 的 `CONFIG`/`DEPLOY` 在最后两次措辞修正后重建为 `3549c671…`/`df07e42f…`，而 `APPROVAL_CHECKLIST`/`GPU_PLAN` 里手写的 `ba7fa9a7…`/`45729522…` 是更早一次构建的摘要——**同一批的不同版本摘要被拼进同一份审批文本**，不是文件被篡改。r1 不再手写摘要：`freeze_docs.py` 一次性生成完整 SHA 表，生成顺序固定为 预测→plan 常量→CONFIG/DEPLOY→CPU→FREEZE|
|CPU|`tests/run_cpu.py` → **71/71 PASS**（结构 56 + 评价链 15）：B8 夹具 64/64/32、缺失记录保留 INCOMPLETE 与分母、区间跨 deadline→UNCERTAIN、未开始段保留分母、预测被真实使用（改完成时刻/次序/版本/预留→输出变化）、条件不匹配不包装为 MATCH、篡改冻结文件被拒且原 SHA 不变、完整 CLI 三部分与退出码（正常 0、条件不匹配 0 且不报通过、`INVALID_EVIDENCE` 2）|
|状态/证据|**PREPARED / NOT APPROVED / NOT RUN**；未获新批准不得 SSH/部署/写硬件/提交 scope。修订说明 [REVISION.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/REVISION.md)、[GPU_PLAN.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/GPU_PLAN.md)、[APPROVAL_CHECKLIST.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/APPROVAL_CHECKLIST.md)、[FREEZE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/FREEZE.json)、[CPU_RESULTS.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/CPU_RESULTS.json)、[EVALUATION 模板](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/RESULTS_TEMPLATE.json)、[MINIMAL_DIFF.patch](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/MINIMAL_DIFF.patch)|
|下一动作|一次性审批（同一 B9 批次，revision r1）；**批准前不执行**。M2 已验收；M3 未全面验收；B2 仍候选；不进入 M4|

## 历史：2026-10-23 Expert 预留验证批 B9 准备 v1（已被 r1 修订包取代）

|项目|结果与边界|
|---|---|
|本轮性质|**方案准备 + CPU 核验 + 冻结预测**；协议 `m3_b9_expert_reserve_validation_v1`；0 模型/worker/SSH/部署/硬件写入/scope；无 GPU PASS；不改写 B8 预测失败、不改 r1 选择器适用域|
|选择器修复（v1_r1）|两个真实缺口已修并留反例：① 只给一个声明候选时 v1 返回 SELECTED → r1 返回 `INSUFFICIENT_EVIDENCE` 并列缺项；② `lifecycle_ok=False` 的候选在 v1 仍可能 feasible/被选 → r1 一律不可行、不可选。规则本身（RE=10 ms、成本来源、顺序）不变；**修复后 B8 选择经重新计算保持不变**（`SELECTION.csv`/`ABLATION.csv` 与 v1 逐字节相同）。CPU **37/37 PASS**，见 [REVISION.md](../reports/m3_b2/20261023/expert_reserve_selector_v1_r1/REVISION.md)|
|冻结规则/预测|规则 [RULES.json](../reports/m3_b2/20261023/expert_reserve_selector_v1_r1/RULES.json)（`1e46e495…`），成本 `COSTS.json`（`ebee939d…`），B9 预测 [PREDICTION.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/prediction/PREDICTION.json)（`62e6c476…`），段前选择冻结 [SELECTION_FREEZE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/prediction/SELECTION_FREEZE.json)（`f251e438…`）：**180 S0=S10=`two_9_9`；140 S0=`two_9_9`、S10=`three_prefix_9_9`**（由规则在 B8 成本上算出，非硬编码；CPU 用例可复算）|
|本批矩阵|A two/180、B three/180、C two/140、D three/140；顺序 A,B,C,D,D,C,B,A；每段 8 周期/4 刷新；全部 `b2_boundary`、quiet、0 压力 worker、phase +15 ms、lead 10 ms。**固定矩阵在两个预算都执行两个候选**；冻结推荐只写入段记录（JSON 拷贝，零模型计算），不改变执行计划|
|工作量/资源（本批代码核算）|计时 **32C/64E**；全批 **52C/70E**；观察账本 **13,400 行**；Autotune **36** 另账；bank **597,617,152 B**（GPU+pinned 各一份）；8 段 payload **4,339,748,864 B**；磁盘估算 **5.83 GiB** < 12 GiB 准入；内部 **170 s**、外层 **180 s+10 s**、scope **≤420 s**；0 重试、0 压力 worker、无 profiler。见 [BUDGET.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/deployment/BUDGET.json)|
|兼容/公平|与 B8 的 manifest 在去掉 `schema` 后**逐字节相同**（`COMPATIBILITY.json`）；同预算两 cell 共享同一 manifest，跨预算非同一墙钟轨迹；协议 ID 独立，不要求与 B8 相同|
|条件匹配策略|实际 numeric configuration 在准备完成后、计时前记录：**匹配**→可评价原声明条件下的前瞻预测；**不匹配或必要证据未知**→选择器域 `INSUFFICIENT_EVIDENCE`、预测比较 `CONDITION_MISMATCH`；固定矩阵照常跑完，不筛配置、不重启、不伪造 `SELECTED`|
|CPU|`deployment/validate_m3_b9_cpu.py` **57/57 PASS**：协议/凭据/入口/控制器、8 段顺序与唯一 ID、预算与 plan 驱动 manifest、冻结推荐 SHA 与可复算性、禁止回写成本/规则、S0/S10 不重复分母、条件不匹配不伪造 SELECTED、性能失败继续、正确性/资源/截止停止、初态/版本/义务/留存公平、失败归属、缺失记录不填零不记 PASS、部署清单覆盖|
|文档更正|180 ms 的 **+3.009/+5.798 ms 是模型场景余量差**；B8 实测两块相对三块为 **+1.334/+4.395 ms**，两块实测最小 Expert 余量 **41.921 ms**；逐块 post-retention 包络中位数**不能**冒充整次刷新观测总成本。v1 `MAINLINE_RESULT.md` 已按此改正|
|状态/证据|**PREPARED / NOT APPROVED / NOT RUN**；未获新批准不得 SSH/部署/写硬件/提交 scope。交付 [README.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/README.md)、[GPU_PLAN.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/GPU_PLAN.md)、[APPROVAL_CHECKLIST.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/APPROVAL_CHECKLIST.md)、[CONFIG.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/deployment/CONFIG.json)、[BUDGET.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/deployment/BUDGET.json)、[COMPATIBILITY.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/deployment/COMPATIBILITY.json)、[FAIRNESS_CHECK.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/deployment/FAIRNESS_CHECK.json)、[FREEZE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/FREEZE.json)、[RESULTS_TEMPLATE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/RESULTS_TEMPLATE.json)、[CPU_RESULTS.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/CPU_RESULTS.json)、[MINIMAL_DIFF.patch](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/MINIMAL_DIFF.patch)|
|下一动作|一次性具体审批见 APPROVAL_CHECKLIST；**批准前不执行**。M2 已验收；M3 未全面验收；B2 仍候选；不进入 M4|

## 历史：2026-10-23 Expert 预留约束的计划选择与回顾性消融（离线/CPU）

|项目|结果与边界|
|---|---|
|本轮性质|**离线选择研究 + 回顾性消融**；规则（RE=10 ms）在 B8 之后提出；0 模型/worker/SSH/部署/硬件写入/scope；无新增 GPU PASS；不改写 B8 预测失败（`CONDITION_MISMATCH`）与 r1 选择器适用域|
|规则|[RULES.json](../reports/m3_b2/20261023/expert_reserve_selector_v1/RULES.json)：RE=**10 ms**（工程参数，非任务书、非 WCET、非已验证安全界、不表示可承受任意 10 ms 干扰）；候选 `two_9_9`/`three_prefix_9_9` + `b2_boundary`；typical=该条件样本中位、stress=该条件样本最大；MC/ME/MR 取所有场景最小值；选择顺序：义务/官方 deadline → `ME≥RE` → 块数最少 → MC 较大 → 稳定 ID；状态 `SELECTED`/`RESERVE_UNSATISFIED`/`NO_EMPIRICALLY_FEASIBLE_PLAN`/`INSUFFICIENT_EVIDENCE`/`UNSUPPORTED_INPUT`|
|是否改变选择|**180 ms：S0=S10=`two_9_9`**（两候选 ME 42.128/89.813 ms 均 ≥10）→ 未改变；**140 ms：S0=`two_9_9`，S10=`three_prefix_9_9`**（两块 ME 2.487<10、三块 24.304≥10）→ **改变**。两个预算跑同一函数，结论由各自 B8 成本重放得出，非硬编码|
|预留增益|140 ms 实测最小 Expert 余量 **2.551 → 24.322 ms（+21.771）**；实测 Expert 余量 <10 ms 的作业 **8/16 → 0/16**；**官方时限不变**：两块/三块在 140 ms 均 16/16 周期、8/8 刷新|
|代价|140 ms 选三块相对两块：实测最小周期 **2.551→1.934 ms（−0.617）**、最小刷新 **82.821→82.131 ms（−0.690）**；块数 2→3、每刷新合法边界 3→4；每段留存 64→76 entry、487,320,064→597,617,152 B；模型 MC/MR −0.705/−0.704 ms|
|条件价值|180 ms 规则选两块相对固定三块：周期余量 **+3.009**、刷新余量 **+5.798**、少 1 条边界/刷新；Expert 余量 −47.685 但仍 42.128 ms（≥4×RE）。140 ms 规则选三块相对固定两块：Expert 余量 +21.817，周期/刷新 −0.705/−0.704|
|消融与复用|F2/F3/S0/S10 两预算各 4 行（`outputs/ABLATION.csv`）；**S0 与 F2 完全相同**（等价，复用同一记录，不重复统计分母）；S10@180 `reused_from=F2`、S10@140 `reused_from=F3`；本轮**没有**“选择器 GPU 运行”，复用关系逐行标注|
|预留一致性|140 ms 两块：每段每场景预测 4/8 不足、实际 4/8；**“预测满足而实际不足” 0/8**；三块 0/8→0/8。规则输入只有场景汇总，实测轨迹不回调规则|
|证据类别|**回顾性支持**（本批 2 预算 × 2 候选 × 2 段），**非前瞻**（RE 后于 B8 提出）；样本窄（单相位 +15 ms、quiet、每格 2 段同进程顺序）；不改写任何官方结论|
|CPU|`ers/test_ers_cpu.py` **31/31 PASS**：ME 恰为 10 ms 按 ≥ 接受、预留足但周期/刷新失败被拒、官方可行但预留不足→`RESERVE_UNSATISFIED`、两候选满足→少块、仅三块满足→实际改选、一候选不可行保留另一、缺证据/条件不匹配不按可行、RE=0 与 F2 等价不重复统计、规则不看实测轨迹、冻结输入/预测/执行器 SHA 不变|
|状态/证据|M2 已验收；**M3 未全面验收**；B2 仍候选；不进入 M4。交付 [README.md](../reports/m3_b2/20261023/expert_reserve_selector_v1/README.md)、[MAINLINE_RESULT.md](../reports/m3_b2/20261023/expert_reserve_selector_v1/MAINLINE_RESULT.md)、[RULES.json](../reports/m3_b2/20261023/expert_reserve_selector_v1/RULES.json)、[SELECTION.csv](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/SELECTION.csv)、[ABLATION.csv](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/ABLATION.csv)、[JOB_RESERVE.csv](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/JOB_RESERVE.csv)、[ACTUAL_METRICS.csv](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/ACTUAL_METRICS.csv)、[FINGERPRINTS.json](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/FINGERPRINTS.json)、[CPU_TESTS.log](../reports/m3_b2/20261023/expert_reserve_selector_v1/CPU_TESTS.log)|
|下一命题（只写命题/字段/条件）|见 MAINLINE §6：140 ms 下 `two_9_9` 偶数 Expert 中 ≥4/8 的余量 <10 ms、`three_prefix_9_9` 8/8 ≥10 ms，规则在独立重复中仍改选三块且三块官方违约计数不高于两块；**字段**：逐 Expert `deadline−completion`、逐周期/刷新违约计数与分母、每刷新块数与释放点距离、MC/ME/MR；**条件**：B8 的 configuration/相位/lead/quiet/输入/版本与义务分组/观测协议，B4 成本与 180 ms 结果不得代入。不设计矩阵、不建 GPU 入口、不调 RE|

## 历史：2026-10-23 M3 释放点敏感的计划评价（离线/CPU）

|项目|结果与边界|
|---|---|
|本轮性质|**离线方法实现 + 回顾性分析**；0 模型/worker/SSH/硬件写入/scope；不修改生产执行器、历史冻结包、原始数据与 B8 运行前预测；无新增 GPU PASS；**不把 B8 预测失败改写成通过**|
|主线问题|计划评价从“每类操作一个耗时→一条时间线”扩展为“每个合法决策边界同时给出 deadline 余量与释放点距离，并给出跨过释放点所需的前序耗时变化”|
|覆盖|B8 全部 **32 次刷新 / 176 个实际决策边界**（140 ms 16 次刷新 + 180 ms 16 次对照）；预测侧同一重建：176 边界 × typical/stress|
|两类余量|A `deadline − completion`（Expert/周期/刷新分列，`DEADLINE_MARGINS.csv`）；B `下一 Expert 原始 release − 决策 Host 时刻`（`BOUNDARY_AUDIT.csv`）。决策时刻含真实完成确认与调度成本，不以 GPU Event 结束代替|
|等价关系（本轮核验）|**在当前 manifest 与这些完成依赖下**，紧边界处 `release_distance = cycle(2q) 余量 − Host 确认开销`，**32/32** 刷新成立（`MARGIN_IDENTITY.csv`），因为 `deadline(cycle 2q) = deadline(Expert 2q) = release(Expert 2q+1)` 且 cycle 2q 恰完成在本边界之前的那个操作上。**不是任意调度状态下的通用恒等式**；释放点距离**不是**第二个独立 headroom，新增信息是分支、翻转代价与 Δ-to-flip|
|140 ms 次序翻转|two_9_9：E(2q) 完成后 B2 边界实测距离 **+2.54…+4.18 ms**（尚在释放点前），冻结预测 **−0.04…−1.17 ms**（已过），分支相反，**该计划 8/8 刷新 ×2 场景**；three_prefix_9_9：B1 完成后 **B3** 边界 **+1.91…+3.23 ms** 对 **−0.41…−2.04 ms**，同样 8/8×2。180 ms 对照 **0/16** 翻转|
|放大机制|翻转阈值（前序 Expert 耗时变化）**3.20 ms**（140/两块 R0）、**2.51 ms**（140/三块 R0）；翻转后尾块与发布晚 **71.9–72.1 ms**、Expert E(2q+1) 早 **44.7 ms**（B8 自身成本模型构造）。**刷新仍按时**：两块构造 pre/post 发布 **199.670→271.605 ms**、三块 **199.655→271.743 ms**，deadline **280 ms**；冻结预测刷新余量 +4.871/+2.942/+4.599/+1.700 ms（PASS），FAIL 的是偶数周期与（两块的）E0|
|成本来源分离|操作级 B4 源与 B8 中位差：B1 **0.14 ms**、B2 **0.01 ms**、**Expert 3.32 ms**（三块同型 3.05 ms）。即 3.2 ms 的 Expert 差正好跨过释放点；**为何该配置下 Expert 包络更短仍未知**，不作单因素归因|
|同条件包络（收窄）|在本批**已观察轨迹**与“该格每操作取 B8 观测最大值”这一**已检查构造**中，边界未跨过释放点（两块余 **+2.49 ms**、三块 **+1.74 ms**）。结论仅限“本批已观察轨迹与已检查构造未跨过”，**不是**同条件所有波动的上界（观测最大值不是上界，样本仅 2 段）；也不仅由成本差断言数值配置造成差异。构造的 Δ **超出**该批已观察范围，标 `SENSITIVITY_CONSTRUCTION`|
|条件化重放|B4 源重放**逐值复现**冻结预测（180/140 × 两切分 × 两场景：feasible 与三项最小余量全部一致）；B8 自身成本重放**复现实际派发次序**（8/8 段）且完成误差 ≤6 ms。后者是**回顾性解释**，不是前瞻验证，不回写预测|
|两候选（非支配）|两块 two_9_9：min cycle/Expert/refresh（180→140）= 41.921/41.921/162.200 → **2.551/2.551/82.821**；三块 three_prefix_9_9 = 40.587/91.303/157.805 → **1.934/24.322/82.131**。三块的紧余量来自 **B1→B3 的块边界**（Expert 仍余 24 ms），与两块“翻转=该 Expert 违约”性质不同；两者不加权、不选赢家|
|工程默认|允许继续以 two_9_9 为默认，依据仅限：边界更少、且紧余量恰好等于某 Expert 的 deadline 余量（翻转与 Expert 违约同一事件，可被现有指标看见）。**不是性能最优或稳健性证明**|
|未覆盖/证据不足|176 边界中 **0** 个“已释放但版本未就绪”、**0** 个完成区间跨释放点（该规则仅 CPU 覆盖）；B8 该批 **0/64 周期、0/32 刷新**（只作 0/n 观测率，非零风险）；每格 2 段同进程顺序、非独立重复；未构造块耗时扰动；平台根因不在本轮范围|
|统计口径（2026-10-23 统一）|零违约只报 **0/n** 与测试长度，按 §7.3 不算倍数、不等于总体风险为零；n=8/16 的 nearest-rank p99/p99.9 等于样本最大值，**不称尾部证据或 WCET**；周期相关，未建立统计假设，不套独立伯努利上界。**B5 180 ms 有有限配对收益**（serial 周期 8/16 对 boundary 0/16，刷新均 8/8）；**B6 180 ms boundary 并非零违约**（周期 28/32、刷新 12/16；serial 16/32、刷新 16/16）；不同批次条件不同，**不合并**成总体违约率|
|CPU|`rbe/test_rbe_cpu.py` **30/30 PASS**：释放点前/相等/后、Expert 已完成/未释放/已释放但版本未就绪、队列与未来到达不混淆、区间跨释放点标 UNCERTAIN、耗时变化改次序但释放与 deadline 不变、翻转后工作量/依赖/版本/读者合法、Expert 提前但刷新推迟不误报改善、缺记录不填零且保留分母、B4/B8 不混池、冻结输入 SHA 不变|
|B8 报告更正|`RUN_REPORT.md` 一句表述更正：140 ms 最小**周期**余量 1.934–2.551 ms；最小 **Expert** 余量两块 2.551 ms、三块 24.322 ms。统计数值与原始记录未改（`RUN_SUMMARY.json`/`PREDICTION_COMPARISON.json`/`result.json`/`PREDICTION.json` SHA 不变），保留更正前副本与 diff|
|状态/证据|B2 仍候选；**M3 未完成**；不进入 M4。交付 [README.md](reports/m3_b2/20261023/release_boundary_evaluator_v1/README.md)、[MAINLINE_RESULT.md](reports/m3_b2/20261023/release_boundary_evaluator_v1/MAINLINE_RESULT.md)、[M3_ACCEPTANCE_GAP.md](reports/m3_b2/20261023/release_boundary_evaluator_v1/M3_ACCEPTANCE_GAP.md)、[BOUNDARY_AUDIT.csv](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/BOUNDARY_AUDIT.csv)、[REFRESH_COVERAGE.csv](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/REFRESH_COVERAGE.csv)、[DEADLINE_MARGINS.csv](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/DEADLINE_MARGINS.csv)、[MARGIN_IDENTITY.csv](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/MARGIN_IDENTITY.csv)、[SENSITIVITY.json](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/SENSITIVITY.json)、[PLAN_EVALUATION.json](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/PLAN_EVALUATION.json)、[FINGERPRINTS.json](reports/m3_b2/20261023/release_boundary_evaluator_v1/outputs/FINGERPRINTS.json)、[CPU_TESTS.log](reports/m3_b2/20261023/release_boundary_evaluator_v1/CPU_TESTS.log)、[MINIMAL_DIFF.patch](reports/m3_b2/20261023/release_boundary_evaluator_v1/MINIMAL_DIFF.patch)、[B8_REPORT_CORRECTION](reports/m3_b2/20261023/release_boundary_evaluator_v1/B8_REPORT_CORRECTION/CORRECTION.md)|
|下一命题（**已撤回**）|撤回“140 ms 下 E(2q) 晚于 release(2q+1) 完成即发布必然 >280 ms”：本轮 `SENSITIVITY.json` 反例为 **199.670→271.605 ms**（两块）与 **199.655→271.743 ms**（三块），deadline 280 ms，**仍 PASS**；据此提出的“≥2 独立进程、各 16 周期”建议一并撤回。更正后：翻转使发布晚约 72 ms 但刷新按时，**Expert/周期/刷新分别判定**；≥70 ms 只是这些成本下的构造结果，不是任意负距离的下界。原始构造与输出保留，不重写数据。是否以及如何提出下一命题，见 [NEXT_RESEARCH_DECISION.md](reports/m3_b2/20261023/reconciliation/NEXT_RESEARCH_DECISION.md)|
|M3 验收差距|按任务书 §4/§5.1/§7/§8 重列：净机制收益有 **B5 有限配对计数差**（8/16 对 0/16，可报告样本违约率，但缺少可靠的总体率估计与推广证据），且该差异被 **B6 刷新回归**部分抵消；开销分解**部分可由现有 `operations` 整理**（GPU 分项、边界等待、stage），**Host launch/提交 CPU 与跨块状态维护 CPU 无直接测量**；计划余量**仅离线量、尚未改变任何执行选择**。§5.1 的 KV 正确性属任务书要求（D1 为项目准入协议，不重跑 M2；D2 为未实施的固定算法方案）。不预设阻挡项恰好两个。详见 [M3_ACCEPTANCE_GAP.md](reports/m3_b2/20261023/release_boundary_evaluator_v1/M3_ACCEPTANCE_GAP.md)|
|复核勘误（2026-10-23）|本轮撤回一个被自身构造否定的命题、收窄两处过强解释、统一统计口径，并恢复 PROJECT_STATUS 历史原文。旧说法→反证→修正位置见 [CORRECTION_MATRIX.md](reports/m3_b2/20261023/reconciliation/CORRECTION_MATRIX.md)，恢复范围见 [STATUS_RECOVERY.md](reports/m3_b2/20261023/reconciliation/STATUS_RECOVERY.md)|

## 历史：2026-10-22 split × budget challenge b8（RUN）

> 2026-10-22 实际执行批的历史记录。140 ms 结论行的“周期/Expert 余量”混写已于 2026-10-23 更正（数值未改，见 `reports/m3_b2/20261023/release_boundary_evaluator_v1/B8_REPORT_CORRECTION/`）。

|项目|结果与边界|
|---|---|
|协议/执行|`m3_b8_split_budget_challenge_v1`；1 普通 nvidia 模型 **76.680 s** + 1 次五节点 scope **78.600 s**/80 samples；`MODEL_ATTEMPT_USED`/`SCOPE_ATTEMPT_USED` 各 1；0 retry、0 压力 worker、无 profiler；`restored=true`，独立 uid1001 读回 **PASS**，无残留进程/服务/psm|
|四条件/顺序|A two/180、B three/180、C two/140、D three/140；顺序 **A,B,C,D,D,C,B,A**；每段 8 周期/4 刷新；两块/三块均 `b2_boundary`、quiet、phase +15 ms、lead 10 ms；同预算 A/B、C/D 严格配对；180/140 不是同一墙钟轨迹；本批无 serial 对照|
|工作量/正确性|计时 64 Expert10 / 32 Context；全批 52C/70E；观察账本 **13,400 行**；Autotune 36 另账；**261/261 checks PASS**；D1 同进程逐字节；gates 22/24 PASS；assembly/prefix reference PASS；8 段 retention 64/76 与 call ledger 全 PASS；**64/64 周期 PASS、32/32 刷新 PASS**，0 INCOMPLETE/UNCERTAIN；`cross_process_gate` 仅报告（admission=false, within_historical_envelope=true）|
|性能（两段合并，非独立重复）|A two/180：16/16 周期、8/8 刷新；min cycle/Expert/refresh **41.921/41.921/162.200 ms**。B three/180：16/16、8/8；**40.587/91.303/157.805 ms**。C two/140：16/16、8/8；**2.551/2.551/82.821 ms**。D three/140：16/16、8/8；**1.934/24.322/82.131 ms**。各格 `backlog_max=1`、`ready_experts_max=1`、`version_wait_rows=0`、`deferred=0`|
|140 ms 结论|本样本两块/三块均通过，但最小**周期**余量 **1.934–2.551 ms**、最小 **Expert** 余量两块 **2.551 ms**/三块 **24.322 ms**（2026-10-23 表述更正，数值未改）；没有出现 backlog>1、多 Expert 排队、版本等待或 publication deferred。140 ms 的挑战主要表现为余量收缩；**不是测得边界、违约率、尾部或一般可行性结论**|
|预测身份/条件|运行前预测 `d7b41775…`，状态 `EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED`；r1 正式域仍拒绝 180/140 正式选择。实际条件 **`CONDITION_MISMATCH`**：除 period/新协议外，B4 成本来源为 `OTHER_S0_0c63ddfb1c91`（matches_frozen=false），B8 实际为 `H_frozen`（matches_frozen=true），S0 context SHA 不同；B8 cross-process envelope=true vs B4 false（仅报告）。因此**不是原条件下预测验证**，只作超出适用域的外推比较；不声称配置差异是 140 ms 差异的因果原因|
|预测表现（180）|A/B 的 order/version/status 全部匹配；completion signed mean +2.7–4.4 ms、max abs 7.8–10.8 ms；stress exceed 8–10 jobs，最大 0.44–0.53 ms；预测/实际均可行|
|预测表现（140）|预测判 C/D 不可行（4/8 周期 FAIL），实际均 **16/16 周期 PASS、8/8 刷新 PASS**；错误判不可行按两段合计 C typical 16、C stress 16、D typical 8、D stress 8，错误判可行 0；order **mismatch**、version match；completion abs mean 26.2–30.6 ms、max 81.7 ms；stress Expert 实际晚于 stress 预测 34–37.5 ms。这是**预测包络超出**，不是执行器正确性失败；不得回写冻结预测|
|备份/恢复|板端 nvidia 可读 **191 文件 / 5,090,582,139 B** 与本机 SHA **191/191 一致**；`clock_before.json` root 0600 2,980 B 未读取/未复制/无 SHA 声明。真实 snapshot、后代清理、逆序恢复、独立读回均 PASS|
|边界/停止|每条件两段同进程顺序，不是独立重复；每格 16 周期/8 刷新；不支持长尾、违约率、WCET、k_min、最终切分、相对 serial 收益或 M4。140 ms 通过仅限本样本/配置/相位。预测失败/包络超出不是重试理由；本批未追加实验|
|状态/证据|B2 仍候选；M3 未完成；不进入 M4。结果 [RUN_REPORT.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/RUN_REPORT.md)、[RUN_SUMMARY.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/RUN_SUMMARY.json)、[PREDICTION_COMPARISON.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/analysis/PREDICTION_COMPARISON.json)、[PERFORMANCE_SEGMENTS.csv](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/analysis/PERFORMANCE_SEGMENTS.csv)、[PREDICTION_ERRORS.csv](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/analysis/PREDICTION_ERRORS.csv)、[BACKUP_VERIFICATION.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/BACKUP_VERIFICATION.json)|


## 历史：2026-10-22 split × budget challenge b8 准备（PREPARED，已被实际执行取代）

> 准备阶段的预测/预算/CPU 结果保留；实际执行与预测比较见上方。运行前预测未被改写。

|项目|结果与边界|
|---|---|
|协议/目录|`m3_b8_split_budget_challenge_v1`；[split_budget_challenge_b8_v1](reports/m3_b2/20261022/split_budget_challenge_b8_v1/)。独立协议，不改历史协议/冻结包/生产执行器/原始数据|
|四条件|A two_9_9+`b2_boundary` P=D=180 ms；B three_prefix_9_9+`b2_boundary` 180 ms；C two_9_9 140 ms；D three_prefix_9_9 140 ms；顺序 **A,B,C,D,D,C,B,A**；每段 8 周期/4 刷新；同预算 A/B、C/D 严格配对，180/140 不是同一墙钟到达轨迹|
|固定项|quiet、0 压力 worker；Expert 相位 +15 ms；lead 10 ms；固定输入/噪声/checkpoint/BF16/完整工作量；固定版本消费/FIFO/既有义务分组；非 Graph、单 Stream、无分区、无并发；本批无 serial 对照，不产生相对 serial 收益结论|
|140 ms 定位|预声明挑战点，依据历史约 139–142 ms 周期响应选择；**不是已测出的可行边界**，不预设两块或三块通过；预测若判不可行仍保留该条件，不回调预算|
|运行前预测|[PREDICTION.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/prediction/PREDICTION.json) SHA `d7b41775…`，状态 **EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED**、条件 **OUT_OF_SOURCE_APPLICABILITY_DOMAIN**；仅改 P，复用 r1 冻结 median/sample-max 成本与模型，无补偿/倍率/拟合。r1 正式域仍拒绝：180 ms **INSUFFICIENT_EVIDENCE**、140 ms **UNSUPPORTED_INPUT**。预测（非结果）：180 ms 两候选均可行（stress min cycle two 38.827 / three 38.006 ms）；140 ms 两候选均不可行（two −1.173 / three −1.994 ms，各 4/8 周期 FAIL）。不要求预测为正或三块胜出|
|工作量/预算|计时 **32C/64E**；全批 **52C/70E**；观察账本 **49C/69E = 13,400 行**；Autotune **36** 另账；bank **597,617,152 B**、GPU+pinned **1,195,234,304 B**、payload **4,339,748,864 B**、gates **248,242,944 B**、二进制 **5,087,214,824 B**、磁盘估算 **6,259,915,173 B（5.83 GiB）** < 12 GiB；声明周期和 **10.24 s**；内部 170 s、外层 180+10 s、scope 415 s<420 s。投影不是保证|
|CPU|`validate_m3_b8_cpu.py` **17/17 PASS**（0 fail/0 error）：四条件真实驱动 plan/P/释放/deadline/刷新；8 唯一 segment 与顺序；两块/三块全部块与义务；140 ms 长耗时下多 Expert 排队、Context 积压、固定版本与读者保护；性能 FAIL 不触发正确性停止/丢弃后续段；总截止保留完整分母及 INCOMPLETE；首段/中段失败归属及未验证 bank 不可复用；预测入口不改正式域、不写回 r1；完成/响应/三类余量时间原点一致；凭据/协议/配置/入口一致。复用 B3/B4/B5 CPU 夹具，未重跑全部历史检查；0 model/worker/SSH/hardware/scope|
|复用/差异|复用 B5 逐段预算 manifest 与 `confs`、B4 两切分数学/装配/前缀/gate、B7 仅 10 ms lead 证据；`m3_b3_orchestrate.run_candidates` 增加可选 `expects`，执行前核对段 manifest 与本批 canonical manifest。新增 `m3_b8_plan.py`、`pi05_m3_b8_challenge.py`、`m3_b8_control.py`、CPU 套件。不用 B7 4 s 准备等待/22 点专项观测、不引入压力 worker、不新增切点/策略/Graph/预热/keepalive|
|审批/停止|一次性具体审批见 [APPROVAL_CHECKLIST.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/APPROVAL_CHECKLIST.md)；批准前不运行。停止：170 s/180+10 s、热 ≥80 °C、磁盘 <12 GiB、五节点/EMC 偏差、留存/地址/装配/gate/账本/协议/段 ID/预算不符。**性能违约/积压/排队/版本等待/预测失败/经验包络超出不是停止或重试理由**；总截止未完成保留分母和 INCOMPLETE，不扩时|
|状态/停止|PREPARED / NOT APPROVED / NOT RUN；无 GPU PASS、无最终选线、M3 未完成、不进入 M4；B2 仍候选。方案 [GPU_PLAN.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/GPU_PLAN.md)、预测 [PREDICTION.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/prediction/PREDICTION.md)、评价口径 [EVALUATION_PROTOCOL.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/prediction/EVALUATION_PROTOCOL.md)、逐段模板 [RESULTS_TEMPLATE.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/RESULTS_TEMPLATE.json)、复现 [REUSE_AND_DIFF.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/REUSE_AND_DIFF.md)、[MINIMAL_DIFF.patch](reports/m3_b2/20261022/split_budget_challenge_b8_v1/MINIMAL_DIFF.patch)|
|下一阶段前置|用户明确批准唯一模型+五节点 scope、板端 CPU preflight 通过、部署 SHA 核对、独立读回与恢复路径就绪；缺一不运行|

## 历史：2026-10-22 实测驱动计划选择器 r1（分析基线，保留）

> r1 仍是 b8 预运行预测的成本/规则/模型来源；其正式适用域未被本次修改。r1 的 240 ms 结论与回顾性核验仍限于原样本，不因 b8 准备升级为前瞻结论。

|项目|结果与边界|
|---|---|
|主线问题|在固定工作、释放轨迹、预算和版本规则下，已有测量支持哪个合法切分计划；Expert/周期/刷新余量；何时必须返回证据不足或不可行|
|选择空间|**two_9_9+b2_boundary**、**three_prefix_9_9+b2_boundary**；serial_context 只作离线机制对照，不作为候选；未新增调度/切点/义务规则|
|主条件/验证身份|B4 P=240 ms、phase +15 ms、quiet（批次声明）、8 cycles/4 refreshes；pass 1 B/D 提成本，pass 2 D/B 为**第一遍成本提取、第二遍分离评价的回顾性检验**；B4 pass 2 在 v1 已分析，**不是前瞻、不是此前未见数据**；同进程顺序，不是独立重复或外部泛化|
|训练成本/条件|从原始 operations **Event total** 提取；Layer 不均分；stage 首次/后续 Host 启动成本单列；B4 pass 1 每计划 8 Expert、4/8 个块样本、1 个 first-stage/3 later-stage 样本；B5/B6/B7 不混池。结构化 condition 含 period/phase/cycles、lead、pressure、数值 configuration、输入/checkpoint/精度、版本消费、义务分组、留存/观测、clock limits；无法取得的字段标 **UNKNOWN**（pressure worker 数/runtime audit、device、temperature），不猜测|
|成本/freeze|`TRAIN_COSTS.json` SHA `5b9df9782c71981959008203f1d4a129fa6f9f5c71d359d7690f43abfae5a948`；`RULES.json` SHA `8c3eb365e5f23c7c36fbd78cd0013090443a1d2524e934e066cbb24fa10e3712`；`FREEZE.json` SHA `72228b75075e0475fc6ccc5e0066351c1efe5021a56429a015dadb53d4efd211`；`plan_model.py` SHA `2ee21ef17d6cd03eb5dc21336ad7c2b2c370544f6091b1193ff7894669552237`；frozen `m2_executor.py` SHA `7890fa54…`。显式 freeze 校验 costs/rules/catalog/selection、evidence/evaluator/selection/plan_model/model_env/validate/freeze、executor 及 9 项声明输入；不一致在评价前拒绝且不产出正常结果，验证不重写清单|
|选择结果|P=240 两候选均 **EMPIRICALLY_FEASIBLE**：two min cycle **98.827 ms** / Expert **98.827 ms** / refresh **279.132 ms** / max refresh response **200.868 ms** / max completion offset 1640.709 ms；three **98.006** / **147.564** / **278.120** / **201.880 ms** / 1641.690 ms。两候选 **非支配**：two 的周期/刷新余量更大、最大完成偏移更小，three 的 Expert 余量更大；不唯一、不加权。旧 1640.709/1641.690 ms 仅作为相对整段 t0 的完成时刻保留，**不是**最大刷新响应|
|三块判断|**有限结论**：三块在本模型中减少 Expert 等待、min Expert 余量更大，但**没有证据**支持其在完整周期/刷新层面优于两块；不把“三块周期/刷新不劣”写成下一批预期。two 仅可作为减少边界数的工程默认，不是已证明性能最优|
|P=180|**INSUFFICIENT_EVIDENCE**；B5/B6/B7 只有 two_9_9，且 lead/startup/pressure/observation 不同；没有三块 180 ms 证据，不把 two 的成本迁移成 three；本次修正不推算其通过|
|回顾性核验|B4 pass 2：**completion（Expert/块）** two **16/16**、three **20/20**；**deadline（周期/刷新）** 各 **12/12**；各 scenario 实际 cycle **8/8** PASS、refresh **4/4** PASS；false feasible/infeasible/missing 全 **0**；mean/max abs completion offset two 0.469–0.529 / 0.994–1.060 ms，three 0.664–0.686 / 1.245–1.291 ms。合并总数 28/28、32/32 仅作行数，**不冒充**全部时限分类；零误判只适用于这些样本，不能证明临界失败识别能力|
|B5/B6/B7 补充|仅自身批次/条件 sample-in-batch replay：B5 D 180 通过、B6 B 4 s 与 B7 B 4 s 模型判不可行且实际 7/8+3/4、B7 A 10 ms 通过；completion 与 deadline 匹配分列；不进入 B4 选择、不混成本；B7 Event0 定位不回溯为 B6 直接测量|
|CPU|`selector/test_selector_cpu.py` **30/30 PASS**；新增实际反例：相同刷新响应不同释放时刻、lead/pressure/configuration/protocol/version 条件拒绝、冻结规则目标不相容、未识别目标参数拒绝、临时修改成本/规则/源码分别被 freeze 拒绝、一候选不可行另一可行保留可行、全部不可行才 NO、缺完成记录仍 INCOMPLETE、Expert 完成与时限分列；故障注入只用临时副本；0 model/worker/SSH/hardware/scope|
|状态/停止|无 GPU PASS、无最终选线、M3 未完成、不进入 M4；B2 仍候选。输出 [MAINLINE_RESULT.md](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/MAINLINE_RESULT.md)、[REVISION_CHANGES.md](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/REVISION_CHANGES.md)、[V1_TO_R1_CHANGES.md](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/V1_TO_R1_CHANGES.md)、[EVIDENCE_CATALOG.json](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/freeze/EVIDENCE_CATALOG.json)、[VALIDATION_JOBS.csv](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/validation/VALIDATION_JOBS.csv)、[SELECTION_240.json](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/freeze/SELECTION_240.json)、[SUPPLEMENTAL.md](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/supplemental/SUPPLEMENTAL.md)、[FORWARD_VALIDATION_INTERFACE.md](reports/m3_b2/20261022/empirical_plan_selector_v1_r1/FORWARD_VALIDATION_INTERFACE.md)|
|缺失证据/下一步接口|B4 之外没有同条件独立批次；三块 180 ms 缺测；固定压力下两候选没有同条件证据。r1 不提出“三块全面非劣”命题；前瞻验证的实验条件、误差判据与唯一批次方案由 Codex 审阅 r1 后确定，接口见 FORWARD_VALIDATION_INTERFACE.md|

## 历史：2026-10-22 实测驱动计划选择器 v1（已被 r1 取代）

> 历史原文保留。v1 的 `max_refresh_ready_ms` 实为相对整段 t0 的完成时刻，1640.709/1641.690 ms **不是**最大刷新响应；v1 的 28/28、32/32 是合并 job/status 匹配，**不是**时限分类。r1 已修正，见上方当前状态。

|项目|结果与边界|
|---|---|
|主线问题|在固定工作、释放轨迹、预算和版本规则下，已有测量支持哪个合法切分计划；Expert/周期/刷新余量；何时必须返回证据不足或不可行|
|选择空间|**two_9_9+b2_boundary**、**three_prefix_9_9+b2_boundary**；serial_context 只作离线机制对照，不作为候选；未新增调度/切点/义务规则|
|主条件|B4 P=240 ms、phase +15 ms、quiet、8 cycles/4 refreshes；pass 1 B/D 提成本，pass 2 D/B 为同进程顺序留出；**不是独立重复或外部泛化**|
|训练成本|从原始 operations **Event total** 提取；Layer 不均分；stage 首次/后续 Host 启动成本单列；B4 pass 1 每计划 8 Expert、4/8 个块样本、1 个 first-stage/3 later-stage 样本；B5/B6/B7 不混池|
|成本/freeze|`TRAIN_COSTS.json` SHA `6a7730c861a97c0f4010e69603cc5c3fb532a4037aa1609b64d7175485b56f12`；`RULES.json` SHA `2db4c77e4ae94794fc256bf51d9212b71424397755a5bfc7e7986b4219048a06`；`plan_model.py` SHA `2ee21ef17d6cd03eb5dc21336ad7c2b2c370544f6091b1193ff7894669552237`；frozen `m2_executor.py` SHA `7890fa54…`|
|选择结果|P=240 两候选均 **EMPIRICALLY_FEASIBLE**：two min cycle **98.827 ms** / Expert **98.827 ms** / refresh **279.132 ms** / max ready **1640.709 ms**；three **98.006** / **147.564** / **278.120** / **1641.690 ms**。两候选 **非支配**：two 在周期/刷新/ready 更好，three 在 Expert 更好；不唯一、不加权|
|三块判断|**没有证据支持三块在完整周期/刷新层面优于两块**；其 Expert 余量更大但周期/刷新余量更小。two 仅可作为减少边界数的工程默认，不是已证明性能最优|
|P=180|**INSUFFICIENT_EVIDENCE**；B5/B6/B7 只有 two_9_9，且 lead/startup/pressure/observation 不同；没有三块 180 ms 证据，不把 two 的成本迁移成 three|
|Holdout 验证|B4 pass 2：two **28/28**、three **32/32** job/status 匹配；false feasible/infeasible/missing 全 **0**；mean/max abs completion error two 0.469–0.529 / 0.994–1.060 ms，three 0.664–0.686 / 1.245–1.291 ms；实际 cycle/refresh 全 PASS|
|B5/B6/B7 补充|仅自身批次/条件 sample-in-batch replay：B5 D 180 通过、B6 B 4 s 与 B7 B 4 s 模型判不可行且实际 7/8+3/4、B7 A 10 ms 通过；不进入 B4 选择、不混成本；B7 Event0 定位不回溯为 B6 直接测量|
|CPU|`selector/test_selector_cpu.py` **13/13 PASS**；缺失成本/180/不支持输入拒绝；固定释放、完整义务/FIFO/版本绑定、启动进入时间线、Expert 早但周期晚的 tradeoff、INCOMPLETE 不 PASS、训练/验证互斥、max≠formal bound；0 model/worker/SSH/hardware/scope|
|状态/停止|无 GPU PASS、无最终选线、M3 未完成、不进入 M4；B2 仍候选。输出 [MAINLINE_RESULT.md](reports/m3_b2/20261022/empirical_plan_selector_v1/MAINLINE_RESULT.md)、[EVIDENCE_CATALOG.json](reports/m3_b2/20261022/empirical_plan_selector_v1/freeze/EVIDENCE_CATALOG.json)、[VALIDATION_JOBS.csv](reports/m3_b2/20261022/empirical_plan_selector_v1/validation/VALIDATION_JOBS.csv)、[SELECTION_240.json](reports/m3_b2/20261022/empirical_plan_selector_v1/freeze/SELECTION_240.json)、[SUPPLEMENTAL.md](reports/m3_b2/20261022/empirical_plan_selector_v1/supplemental/SUPPLEMENTAL.md)|
|最需验证的命题（v1，已撤回）|v1 曾提出“three min Expert 高于 two 且 min cycle/full-refresh 不低于 two”；r1 删除该命题：当前没有依据把三块全面不劣设为下一批预期。|

## 历史：2026-10-22 B7 stage-startup 实际执行（RUN + PASS diagnostic）

|项目|状态与边界|
|---|---|
|协议|`m3_b7_stage_startup_v1`；唯一变量为准备完成后的 lead：A **10 ms**、B **4 s**；两条件均为 quiet、`b2_boundary`、`two_9_9`、P=D=180 ms、Expert +15 ms；顺序 **A,B,B,A**，4 段，每段 8 周期/4 刷新|
|共享入口|两条件都走同一个 `SegmentWindow`，只由 `lead_ns` 配置区分；t0 在 bootstrap、初态恢复、报告初始化和 GPU 排空之后确定一次，之后不移动；同一 `nominal_end=t0+1.440 s`、`end=t0+2.160 s`、0.720 s drain；无压力 worker|
|观测|仅 stage 路径；每段 4 次 stage，每次固定 22 个 Host 时间戳（入口/出口、Event0/1/2/7前后、images/noise restore前后、images/noise capture前后、Event7等待起止、完成确认）；4×22 预分配；轮询只留计数；不加 GPU 操作/同步/预热；D2H/比较/写盘在窗口之后|
|工作量|计时 16 Context/32 Expert；全批 32C/38E；观察账本 29C/37E = 29×20+37×180 = **7,240 行**；Autotune 36 请求另账；每段 64 entry/487,320,064 B；GPU+pinned 同尺寸 bank|
|磁盘/时间|4 段路径重算：payload 1,949,280,256 B + 2 gates 248,242,944 B + 6 labels 151,658,496 B + bootstrap 75,829,248 B + fixed 120,076,776 B + JSON/temp ≈ **3,342,248,562 B（3.11 GiB）**；12 GiB admission；内部 170 s、外层 180 s+10 s、scope 420 s；B6 推导投影 54.457 s（allowance 64.457），不是保证|
|CPU|B7 **25/25 PASS**（lead/order、同一 SegmentWindow、四 stage 观测、阶段调用顺序、B6 r1 资源闸门、异常归属、工作量/账本/磁盘、CLI/凭据）；B6 **37/37 PASS** 回归；0 model/worker/SSH/hardware/scope|
|冻结|35 文件；[DEPLOY_SHA256.txt](reports/m3_b2/20261021/stage_startup_b7_v1/deployment/DEPLOY_SHA256.txt) SHA `0dea6615563d38d440cb7672f54b7fa8fc102885f2433eac2cd865cc4cc0b004`；[CONFIG.json](reports/m3_b2/20261021/stage_startup_b7_v1/deployment/CONFIG.json) SHA `afa7f6f911ff7431b4da1ea85388d1cdd16518f6413f6bcc118c060f9e2b587c`；[FREEZE.json](reports/m3_b2/20261021/stage_startup_b7_v1/FREEZE.json)；[GPU_PLAN.md](reports/m3_b2/20261021/stage_startup_b7_v1/GPU_PLAN.md)；[APPROVAL_CHECKLIST.md](reports/m3_b2/20261021/stage_startup_b7_v1/APPROVAL_CHECKLIST.md)；[RESULTS_TEMPLATE.json](reports/m3_b2/20261021/stage_startup_b7_v1/RESULTS_TEMPLATE.json)、[B7_RUN_REPORT.md](reports/m3_b2/20261021/stage_startup_b7_v1/B7_RUN_REPORT.md)、[B7_ANALYSIS.json](reports/m3_b2/20261021/stage_startup_b7_v1/B7_ANALYSIS.json)、[B7_STAGE_TIMELINE.md](reports/m3_b2/20261021/stage_startup_b7_v1/B7_STAGE_TIMELINE.md)、[B7_BACKUP_VERIFICATION.json](reports/m3_b2/20261021/stage_startup_b7_v1/gpu_run_01/B7_BACKUP_VERIFICATION.json)|
|执行|1 普通 nvidia 模型 + 1 五节点 scope，0 重试；模型 **42.591 s**，scope **44.442 s / 46 样本**，`SCOPE_RESULT=PASS`、`restored=true`；独立读回 PASS（uid 1001）；`SCOPE_ATTEMPT_USED`/`MODEL_ATTEMPT_USED` 各 1；0 压力/fixed worker|
|实际 A/B|A（10 ms）**16/16 cycles、8/8 refresh**，首 stage Host **0.748–0.751 ms**，Event .553–.557；B（4 s）**14/16、6/8**，首 stage **93.328–94.008 ms**，Event .411–.489。B 两个 segment 均 cycle0 VLM FAIL（233.873/232.621 ms）与 R0 FAIL（368.281/367.239 ms）；A 全 PASS。A 为 B1-first，B 为 E0-first；后续 stage 正常。**等待条件与首次延迟在本批对应；底层机制未知**|
|Event0 定位|B 首次 Event0 record Host **93.507433 / 92.891151 ms**，占首次 stage **99.47% / 99.53%**；A 为 **0.063200 / 0.060672 ms**，占 **8.42% / 8.11%**；16 个 stage 的其余区间与未分类间隙见 [B7_STAGE_INTERVALS.md](reports/m3_b2/20261021/stage_startup_b7_v1/corrections/output/B7_STAGE_INTERVALS.md)。**已定位可观测 Host 调用区间，底层根因仍未确定**；Host 包络非纯驱动/Kernel，B7 定位不回溯冒充 B6 直接子调用测量|
|工作/正确性|363/363 checks；完整 32C/38E；观察 29C/37E = **7,240 行**；Autotune 36；每段 64 entry/487,320,064 B；gates 22/24；D1/确认/资源全 PASS；stage observation 4×22 全 complete/ordering/counts PASS|
|备份|本地 `gpu_run_01/board/run_01` **137 文件 / 2,547,063,450 B**；136 个 readable payload SHA 全通过；root 600 `clock_before.json` **2,981 B 未读取**，不声称原始 SHA；用户可读副本 `clock_before.readable.json` 2,981 B SHA `545a3ab9…`；详见 [B7_BACKUP_VERIFICATION.json](reports/m3_b2/20261021/stage_startup_b7_v1/gpu_run_01/B7_BACKUP_VERIFICATION.json)|
|解释规则|长 lead 有明显首次延迟、短 lead 没有→报告等待与延迟对应及主要 Host 区间，不宣布 GPU 唤醒/缺页/驱动/频率根因；两者都有/都没有/顺序不一致→如实保留所有段，不加等待时长、不重启碰配置|
|停止|不删除 cycle 0、不扣除首次开销、不生成修正性能、不把诊断当新性能基线、不自动加保活/预热、不进入 M4；B2 仍候选，M3 未完成|

## 历史：2026-10-21 b6 r1 实际执行（RUN + PASS protocol）

|项目|结果与边界|
|---|---|
|执行|1 普通 nvidia 模型 + 1 五节点 scope，0 重试；模型 **83.853 s**（内部 170/外层 180 s），scope **86.602 s**（上限 420 s）；`SCOPE_RESULT=PASS`、`restored=true`、88 样本；`INDEPENDENT_RESTORE_READBACK=PASS`（uid 1001）|
|协议/证据|部署 SHA `96a1c748d7651c40c38b4ba97b6a82a681c781632bac7bf93e2ce77a125c37d2`；8/8 段、257/257 checks；D1 逐字节、两个 gate、完整 52C/70E、13,400 行 ledger、每段 64 entry/487,320,064 B 留存均通过|
|四条件周期|A **8/16** PASS、B **14/16**、C **8/16**、D **14/16**；A/C 在 0,2,4,6 的 Expert 违约，B/D 仅 cycle 0 的 VLM 违约；无 cell 达到 8/8|
|四条件刷新|A **8/8**、B **6/8**、C **8/8**、D **6/8**；B/D R0 ready 362.690–371.189 ms，超过 360 ms deadline；A/C 全部通过|
|比较|A→B +6 cycle/+8 Expert/−2 VLM/−2 refresh，cycle median −38.763 ms；C→D +6/+8/−2/−2，median −39.134 ms。A→C/B→D 的通过数不变，fixed 相对 quiet 的均值约 +4.5/+5.4 ms，不能据此声称因果干扰效应。**B/D 相对 B5 D 的边界退化限定在本批 startup 条件**（B5 D 首 stage ~0.5 ms、B1先于E0，16/16+8/8；B6 B/D 首 stage ~90 ms、E0先于B1，14/16+6/8），不是固有代价 |
|干扰工作|C,D,D,C 共 4 个顺序 CPU11 worker（任一时刻 1 个，quiet 0，0 retry）；copies 598/598/595/598，合计 **2,389 copies / 80,161,538,048 B logical memmove**；start lateness 55.996–58.934 µs，guards PASS，资源全部 released，8/8 condition_valid|
|首次 stage|B6 八段 first R0/stage Host（decision→completion lower）**89.332–93.988 ms**，GPU Event **0.321–0.441 ms**；quiet 90.025–93.988/.321–.359，fixed 89.332–93.880/.396–.441。B5 同 180 C/D 为 **0.490–0.510 ms / 0.532–0.569 ms**；B6 后续 R1 Host .147–.166、R2/R3 .322–.483，说明异常仅首 stage。首 stage 的 cause **来源未定位**；4 s 准备等待只是协议差异候选，不断言 GPU 唤醒/锁频/缺页/驱动 |
|观察边界|worker copy loop 在 declared worker_end 后 **2.063–3.129 ms** 退出（一个 32 MiB copy 粒度）；无 replay 操作/周期/刷新 late；父进程 worker_end 观察约晚 32 ms。model shutdown 有 1 条 resource_tracker 警告列出 4 个已 unlink 的 shm 名称；运行后 `/dev/shm` `psm_*`=0、无 tracker/worker/systemd 残留。两者均保留为实际观察，不当作零边界|
|硬件|scope 先真实 snapshot；CPU0/4/8、GPU、EMC min 均恢复为 729600/729600/729600/306000000/204000000；max/governor/power 不变；EMC 88/88 样本 READ 3199000000；无残留|
|备份|本地 `gpu_run_01/board/run_01` **192 文件 / 4,649,349,033 B**；191 个 nvidia-readable 文件按远程 SHA 全通过；root 600 `clock_before.json` 由用户 sudo cp 为可读副本（SHA `22b1b679…`），原文件未改；`BOARD_SHA256_FULL.txt` 全 192 文件核验通过|
|结果文件|[RUN_REPORT.md](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RUN_REPORT.md)、[RUN_ANALYSIS.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RUN_ANALYSIS.json)、[RUN_SUMMARY.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RUN_SUMMARY.json)、[EXECUTION.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/EXECUTION.json)、[RESTORE_COMPARISON.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RESTORE_COMPARISON.json)、[BACKUP_VERIFICATION.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/BACKUP_VERIFICATION.json)|
|未覆盖/停止|长尾、违约率数量级、k_min、干扰因果、首 stage 根因、最终路线和 M4 均未声称；单次批准批次已完成，不补跑、不调强度/预算。B2 仍候选，M3 未完成 |
|阶段补充|[STAGE_TIMELINE.md](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/stage_timeline/STAGE_TIMELINE.md)、[B5_B6_COMPARISON.md](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/stage_timeline/B5_B6_COMPARISON.md)、[CALL_CHAIN_EVIDENCE.md](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/stage_timeline/CALL_CHAIN_EVIDENCE.md)、[ONE_PAGE_CONCLUSION.md](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/stage_timeline/ONE_PAGE_CONCLUSION.md)；报告 diff 见 `stage_timeline/REPORT_DIFF.patch` |

## 历史：2026-10-21 b6 r1 PREPARED（已被实际执行取代）



|项目|状态与边界|
|---|---|
|协议|`m3_b6_controlled_interference_v1`（r1 收尾修复）；`two_9_9`；P=D=180 ms；Expert +15 ms；A/B/C/D 与 A,B,C,D,D,C,B,A 不变；每段 8 周期/4 刷新|
|r1 修复|Codex 复现：`condition_valid=false` 且 `process_exit_confirmed=false`/`resources_released=false` 时 v1 仍 validate/D2H/写盘/释放 bank/PASS。r1 区分“资源已释放、仅条件/工作证据无效”和“资源未确认”；后者禁止正常 validate、全量 D2H、比较、写表、bank 释放及异常导出，保留 Host/lifecycle 证据/完整分母，bank 未验证不可复用，停止后续段；不重试/不扩时限|
|CPU 核验|`scripts/validate_m3_b6_cpu.py` **37/37 PASS**：v1 29 项保留 + 8 项（TERM/KILL 忽略、退出但 release false、零拷贝安全失败、正常路径、真实入口异常清理、真实 main 合法/错协议/过期凭据）；B5 8/8、B3 entry 10/10 old-path 回归；r1 worker/lifecycle **52/52** 既有证据复用|
|证据|`reports/m3_b2/20261021/controlled_interference_b6_v1_r1/`；部署 payload **33** 文件（含 manifest 共 34），`DEPLOY_SHA256.txt` `96a1c748d7651c40c38b4ba97b6a82a681c781632bac7bf93e2ce77a125c37d2`，`CONFIG.json` `b03a275b0d4a9542a18103de51929ea0c998590f6421309c835cc58b5f77fe77`；dry-run 退出 0；v1 原包保留未改|
|状态语义|`validation.pass_` 独立保留；段 `status`/`overall_status` 由 replay、数值/版本/留存、干扰条件和资源安全综合决定；条件无效但资源安全时数值可 PASS、段总体为 `FAILED_INTERFERENCE_CONDITION`，绝不为 PASS；资源不安全为 `FAILED_UNSAFE_WORKER_RESOURCES`，`validation_status=NOT_RUN_UNSAFE_RESOURCES`|
|实现边界|仅改 `m3_b3_orchestrate` 的资源安全收尾、`pi05_m3_b6_interference` 的异常清理/凭据测试所需路径；新增 `finish_failed_active`；不改 experiment design/work/budget/worker r1/M1/M2/historical frozen semantics|
|资源/时间|bank 487,320,064 B（GPU+pinned 各一份）；磁盘估算 5.27 GiB、准入 12 GiB；时间投影 114.148/126.148 s（不是保证）；最多 4 个顺序 CPU11 worker，quiet 0，0 重试|
|未覆盖|真实 32 MiB 压力、CPU11 实际亲和性、真实窗口内无写盘审计、worker/replay 真实 t0 对齐、残留/热/频率、干扰效果、GPU 数值/性能、硬件恢复；整批未批准、未运行|
|停止|准备完成即停止：不部署、不 submit、不启动模型/压力 worker、不写硬件、不 scope；B2 仍候选，M3 未完成，不进入 M4|

## 历史：2026-10-21 b6 四条件受控干扰 v1（PREPARED，已被 r1 取代）



|项目|状态与边界|
|---|---|
|协议|`m3_b6_controlled_interference_v1`；`two_9_9`；P=D=180 ms；Expert 相位 +15 ms；四条件 A quiet/serial、B quiet/boundary、C fixed_cpu_mem/serial、D fixed_cpu_mem/boundary；顺序 A,B,C,D,D,C,B,A；每段 8 周期/4 刷新|
|准备包|`reports/m3_b2/20261021/controlled_interference_b6_v1/`；部署 payload **33** 文件（含 `DEPLOY_SHA256.txt` 共 34），`DEPLOY_SHA256.txt` `ce630787dc2e598f2db008cbda5aa5aebfa7169d9467e65c82d92486fe3b5610`，`CONFIG.json` `b03a275b0d4a9542a18103de51929ea0c998590f6421309c835cc58b5f77fe77`；dry-run 退出 0；未部署板端|
|CPU 核验|`scripts/validate_m3_b6_cpu.py` **29/29 PASS**（四条件/映射/顺序、4 s t0、1.44 s/0.72 s/2.16 s 窗口、quiet 零 worker、fixed 顺序 4 worker、readiness 失败不 replay、提前完成等满窗、overrun/0 拷贝/资源/统计顺序、finish 先于 D2H/写盘/bank 复用、失败归属与停止、真实入口 dry-run/令牌）；共用驱动回归 B5 8/8、B3 entry 10/10；r1 worker/lifecycle **52/52** 既有证据复用，未重跑历史全集|
|实现边界|仅在 `run_segment` 增加可选 window（旧路径仍 `t0=clock()+10 ms`）；`run_candidates` 增加可选 window_factory、完成/释放后才统计/D2H/比较/写盘；新增 `m3_b6_plan/window/control` 与唯一入口 `pi05_m3_b6_interference`；未改 M1 冻结脚本、GPU 数学/调度、worker r1 状态机|
|时间预算|投影 114.148 s（高清理 allowance 126.148 s），内部 170 s、外层 180 s+10 s、scope 415 s<420 s；投影不是保证，真实 D2H/启动/清理/恢复须板端测量|
|资源预算|bank 487,320,064 B（GPU+pinned 各一份）；磁盘估算 5,653,281,189 B（5.27 GiB），准入 12 GiB；最多 4 个顺序 CPU11 worker（任一时刻 1 个，quiet 0 个），worker 缓冲另列，不当 RSS 上限|
|未覆盖|真实 32 MiB 压力、CPU11 实际亲和性、正常窗口内无写盘的真实审计、worker/replay 的真实 t0 对齐、残留/热/频率、干扰效果、GPU 数值/性能、硬件恢复；整批未批准、未运行|
|停止|准备完成即停止：不部署、不 submit、不启动模型/压力 worker、不写硬件、不 scope；等待新的明确 GPU 与五节点硬件批准；B2 仍候选，M3 未完成，不进入 M4|

## 历史：2026-10-21 受控干扰 worker 修订组件 r1（CPU only）


|项目|状态与边界|
|---|---|
|组件|r1 修正 `scripts/m3_interference_worker.py`、`scripts/m3_interference_lifecycle.py`：执行结果/持久化分离；Host 工作边界与 `copies>0` 门禁；就绪单一绝对 deadline；quiet 完整窗口；独立资源释放；成本表述修正。复用 v4 guard/copy，不修改 v4/M1|
|CPU 核验|`scripts/validate_m3_interference_lifecycle_cpu.py` **52/52 PASS**：原有 29 项保留 + r1 针对性反例（持久化失败、0 拷贝 copy_window→控制器、慢 spawn/延迟接收/验证跨 deadline、quiet 取消、资源未确认退出、重复 close、context 异常）|
|证据|`reports/m3_b2/20261021/controlled_interference_worker_v1_r1/`：R1_FIX_MATRIX、WORKER_LIFECYCLE、CPU_RESULTS/CPU_TESTS、CONFIG、EVIDENCE_INDEX、MINIMAL_DIFF；v1 原目录和 `before_v1/` 保留，未覆盖|
|不可改写|M1 冻结脚本、历史数据/原始 SHA、B5 报告、GPU 数学与调度实现未改；未重跑 M1、未启动真实压力 worker|
|研究目标（不变）|`two_9_9`、P=D=180 ms、Expert 相位 +15 ms；quiet/固定干扰 × serial/boundary；输入、噪声、版本、完整工作量与 D1 不变|
|未覆盖|板端真实 32 MiB 压力、CPU11 实际亲和性、窗口内无文件 I/O 的 strace/审计、残留/热/频率、与 replay t0 的真实对齐、干扰效果、新计时窗口验收；四条件批次没有集成/冻结/批准/运行|
|停止|本轮不接入 GPU 入口，不生成最终冻结包；B2 仍候选，不进入 M4|

## 历史：2026-10-21 受控干扰 worker 组件 v1（CPU only）

|项目|状态与边界|
|---|---|
|组件|新增窗口门控 worker + 单进程生命周期控制器：`scripts/m3_interference_worker.py`、`scripts/m3_interference_lifecycle.py`；复用 v4 的 `GuardedBuffer`/`copy_once`/64 B guard/CPU11/身份/PDEATHSIG，不修改 v4 或 M1 冻结脚本|
|CPU 核验|`scripts/validate_m3_interference_lifecycle_cpu.py` **29/29 PASS**（假时钟/假进程/1 KiB 缓冲；另 1 项真实管道+共享内存的非压力 fixture）；覆盖 quiet 零启动、就绪成功/失败/超时、开始前无压力、不同完成时刻不改轨迹、正常/提前/父死、TERM 后 KILL 有界、重复启动拒绝/零重试、容量/长度/guard、异常阶段证据、窗口内无序列化/写盘/无界等待|
|源码审查|`reports/m3_b2/20261021/controlled_interference_worker_v1/WORKER_REUSE_REVIEW.md`；实际 v4 SHA `b742440e…`；历史 14 个安全 worker 的容量/哨兵/CPU11/退出字段 PASS 保留，但不能证明新预声明窗口/窗口内无写盘|
|报告校正|B5 `REPORT_CORRECTIONS.json` 的 `after.sha256` 已更新为当前 `RUN_REPORT.md` `d71dfaef…` 并有一致性核对；`REBUILD_CHECK.json` 已改为完整可执行命令（`../../plan_feasibility_v1_r1`、显式 B5 result、无省略号），实测 64 周期/32 刷新/0 issue，故障副本返回非零|
|不可改写|M1 冻结脚本、历史数据/原始 SHA、GPU 数学与调度实现未改；未重跑 M1、未追查历史根因|
|研究目标（不变）|`two_9_9`、P=D=180 ms、Expert 相位 +15 ms；quiet/固定干扰 × serial/boundary；输入、噪声、版本、完整工作量与 D1 不变|
|未覆盖|板端真实 32 MiB 压力、CPU11 实际亲和性、窗口内无文件 I/O 的 strace/审计、残留/热/频率、与 replay t0 的真实对齐、干扰效果、新计时窗口验收；四条件批次没有 PREPARED/APPROVED/RUN|
|停止|本轮不接入 GPU 入口，不生成最终冻结包；B2 仍候选，不进入 M4|

## 历史：2026-10-21 边界优先 180/240 ms 两锚点（已执行，RUN + PASS）

2026-10-21 以 1 普通模型（76.468 s）+ 1 五节点 scope（78.841 s<420 s）、零重试完成 8 段 A,B,C,D,D,C,B,A：`PASS_IN_PROCESS_BOUNDARY_BUDGET_ANCHORS`，253 checks/0 失败；硬件已恢复并经普通用户独立读回，原始数据 191 文件/**4,649,192,413 B**（190 个其他文件 4,649,189,183 B + 1 个独立恢复读回文件 3,230 B）逐文件 SHA 一致（本地审计；未重做远端对账）。**实测**：240 ms 下 serial（A）与 boundary（B）均 8/8 周期、0 违约；**180 ms 下 serial（C）两遍均 4/8、4 个周期违约**，同预算 boundary（D）两遍均 8/8、0 违约；刷新四条件均 4/4（就绪 ~198.1–198.6 ms）。观察账本 13,400 行与冻结声明一致。这是机制观察，**不是**违约率/长尾/k_min/最终路线结论（每段 8 周期、两遍非独立重复、无干扰、无相位扫描）。B2 仍候选，未进入 M4。

## 历史：2026-10-21 边界优先 180/240 ms 两锚点结果表

|项目|实测结果与边界|
|---|---|
|执行|r1 冻结包（40 文件、`CONFIG.json` `55e7cfa1…`、`DEPLOY_SHA256.txt` `d676c083…`）；1 模型 + 1 scope、零重试；`SCOPE_ATTEMPT_USED`/`MODEL_ATTEMPT_USED` 各 1|
|八段|每遍分母：A/B 240 ms **8/8**、0 违约；C 180 ms serial **4/8**（两遍合计 8/16，8 个周期违约）；D 180 ms boundary **8/8**（两遍合计 16/16）；两遍为同进程顺序测量，非独立重复|
|刷新|四条件 4/4，就绪 198.10–198.61 ms；`k` 观测按冻结统计记录|
|时间口径|周期响应 = **Host 释放时刻 → 完成确认上界**（非 Event 包络）；GPU Event 区间与 Host 提交/确认分列；n=8 时 p99=p99.9=样本最大值（A/C ≈183.4–184.2 ms；B/D ≈138.7–139.5 ms），不作尾部证据/WCET|
|工作与留存|计时 64E/32C，全批 52C/70E；观察账本 13,400 行；bank 487,320,064 B（GPU+pinned 各一份）；冻结配置声明的磁盘预算与 12 GiB 准入不变；D1 仅数值准入，版本/留存/工作量/安全检查仍分别通过|
|硬件|真实 snapshot；清理后代后逆序恢复；`restored=true`（80 样本）；独立读回 PASS（cpu 729600×3、GPU 306000000、EMC 204000000）；无残留进程|
|证据|`reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/gpu_run_01/`：RUN_REPORT.md、board/run_01（191 文件）、BACKUP_VERIFICATION.json|
|未覆盖|长尾、违约率数量级、k_min、最终路线不声称；受控干扰与干扰条件化余量为后续研究；单段 8 周期、两遍非独立|
|停止|批次一次完成即停止；未追加段/预热/探针、未调预算或相位、未重试；B2 仍候选，未定线、未进入 M4|

## 历史：2026-10-21 边界优先 180/240 ms 两锚点准备（PREPARED，随后获批执行）


|项目|方案事实与边界|
|---|---|
|条件|A `240/serial`、B `240/boundary`、C `180/serial`、D `180/boundary`；共同 `two_9_9`（隔离优先策略，非最终切分）|
|轨迹|8 段 `A,B,C,D,D,C,B,A`，各 8 周期/4 刷新；相位 +15 ms；刷新按原始周期时钟；不扫相位/不改预算/无干扰|
|驱动|每段 manifest 自带 P=D、释放与 deadline；`run_candidates` 新增 per-segment `confs`（向后兼容）；policy 由候选驱动；段级协议取自 manifest 并与 CONFIG 核对|
|工作量|52C/70E（含 2 预热、D1 1C+1E、gate 2×2C+1E、8 bootstrap、计时 32C+64E）；观察账本 13,400 行；Autotune 36 另账|
|预算|每段留存 64/487,320,064 B；bank 487,320,064；GPU+pinned 974,640,128；payload 3,898,560,512；gate 248,242,944；磁盘估算 5.27 GiB；准入 12 GiB；轨迹 13.44 s|
|CPU 核验|`validate_m3_b5_cpu` 8/8 PASS（四条件/顺序、180/240 释放与 deadline、相位只移 Expert、8 段 per-segment 驱动、失败归属、控制器令牌）；历史仓库8套/包内5套证据复用，本轮未重跑，`validate_m2_clean_cpu` 缺仓库依赖不可运行（不记 PASS）|
|冻结|`reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/deployment/` 40 文件、`DEPLOY_SHA256.txt` `d676c083…`、`CONFIG.json` `55e7cfa1…`、dry-run 退出 0；历史包与原始数据 SHA 未改|
|未覆盖|长尾、违约率数量级、`k_min`、最终路线；受控干扰/干扰条件化余量为后续研究；180 ms 未校准（M1 用过不代表本执行器通过）|
|修订|gate统一GATE_PLAN=THREE，每gate15条/124,121,472 B；磁盘估算5,653,281,189 B；成功状态PASS_IN_PROCESS_BOUNDARY_BUDGET_ANCHORS；新增预算契约回归与CPU入口哨兵通过；旧v1包保留|
|停止|准备完成即停止：不启动模型、不部署、不写硬件、不提交 scope；等待新的明确 GPU 与硬件批准|

## 历史：2026-10-21 两锚点准备 v1（预算与元数据由r1修正，未执行）

|项目|方案事实与边界|
|---|---|
|条件|A `240/serial`、B `240/boundary`、C `180/serial`、D `180/boundary`；共同 `two_9_9`（隔离优先策略，非最终切分）|
|轨迹|8 段 `A,B,C,D,D,C,B,A`，各 8 周期/4 刷新；相位 +15 ms；刷新按原始周期时钟；不扫相位/不改预算/无干扰|
|驱动|每段 manifest 自带 P=D、释放与 deadline；`run_candidates` 新增 per-segment `confs`（向后兼容）；policy 由候选驱动；段级协议取自 manifest 并与 CONFIG 核对|
|工作量|52C/70E（含 2 预热、D1 1C+1E、gate 2×2C+1E、8 bootstrap、计时 32C+64E）；观察账本 13,400 行；Autotune 36 另账|
|预算|每段留存 64/487,320,064 B；bank 487,320,064；GPU+pinned 974,640,128；payload 3,898,560,512；gate 248,242,944；磁盘估算 5.21 GiB；准入 12 GiB；轨迹 13.44 s|
|CPU 核验|`validate_m3_b5_cpu` 7/7 PASS（四条件/顺序、180/240 释放与 deadline、相位只移 Expert、8 段 per-segment 驱动、失败归属、控制器令牌）；仓库 8 套全 OK；包内 5 套 OK，`validate_m2_clean_cpu` 缺仓库依赖不可运行（不记 PASS）|
|冻结|`reports/m3_b2/20261021/boundary_budget_anchors_v1/deployment/` 40 文件、`DEPLOY_SHA256.txt` `7d92dadb…`、`CONFIG.json` `dedce43a…`、dry-run 退出 0；历史包与原始数据 SHA 未改|
|未覆盖|长尾、违约率数量级、`k_min`、最终路线；受控干扰/干扰条件化余量为后续研究；180 ms 未校准（M1 用过不代表本执行器通过）|
|停止|准备完成即停止：不启动模型、不部署、不写硬件、不提交 scope；等待新的明确 GPU 与硬件批准|

## 历史：2026-10-21 单流时间关系与计划可行性（修订 r1，离线/CPU）


|项目|结论与边界|
|---|---|
|本轮权限|源码阅读/最小分析代码修改/CPU 核验/文档更新；模型 0、SSH 0、硬件写入 0、scope 0；执行器未改|
|版本生命周期|模型直接驱动冻结 `VersionedKV`（SHA `7890fa54…`）；覆盖 slot/generation、PUBLISHED/RETIRED、偶绑定+奇预留、读者完成、安全回收；负例：预留读者未完成拒收、retired 不可新绑定、回收后旧 Handle 报 stale generation|
|非法回收|`ILLEGAL_RECLAIM`：拒绝复用并保留完整分母（8 周期/4 刷新），记录 slot/version/readers；域内自然轨迹不产生非法回收（该探针需 φ>P 或人为 hold 未完成读者，模型如实标注）|
|支持域|`cycles` 正偶数、`0≤φ<P`、需时为正；审核探针 P=10/φ=15 被显式拒绝并说明范围|
|统计重建|`rebuild_stats.py` 从原始映射独立重建（冻结 `replay_stats`），逐作业比对 64 周期/32 刷新 0 mismatch；operations Event 交叉核对 0 issue；4/4 故障注入被发现；+1000 ms 探针使重建 +1000.0 ms 而 stored 不变|
|模型对照|四格偶数周期残差 −1.10～−1.30 ms（≤0.9%，未调参、未逐项隔离）；条件化串行和 139.583/140.056 ms，B/D 高出 0.9%/1.0%|
|b2_slack|P=180 算例：deadline 375/360，boundary 81.2/81.2（余量 98.8/159.4），延后 75.6/120.2（余量 59.8/44.8）；Expert −5.6、周期 +39.0、刷新余量 −114.6；整轨迹构造 Expert −19.9/周期 +100.2/发布 +175.4；两处均 0 违约（代价为完成点后移）|
|尾块覆盖|按 `block_plan.blocks` 取真实最后块（两块 `/B2`、三块 `/B3`），用该操作 `lower_ns/upper_ns` 判定；实测轨迹无释放落入尾块窗口——仅证明该覆盖事实，不泛化到任意 μ|
|措辞|删除过强结论与"+0.55 ms 在噪声内"；D2 为固定算法方案、Graph 可减提交开销，均非本轮实施项，未来通用优化须对基线对称开放|
|证据|`reports/m3_b2/20261021/plan_feasibility_v1_r1/`：REVISION/ANALYSIS/COUNTEREXAMPLES/NEXT_STEP/README、plan_model/rebuild_stats/scenarios/validate（19/19 PASS）、SCENARIOS/CPU_RESULTS/CPU_TESTS、MINIMAL_DIFF、EVIDENCE_INDEX|
|未覆盖|不声称净机制收益、干扰条件化计划或正式关键消融完成；模型不覆盖重叠/D2/Graph/义务重分配；CPU 通过≠GPU/WCET；B2 仍候选，不进 M4|

## 历史：2026-10-21 单流时间关系分析 v1（离线/CPU，存在已记录的分析缺口）


|项目|结论与边界|
|---|---|
|本轮权限|源码阅读/离线分析/新增分析脚本/CPU 核验；模型 0、SSH 0、硬件写入 0、scope 0；执行器未改|
|时间关系（条件化）|`r_j=jP+φ`（φ=15）、`R_m=2mP`；周期 j 义务 = Expert j（固定版本 `⌊j/2⌋`）+ 单元 `(j//2, j%2)`；两块 `((0,),(1,))`、三块 `((0,1),(2,))`；发布需被 retire 版本的偶数 consumer 已派发；周期响应 = max(Expert, 单元) − r_j，VLM 响应按 r_j 钳零|
|条件化和（推导）|偶数周期 ≥ 单元 + Expert − φ → 139.58（两块）/140.06（三块）；奇数 ≥ Expert 75.16；刷新 ≥ 199.17/199.64|
|实测对照|B 140.893（下界 +0.9%）、D 141.444（+1.0%）、A 185.565、C 186.214；奇数 75.14–75.46；刷新 200.59–201.23；64 周期/32 刷新零违约、k=1|
|模型|`plan_model.py`（分析专用）：单流、块不可抢占、合法边界、发布守卫、双槽 FIFO、安全回收、完整分母；输入仅实测包封（块/Expert total、stage、边界间隔 0.041、发布 0.012），残差 ≤1.3 ms，未调参、不作毫秒预测/WCET|
|只改 Expert 的排序|三块切分（边界下）：等待 65.3→16.2、Expert 完成 140.9→91.8 ms；周期 +0.55 ms（因和不变）|
|改完整周期的排序|boundary vs serial：A→B −44.67、C→D −44.77 ms；边界"块先"= serial（+44.6 ms）；空等直接计入|
|b2_slack|审阅算例：boundary 200.6/276.2 → 81.2/81.2；延后：270.6/315.2 → 75.6/120.2；Expert −5.6、周期 +39.0（deadline 435 内，说明"跨过释放点"≠"违约"）。整轨迹构造：Expert −19.9、周期 +100.2、发布 +175.4（逼近 480）。实测轨迹中该策略**不会触发**（无释放落在尾块窗口）|
|其它反例|人为空等 50 ms → 周期/发布各 +50；版本未就绪 → 周期 1050.96 ms FAIL；Expert 200 ms → 8/8 FAIL 且分母完整；版本永不就绪 → `NO_RUNNABLE_DEPENDENCY`、周期保持 INCOMPLETE|
|进度保底|基于 T̂ 的保底只在"实际 ≤ T̂"时成立，单次超时即破坏；deadline 约束完成而非推进；短测最大包封不是 WCET → 不能声称 100% 保证|
|决策|**A：当前无充分依据新增生产策略**；保留 `b2_boundary`；b2_slack 不实现；后续测量条件（负载紧、尾块跨越、多 Expert 排队、跨进程重复）列在 `NEXT_STEP.md`，均需新 GPU 批准|
|证据|`reports/m3_b2/20261021/plan_feasibility_v1/`：ANALYSIS.md、COUNTEREXAMPLES.md、NEXT_STEP.md、README.md、plan_model.py、scenarios.py、validate_plan_feasibility_cpu.py（13/13 PASS）、SCENARIOS.json、CPU_RESULTS.json、CPU_TESTS.log、MINIMAL_DIFF.patch、EVIDENCE_INDEX.json|
|未覆盖/不变|不声称净机制收益、干扰条件化计划或正式关键消融已完成；人工 gate 只证明分支覆盖；原始数据/冻结包/SHA 未改；B2 仍候选，不进入 M4|

## 历史：2026-10-21 切分 × 优先次序消融执行（RUN + PASS）


|项目|实测结果与边界|
|---|---|
|授权与执行|r2 唯一批次；APPROVED → RUN → PASS；1 普通 nvidia 模型（内部 170 s/外层 180 s+10 s）、1 五节点 scope（52.698 s<420 s）、零重试；`SCOPE_ATTEMPT_USED`/`MODEL_ATTEMPT_USED` 各 1|
|部署与凭据|新目录 `cooverlap_m3_b4_ablation_r2_20261021/`；36 文件 36/36 SHA OK；`PREFLIGHT.json` `e42cb0dd…`；此前 r1 的 argparse 拒绝尝试未消耗额度（已记录）|
|硬件|仅 5 节点 min 各一次写+回读；54 遥测样本 0 偏差；退出先清后代再逆序恢复；独立读回 PASS（cpu 729600×3、GPU 306000000、EMC 204000000，governors/MAXN 未变）；无残留进程|
|八段结果|A(two,serial) 偶周期 185.56 ms；B(two,boundary) **140.89**；C(three,serial) 186.21；D(three,boundary) **141.44**；奇周期四组 75.14–75.46 ms；刷新就绪 200.59–201.23 ms，k=1|
|Expert 侧|偶 Expert 等待：A 110.04、B 65.32、C 110.53、**D 16.16** ms；偶 Expert 完成：A 185.56、B 140.89、C 186.21、**D 91.77** ms；奇 Expert 立即派发 0.08–0.10 ms|
|对照结论|优先次序（A→B、C→D）周期响应各 −44.67/−44.77 ms；切分在 boundary 下 Expert 等待 −49.2、完成 −49.1 ms，但周期响应实测 +0.55 ms；serial 下实测 +0.65 ms；未建立噪声范围、显著性或等价性|
|机制解释|B 偶数 Expert/VLM 义务/周期响应 140.893/65.286/140.893 ms，Expert-bound；D 为 91.772/141.444/141.444 ms，VLM-bound。偶数义务为 P+Encoder0–8，不含尾块；尾块属于下一义务单元|
|完成与发布|A/C 尾块完成 Event 的 Host 确认约 124.995/125.493 ms，KV 发布上界约 200.587/201.234 ms；确认后至发布 Host 间隔约 75.592/75.741 ms（含发布依赖下的 Expert 服务），不全算 Context 计算或恢复开销|
|义务与违约|64 周期全部 PASS（0 FAIL/UNCERTAIN/INCOMPLETE）、32 刷新全部 PASS；W 分配/完成 8/8 每段；backlog 峰值 1；FIFO 刷新 ID 0,1,2,3，对应新版本 1,2,3,4（bootstrap 0）|
|覆盖|32/32 偶 Expert 在块边界派发（无中途抢占）；`serial_context` 每段 4 次待发布推迟、共 16 次，全部由已释放偶 Expert 解除（r2 解阻规则首次实机系统性触发）；boundary 0 次推迟；未出现多 Expert 排队或版本依赖等待|
|数值|D1 五项逐字节 exact；三块装配与两槽前缀参考全 exact；**autotune 落在 config X**（S0 `0c63ddfb…/8b95b48f…/3abed8cf…`，`matches_frozen_context=false`），S1 与 H 相同；跨进程 S0 raw 0.16796875/actions 0.052676 超包封、S1 0.0/0.0，`within_historical_envelope=false`，**仅报告**|
|账本与留存|13,400 行（49/49/882/12,420）与冻结声明一致；8 段 64/64/76/76/76/76/64/64 claims；gate 22/24 条；bank 597,617,152 B|
|证据|`reports/m3_b2/20261021/split_priority_ablation_v1_r2/gpu_run_01/`：RUN_REPORT、CORRECTNESS、COSTS、COVERAGE、offline/METRICS·CELLS·BLOCK_COSTS、board/run_01 可读范围 191 文件、BACKUP_VERIFICATION（原记录 191/191 SHA 一致）；root 快照内容未归档、仅元数据；journal 现有导出 0 行，特权只读可取性未核实，不能认定永久丢失|
|未覆盖|长尾/违约率比较/`k_min`/净收益/最终切分不声称（240 ms 下四组均零违约，只报观测计数及本批完成时间上界，不给出总体违约率置信上界）；每格每遍 4 刷新、两遍非独立；固定 +15 ms 相位不扫描；未实施 D2；Vision 内部与投影组细分未做|
|离线勘误|2026-10-21 本地重算 64 周期/32 刷新，修正关键路径、时钟分列、边界间隙与归档范围；255 checks/有限 PASS 保留。见本批 OBSERVATION_NOTES.md 与 corrections/REPORT_CORRECTIONS.json；原始 191 文件及冻结 36 文件 SHA 未改，本轮模型/SSH/硬件写入/scope 均 0|
|停止|本批一次完成即停止；未追加段/探针/预热、未改预算/相位、未重跑；B2 仍为候选，未自动定线、未进入 M4|

## 历史：2026-10-21 切分 × 优先次序消融准备（r2，PREPARED，随后获批执行）


|项目|准备事实与边界|
|---|---|
|执行尝试记录|r1 获批后 submit 一次，argparse 拒绝（`unrecognized arguments: --approved-m3-b4-split-priority-ablation-v1`）；无 scope/模型/硬件写入，一次性标记均未创建，额度未消耗；未重试、未临时修改后运行|
|r2 修正|控制器 argparse 与审批闸门改用本批 B4 开关（2 行）；新增控制器 CLI 回归 3 项 + 内部一致性断言；模型入口、凭据校验路径、scope 命令、unit 名均未变|
|四组设计|A `two_9_9+serial_context`、B `two_9_9+b2_boundary`、C `three_prefix_9_9+serial_context`、D `three_prefix_9_9+b2_boundary`；8 段 A,B,C,D,D,C,B,A 各 8 周期/4 刷新；仅 plan 与 policy 不同|
|工作量|全批 **52C/70E**（含 2 预热与 D1 的 1C+1E）；观察账本 **49C/69E = 13,400 行**；Autotune 36 请求另账|
|资源|bank **597,617,152 B**（GPU+pinned 各一份）；8 段 payload 4,339,748,864 B；磁盘分项二进制 5,087,214,824 B、估算 6,259,915,173 B（≈5.83 GiB）、**准入 12 GiB**；计时段轨迹 15.36 s；内部 170 s/外层 180 s+10 s/scope 415 s<420 s；1 模型 0 重试|
|CPU 核验|仓库环境 **7 套 142 项全 PASS**：`validate_m3_b4_cpu` **23**（四组/策略/队列/8 段/失败归属 13 + 真实入口凭据 5 + 磁盘与 12 GiB 2 + **控制器 CLI 3**）、b3 25/10/7、M2 23/25/29；部署包环境 4 套 65 项 PASS；公平性 PASS|
|冻结|`split_priority_ablation_v1_r2/`：36 文件、`DEPLOY_SHA256.txt` `e166a4f0…` 全匹配、`CONFIG==protocol()`（17,457 B，`ba2a8ad7…`，与 r1 相同）、入口 dry-run 退出 0、`MINIMAL_DIFF.patch` 对 r1 可应用（2 文件 2 行）；r1/v1 与全部历史证据原样保留|
|下一批|PREPARED、NOT APPROVED、NOT RUN：`split_priority_ablation_v1_r2/GPU_PLAN.md` + `APPROVAL_CHECKLIST.md`；需新的明确批准与新的 CPU 预检凭据（r1 批准与旧凭据均失效）|
|停止|准备完成即停止：不启动模型、不部署、不写硬件、不提交 scope|

## 历史：2026-10-21 切分 × 优先次序消融准备（r1，PREPARED，已被 r2 取代）

|项目|准备事实与边界|
|---|---|
|本轮权限|源码阅读/最小修改/CPU/离线/方案；模型 0、SSH 部署 0、硬件写入 0、scope 0；未复用任何一次性授权或 r2 预检凭据|
|四组设计|A `two_9_9+serial_context`、B `two_9_9+b2_boundary`、C `three_prefix_9_9+serial_context`、D `three_prefix_9_9+b2_boundary`；A/B、C/D 比优先次序，A/C、B/D 比额外切分，(A−B) vs (C−D) 看交互|
|唯一差异|仅 block plan（2 vs 3 个合法切点）与 Expert 决策策略；manifest/输入/噪声/checkpoint/BF16/消费规则 `v=floor(id/2)`/偶绑定预留奇/FIFO/释放与 deadline/义务组/完整工作/留存规则全部共享并由公平性脚本断言|
|serial 语义|与 boundary 相同的块、fence、D2D 留存与发布路径，只在 Context 计算期间不插入 Expert；保留 r2 解阻规则（全部块完成、只等发布时允许**已释放** Expert 解除依赖），不提前执行未释放 Expert|
|配置驱动|`CudaDevice.run_math` 由候选 plan 决定块与期望调用；`run_candidates` 用 `candidate['policy']` 驱动策略、用 manifest 的 `cycles` 计算留存/义务单元，并逐段断言 `mode==policy`、`block_plan.id==plan`、`protocol==manifest.schema`|
|协议记录|`run_segment` 段级 `protocol` 取自本批 manifest `schema` 并与 `expect` 声明核对；入口再断言 8 段协议等于冻结 `CONFIG.json`；r2 原始 `m3_b2_boundary_profile_v1` 字段与观察说明保持原样|
|段与顺序|8 段：`p1_A,p1_B,p1_C,p1_D,p2_D,p2_C,p2_B,p2_A`（两遍相反顺序控制位置效应）；每段 8 周期/4 刷新；段前恢复同一物理/逻辑初态并排空；同进程、同一 autotune、不重建模型|
|工作量|全批 **52 Context / 70 Expert10**（含 2 预热与 D1 的 1C+1E）；观察账本 **49C/69E = 13,400 行**（language 49/vision27 49/encoder 882/decoder 12,420）；Autotune 36 请求另账；每段调用计数固定 5/5/90/1440|
|资源|每段留存 64/76 entry（487,320,064/597,617,152 B）；bank **597,617,152 B**，GPU+pinned **1,195,234,304 B**；8 段 payload 4,339,748,864 B；两 gate 各 124,121,472 B；**磁盘分项**：留存 4,587,991,808 + 10 标签初态 252,764,160 + 10 标签 bootstrap 126,382,080 + 固定二进制 120,076,776 = **二进制 5,087,214,824 B**，加 JSON/CSV/日志 4,000,000、临时 599,617,152、10% 余量 = **估算 6,259,915,173 B ≈ 5.83 GiB**；**准入门槛 12 GiB**（实际代码路径）；计时段轨迹 15.36 s；内部 170 s/外层 180 s+10 s/scope 415 s<420 s；1 模型 0 重试|
|指标|Expert 等待（释放→派发决策）、Expert 响应（释放→完成）、周期响应（含同一完整 VLM 义务组）、刷新就绪（释放→完整 KV 发布）；违约/分母、W 推进、积压、未完成、不确定；Host 决策/完成确认/GPU Event 分列；Event 是含空隙与插桩的包络，不称纯 Kernel|
|CPU 核验|仓库环境 **7 套 139 项全 PASS**：`validate_m3_b4_cpu` **20**（四组/策略分流/无 Expert 连续/队列与版本等待/FIFO/8 段唯一 ID/中间段失败归属/窗口无侵入 13 项 + **真实入口凭据 5 项** + **磁盘分项与 12 GiB 门槛 2 项**）、b3 25/10/7、M2 23/25/29；部署包环境 4 套 62 项 PASS，`validate_m2_clean_cpu` 包内缺依赖不记 PASS（`TEST_ENVIRONMENT.md`）；公平性 PASS|
|冻结|`reports/m3_b2/20261021/split_priority_ablation_v1_r1/`：36 文件、`DEPLOY_SHA256.txt` `1cf6553b…` 全匹配、`CONFIG==protocol()`（17,457 B，`ba2a8ad7…`）、入口 dry-run 退出 0（协议内 disk 12 GiB/估算 5.83 GiB）、`MINIMAL_DIFF.patch` 对 v1 可应用（3 文件）；v1 与 r1/r2/v1 历史包原样保留|
|未覆盖|无 GPU 数据：四组数值、周期/刷新/违约差异、交互结论均 NOT_RUN；不支持长尾、违约率数量级、`k_min`、净收益或最终切分；固定 +15 ms 相位不扫描；无跨进程独立重复|
|下一批|PREPARED、NOT APPROVED、NOT RUN：`split_priority_ablation_v1_r1/GPU_PLAN.md` + `APPROVAL_CHECKLIST.md`（1 普通模型 + 1 五节点 scope、0 重试、36 文件 SHA、12 GiB 准入、命令与停止条件齐全）|
|停止|准备完成即停止：不启动模型、不部署、不写硬件、不提交 scope；需新的明确批准|

## 历史：2026-10-20 M3 三块唯一批实际结果（r2，RUN + PASS）

|项目|实测结果与边界|
|---|---|
|授权与执行|用户批准 r2 唯一批次；APPROVED → RUN → PASS；1 普通 nvidia 模型（内部 170 s/外层 180 s+10 s）、1 五节点 scope（21.632 s<420 s）、零重试；`SCOPE_ATTEMPT_USED`/`MODEL_ATTEMPT_USED` 各 1|
|部署与凭据|新目录 `/home/nvidia/rtvla/cooverlap_m3_b3_20261021/`；r2 冻结包 31 文件 `sha256sum -c` 31/31 OK；`PREFLIGHT.json` SHA `931047d2…`（CPU_PREFLIGHT_PASS，未 import CUDA/未写硬件）|
|硬件|仅 5 节点 min：CPU policy0/4/8 2201600、GPU 1300500000、EMC 3199000000，冻结代码各一次写+有界回读（逐节点原journal已补取并逐条核对）；scope 内遥测 23 样本、**0 偏差**、温度 46.9→51.1 °C、`MemAvailable` 最低 42.9 GB；退出先清后代进程再恢复；独立读回 PASS（uid 1001，cpu 729600×3、GPU 306000000、EMC 204000000，governors/MAXN 未变）；残留进程 0|
|结果|`model/result.json` `PASS_IN_PROCESS_THREE_BLOCK_COVERAGE`，151 checks/0 failed（72 个不同检查名）；`SCOPE_RESULT.json` PASS/`restored=true`/`samples=23`|
|数值|D1 同进程 `context_x/K/V/raw/actions` 全部逐字节 exact；冻结配置 `H_frozen`（S0 `ea62dc72…/7ff20f0d…/4357374f…` 与历史记录一致，S1 完整 SHA 另记）；三块装配 prefix/mid/full/raw/actions 全部 exact；两槽完整前缀参考 `complete_context=true`；跨进程仅报告（raw 0.015625/0.015625、actions 0.0078017116/0.0078017712，阈值未放宽、未筛配置/重启）|
|观察账本|`language 15 / vision27 15 / encoder 270 / decoder 2340 = 2640` 行，与冻结声明一致；分段核对：bootstrap 2C、参考 2C+2E、前缀参考 2C、装配 1C+1E、gate 2×(2C+1E)、两段 4C+8E|
|留存|control 段 32 条/243,660,032 B；three 段 38 条/298,808,576 B；两 gate 各 15 条/124,121,472 B；均经全量 D2H+逐字节比较+落盘 fsync 后 `mark_verified` 再释放 bank；正常窗口内无 D2H/比较/SHA/写盘；`RETENTION_INDEX.json` 的 `segment_id` 与四段目录一致|
|块与控制成本|control：B1 math 78.553/78.823 ms、B2 43.702/43.959 ms；three：P 29.870/29.757、B1 48.749/49.081、B2 43.711/44.132 ms；pre D2D 0.212–0.237 ms、post 留存 0.224–0.406 ms；stage R0 0.554 ms/R1 0.035 ms；Expert math 74.35–78.86 ms；刷新就绪上界 control 204.276/200.550 ms、three 202.513/201.068 ms|
|自然调度覆盖|8 次 Expert 派发全部可解释：4 次“块执行中到达→块结束边界派发”（边界间隙 0.038–0.060 ms）、4 次“空闲到达→立即派发”（0.112–0.172 ms）；**块中途派发 0 次**；每段 4 次真实空闲等待、版本等待 0、backlog 峰值 1；发布守卫本批未触发（0/4）|
|统计口径|每段 4 周期/2 刷新全执行：`cycle_counts` 4/4 PASS、`refresh_counts` 2/2 PASS、`longest_consecutive_definite_miss=0`、`W_assigned_on_time=4`、`W_completed_in_window=4`；`p99=p999=144.8/142.9 ms` 仅为 4 样本最大值（非尾部分布），`k_upper=1`、`k_min` 不估计|
|未覆盖|长尾/违约率比较/`k_min`/净收益/最终切分不声称；`serial_context` 未在本批运行（仅 CPU 回归）；未出现两 Expert 同时排队或发布守卫真正推迟；固定 +15 ms 相位不扫描；未实施 D2；Vision 内部与投影组细分未做；原普通用户未取得的root快照及服务journal现已通过交互sudo只读补档|
|证据与备份|`reports/m3_b2/20261020/three_block_v1_r2/gpu_run_01/`：RUN_REPORT.md、CORRECTNESS.md、COSTS.md、COVERAGE.md、offline/SUMMARY.json、offline/BLOCK_COSTS.csv、offline/COVERAGE.json、board/run_01 普通用户可读原始文件（原107个）；root快照补充归档、108源文件联合SHA清单及服务journal见closeout/、BACKUP_VERIFICATION.json（107/107 SHA 一致）|
|收口勘误|成本对照列、Event包络和stage复制量解释已修正；旧段级protocol字段保持原值并另记effective_protocol；见OBSERVATION_NOTES.md与closeout/CLOSEOUT_REPORT.md|
|归档状态|107个可读文件已与本次板端完整SHA清单核对；COMPLETE_108_SOURCE_FILES，108源文件/1,063,439,813 B无缺失及SHA不一致；apply/restore各5次、10次读回已由journal实核；本轮新增模型/硬件写入/scope均0|
|停止|本批一次完成即停止；未追加段/探针、未重跑、未扩时；B2 仍为候选，不宣称收益，不自动进入 M4|

## 历史：2026-10-20 三块候选准备（r1/r2，PREPARED，未执行）

|项目|当时事实与边界（准备阶段，未执行）|
|---|---|
|本轮权限与实际操作|仅源码/最小实现/CPU/离线分析/方案准备；模型 0、硬件写入 0、scope 0、未 SSH 部署；未复用任何一次性授权|
|三块语义|P（前缀）后有效**新** KV=0、留存只有 x（2,297,856 B）；Encoder0–8 后=9；Encoder9–17 后=18；`publish()` 显式拒绝非 18 层，前缀状态永不发布；旧代残留 KV 不被当作新 KV|
|配置化|`m2_executor.BlockPlan` + `Version.valid_layers` + 按 plan 的 `check_block/poll_block/publish`/`retention_layout(cycles,plan)`/`capture('prefix')`/`run_math(block_math)`/`audit_and_persist`；默认仍为 `two_9_9`（两块），两块布局与已归档批次逐字节一致（32 entry/243,660,032 B）|
|新源码|`m3_b3_plan.py`（计划/相位/预算/协议）、`pi05_m3_b3_prepare.py`（PREPARED 入口）、`m3_b3_control.py`（PREPARED 一次性控制）、`validate_m3_b3_cpu.py`、`check_m3_b3_fairness.py`；`m2_pi05_ops.prefix_block/encoder_block`（调用序列经 mock 逐参比对等于 `block1` 前缀）|
|正确性修补|CPU 复现“刷新在偶 Expert 未派发时发布 → retires 未执行版本 → 回收后引用失效”；已加发布前版本保留守卫（记录 `publication_deferred`），真实协议下不触发，不改变已归档语义|
|公平性|两候选同一 manifest/binding/相位/版本轨迹/释放与 deadline/完整工作量；仅切分不同；留存规则按块对称；`FAIRNESS_CHECK.json` PASS|
|数值口径|D1 同进程逐字节准入（沿用 M2 实际源码 AST）；**新增前缀边界有同进程参考**（两块 `block1` 层 0 入口只读钩子）并要求三块装配 prefix/mid/full/raw/actions 全 exact；跨进程 0.015625/0.01 仅报告，不筛 H_frozen|
|新预算|**全批 18 Context/14 Expert10**（含 2 丢弃预热与 D1 的 1C+1E）；**观察账本 15C/13E = 2640 行**（15×20+13×180）；每段留存 38 entry/298,808,576 B（三块）与 32/243,660,032 B（两块），bank 取最大 298,808,576 B（GPU+pinned 597,617,152 B），payload 542,468,608 B，gate 各 124,121,472 B；预计模型段 20–25 s，硬边界 170/180 s、scope 415 s<420 s|
|修订 r1|前缀参考现为完整 Context（B1→B2 并逐字节核验 full）；gate journal 逐条核对 22/24（被拒发布/回收不产生条目）；`SEGMENT_IDS` 贯穿账本键、`RETENTION_INDEX.json`、报告与 `out/<segment_id>/`；新增 `m3_b3_orchestrate.py` 与入口回归|
|修订 r2|①两块对照真实账本：`expected_calls(work)` 按 plan 生成观测期望（两块 B1=language+vision27+encoder0–8；三块 P 无 encoder；尾块 9–17；Expert 完整 10×18），不再把 norm/project/bias 当 encoder；新增 `validate_m3_b3_adapter_cpu.py` 7/7（真实 `run_math`+真实 `CallLedger`，含漏算/重复/错槽负例）。②失败归属：`mark_active`/`describe_active`/`export_failed_retention`+`RetentionLedger.status()`，异常收尾只指向实际活动段或 gate，只在截止时间内且 bank 安全时导出，状态只可能 `EXPORTED_UNVERIFIED_NOT_REUSABLE`/`NOT_EXPORTED_*`。③`serial_context`：仅“全部块完成、只等发布”时允许已释放偶 Expert 解除依赖，Context 执行仍不可中断；两策略均完整排空、到达/deadline/分母不变。预算未变|
|预声明相位|φ=+15 ms 只作用于 Expert 释放（deadline 保持 release+P，刷新释放不变）；目的是让首个 Expert 在前缀块执行期间到达，由真实时钟触发边界优先；单一相位、不扫描、两候选一致|
|CPU 核验|**仓库环境 6 套 119 项全 PASS**：`validate_m3_b3_adapter_cpu` 7、`validate_m3_b3_cpu` 25、`validate_m3_b3_entry_cpu` 10、`validate_m2_cpu` 23、`validate_m2_clean_cpu` 25、`validate_m3_b2_cpu` 29；**部署包环境 3 套 42 项 PASS**，`validate_m2_clean_cpu` 在包内缺仓库独有模块**不可运行、不记 PASS**（见 `TEST_ENVIRONMENT.md`）；r2 包 **31 文件** SHA 自洽且 `CONFIG==protocol()`；入口 dry-run 退出 0；r1 与更早冻结包保留不变|
|下一批|PREPARED、NOT APPROVED、NOT RUN：`reports/m3_b2/20261020/three_block_v1_r2/GPU_PLAN.md` + `APPROVAL_CHECKLIST.md`（1 普通模型 + 1 五节点 scope、0 重试、31 文件 SHA、命令与停止条件齐全；预算与 r1 相同）|
|未覆盖|三块 GPU 数值/边界成本/真实时钟驱动的优先覆盖 = NOT_RUN；长尾/k_min/净收益/最终切分不声称；Vision 内部与投影组细分未做|
|停止|本轮准备完成即停止：不启动模型、不写硬件、不运行 scope；下一批需新的明确批准|

交付：原冻结包 `reports/m3_b2/20261020/three_block_v1/` 与 `three_block_v1_r1/` 均保留不覆盖；**当前修订包 `reports/m3_b2/20261020/three_block_v1_r2/`**（REVISION.md、DESIGN.md、MINIMAL_DIFF.patch、GPU_PLAN.md、ACCEPTANCE.md、APPROVAL_CHECKLIST.md、TEST_ENVIRONMENT.md、CPU/ENTRY/ADAPTER 结果与日志、CPU_REPO/CPU_BUNDLE 日志、FAIRNESS_CHECK.json、deployment/ 31 文件）。

## 历史：2026-10-20 M3 唯一批实际结果（boundary_profile_v1，已执行）

|项目|实际结果与限制|
|---|---|
|授权与执行|APPROVED/RUN/PASS（有限数值/版本/顺序profiling）；1普通nvidia模型、1五min scope，180s+10s grace/内部170s/420s额度内；只提交一次，无追加工作或实验重试|
|完整计算|15 Context/13 Expert10，270 Encoder/2340 Decoder/405 Vision层；原固定2预热C、参考/D1、两gate及bootstrap均计入；36 Autotune请求（288候选条目）另账，内部Matmul/算法ID未直接取得|
|观察账本|2400=216 Encoder+2160 Decoder+12 language+12 Vision27；另列预热2C、原pipeline D1 1C1E，不把账本当全部工作|
|数值|D1同进程同槽S0原pipeline vs完整Context+Expert五类保存字节exact；两个槽新块/刷新/Expert对各自完整参考全部exact；114条内部检查记录0失败|
|配置漂移|H_frozen仅原Context标签，S0/S1 Context均匹配冻结SHA；不代表全链算法身份。跨进程仅报告S0/S1 raw0.0078125/0.015625、actions0.007801711559/0.007801771164，阈值不变、未筛配置/重启|
|留存与stage|GPU/pinned Host各243660032B；88entry、10留存Expert全量exact，payload680414464B；28操作含6stage均有真实tail Event首次true/独立确认与Host完成字段；M2旧false不变|
|人工接续/版本|旧读者gate journal18；B1→旧槽Expert→B2及hold跨发布gate journal20；mid/full/旧KV/输入/代次/完整发布/安全回收通过，人工gate与自然覆盖分开|
|C0/C1短段|各4周期/2刷新，P=D240ms、同输入/噪声/版本vq/释放/deadline/观测；各周期/Expert/VLM义务4/4、刷新2/2、违约0/4、UNCERTAIN/INCOMPLETE0；周期0保留、最终积压0|
|响应及解释|C0/C1周期样本最大156.177/155.089ms，刷新198.675–200.843/199.508–199.773ms，观测k均1；n4不支持长尾/k_min/净收益。C0保留对称中间fence，不替代M2已验收基线|
|自然覆盖|8次Expert释放均未落在Context块内，无版本等待/较早Expert未完成场景；边界阻塞/版本等待/多Expert排队NOT_OBSERVED，不填成零ms，不改相位补测|
|块实测|窗口n4：Vision29.555–29.994ms，投影组0.152032–0.154784ms，Encoder0–8/9–17为48.847–49.050/43.818–43.955ms，Context Event123.075–123.775ms；含插桩/提交空隙，非纯Kernel|
|Host控制|B1回执→B2决策9.313–11.745µs，→B2数学提交130.147–134.306µs，publish5.600–7.904µs；约65ms轮询等待还含GPU剩余计算，不能叫恢复成本；gate校验间隔另列|
|硬件/清理|5apply+5restore、10读回；真实snapshot恢复，独立uid1001 min/max/governor/MAXN一致，无残留/service已collect；21采样（20model）全五域目标，两窗口各1点，采样最高50.437°C；未取得独立GPU/模型内存峰值|
|备份与离线|122清单文件886403765B全SHA匹配，加清单123文件886425950B；root600 snapshot等SHA导出；独立离线1007检查记录0失败，逐字节/账本/journal/统计/恢复复核；214既有文件及22部署Python未变|
|下一步仅建议|优先前缀独立+Encoder0–8/9–17三块的状态/留存集成及CPU验证；约30/49/44ms只是分项依据，新边界与额外成本尚未验收，Vision仍不可中断；不把9+9或新三块定为最终|
|停止|唯一额度已用完，实际报告/全量备份/恢复交付后停止；不追加GPU、不自动选线、不进入M4，不重开M1/历史根因；D1沿用、D2不实施、不加前置|

实际报告：`reports/m3_b2/20261020/boundary_profile_v1/gpu_run_01/RUN_REPORT.md`；块/控制成本、未覆盖项及下一步切分建议同目录；原始数据在`board/`，离线1007检查及逐项CSV在`offline/`。M2阶段基线与历史FAIL/INCOMPLETE/UNKNOWN保持原样。收尾有一次只读导出脚本传输审批超时及一次SCP连接关闭，恢复仅文件传输，未重试模型/scope。

## 历史：M3候选准备交付时顶部（2026-10-20，随后获批执行）

当时更新时间：2026-10-20
当时阶段：**M3 B2候选机制准备已完成；CPU 29/29 PASS；GPU NOT APPROVED / NOT RUN**。M2 clean_serial_v1在约定范围内验收通过，不追加回放。B2仍试选/候选，最终定线未确认；M3收益尚未验收，不进入M4。

## 历史：M3候选准备状态表（2026-10-20）

|项目|当前事实与边界|
|---|---|
|本轮权限与实际操作|仅源码/最小实现/CPU/离线分析/方案准备；模型启动0、硬件写入0、scope0，未SSH部署或触碰板端|
|M2结论|阶段串行基线PASS；带对称D2D、无逐单元D2H/比较/写盘；240ms两模式均0违约，不能证明B2收益；resumed更晚包含等下一释放的计划空档，不把全部差值算恢复成本；n16不支持可靠长尾/k_min|
|独立协议|m3_b2_boundary_profile_v1：固定到达/FIFO、已释放可运行Expert边界优先，无Expert立即推进；单Stream、在途深度1，真实fence后决策；版本未就绪保留原到达并推进依赖|
|版本公平性|两策略同输入/噪声/完整工作/P240/2P刷新/预定vq；偶Expert首次执行绑定并预留奇Expert同v，预留不提前执行；原版本机/数学/统计不改|
|完成字段修复|仅新BoundaryBackend/ProfileDevice：stage也实际等待/查询新tail Event；GPU完成观测Host时刻/保守区间与Host完成上下界分列；M2旧33条false/原数据/限制说明不改、不补跑|
|切分候选|C0完整Context决策控制、C1现有9+9边界，共2个；不把9+9定为最终；其他位置待测；不可抢占Vision/投影及整个首块纳入最大阻塞|
|已有测量整理|M2 B1/B2 math中位约78.82–78.90/43.89–43.95ms；历史v7完整前缀约30.09ms，含Vision/投影；不做跨协议差值或按层数均分，Vision/投影单项/细组/调度待测|
|CPU与冻结|29项0失败；CONFIG dry-run、30清单项SHA/22 Python语法通过；CPU只证明符号逻辑，未证明新GPU数值/性能|
|新源码|m3_b2_core/backend/profile、m3_m2_preparation、pi05_m3_b2_profile、m3_b2_control、validate_m3_b2_cpu；原M2/M1脚本/执行快照/数学不改，D1准备72条原AST由实际源码SHA锁定复用|
|唯一下一批计划|PREPARED：1普通模型180s+10s grace、内部170s、0重试；1新五min scope≤420s；两个4周期/2刷新短profiling，窗口8E/4C，完整15C/13E+36 Autotune请求；不扫描/长跑/三重复/Graph|
|留存预算|GPU/pinned Host各243660032B；两段+两gate88entry，payload680414464B；覆盖前D2D、窗口后全量核验/持久化才复用；所有必要机制/对称细Event费用计入|
|数值口径|D1同进程逐字节严格准入；跨进程0.015625/0.01仅报告配置漂移，记录各槽SHA/Autotune，不筛H_frozen、不重试；D2不实施、不作前置|
|停止与后续|本轮准备已交付并停止；新模型/硬件/scope未授权、未执行；不宣称B2收益或M3净机制PASS，不进入M4，不重开M1/历史根因|

交付：`reports/m3_b2/20261020/boundary_profile_v1/PREPARATION_REPORT.md`、`PROTOCOL.md`、`SPLIT_EVIDENCE.md`、`GPU_PLAN.md`、`RESULT_TEMPLATE.md`、CPU/配置/冻结/保全核验与`MINIMAL_DIFF.patch`。M2原实际报告和全部历史FAIL/INCOMPLETE/UNKNOWN保持原样。

## 历史：M2 clean_serial_v1交付时顶部（2026-10-20）

当时更新时间：2026-10-20
当时阶段：**M2有限正确性已通过，阶段干净公平串行基线已取得**。用户批准的clean_serial_v1唯一批APPROVED/RUN/PASS：1普通nvidia模型44.049s、1个五min scope46.451s，模型/scope0重试；ABBA四段各16周期/8刷新全部完成，各0/16周期违约；D1、全量数值/版本/工作量、冻结离线审核及原始SHA备份均通过。自动恢复、独立读回及无残留核验PASS。本批已交付并停止，B2保持试选，未进入M3。
主研究路线：B2试选，最终定线未确认；不宣称B2收益。M1除用户延期的路线选择外可执行项已收口，全部历史FAIL/INCOMPLETE/UNKNOWN保留；D1沿用，D2不实施也不作为M3前置。

## 历史：M2交付状态表（2026-10-20）

| 项目 | 当前 |
|---|---|
| 阶段结论 | M2有限正确性/版本/合法块/回放机制及本次阶段公平串行基线PASS；不是最终优化尽的论文串行基线、可靠长尾或B2收益证据 |
| 最新GPU批 | `reports/m2_common/20261020/clean_serial_v1/gpu_run_01/`：唯一模型/唯一scope、0实验重试，四段全部完成；原M2 v3 `gpu_run_05`正确性PASS保留 |
| 数值 | D1同进程同槽S0原pipeline vs完整Context+Expert拆分参考，x/K/V/raw/actions全部exact；本批两槽H_frozen_S0/S1，未配置筛选或重启 |
| 跨进程仅报告 | S0/S1 raw最大差0.015625，动作0.007801711559/0.007801771164，均在原0.015625/0.01包络；不等于其他配置都在包络内 |
| 完整工作 | 正式64E/32C；含预热/参考/D1/gate/bootstrap共68E/43C；主观察账本12860=720 Encoder+12060 Decoder+40 language+40 Vision27；两槽Autotune36请求另账 |
| 版本与留存 | gate18 journal、四段各109；4×128+gate12=524留存entry全exact，正式64个Expert动作全exact；GPU/pinned Host各974640128B，覆盖前D2D、窗口后全量核验/持久化才复用 |
| A1/B1/B2/A2周期 | Host完成区间上端的样本最大值分别152.074/151.219/151.752/151.716ms；每段16样本的nearest-rank p99=p99.9=样本最大值，不是总体尾延迟上界 |
| 刷新与推进 | A刷新194.924–196.493ms、观测k=1；B刷新355.496–356.594ms、观测k=2；各8/8按时、16单元/段全部推进、最终backlog0；k_min不计算 |
| 时限与分母 | 各段周期/Expert/VLM义务16/16、刷新8/8，FAIL/UNCERTAIN/INCOMPLETE均0，周期0保留；同240ms预算及固定消费/释放轨迹 |
| 计时口径 | 无逐单元D2H/比较/写盘，包含对称D2D留存及全部必要机制成本；不称零观测开销，不拿v3插桩时间作对比 |
| 采集字段限制 | 33条stage.completed保持默认false，缺独立Host回执；实际完成由同流fence/bank逐Event查询及全量输入字节校验支持；原值保留，详见OBSERVATION_NOTES，不当作未完成主作业或改写后补跑 |
| 硬件与安全 | 47条model阶段采样全部五域实际率符合目标、BPMP EMC=3199000000；各正式窗口4采样，最高50.468°C；5设置+5恢复、10读回成功；原min/max/governor/MAXN恢复并独立uid1001确认，无残留 |
| 备份与审核 | 136清单文件4240537217B全部SHA匹配，加清单共137文件4240571960B；root600原快照由等SHA副本保存；冻结CPU审核1076项0失败，本地统计重算一致；200个既有捕获文件SHA与15个冻结Python均不变 |
| 解释边界 | 一进程/一配置/四段短回放，非独立长运行；未取得算法身份，不外推历史根因；当前轨迹两模式均0违约，resumed刷新更晚，不宣称B2优势 |
| 执行边界 | 唯一额度已执行完并交付后停止；不自动优化、补跑、选线或进入M3。后续Graph等通用优化应向串行基线对称开放 |

本批实际报告：`reports/m2_common/20261020/clean_serial_v1/gpu_run_01/RUN_REPORT.md`；原始数据、逐段CSV、源/配置指纹、恢复与SHA核验同目录。准备包及原M2 v3/所有M1证据均保留。事后一次重复只读导出被noclobber拒绝、一次小文件备份SSH握手reset均单列采集记录，未增加模型/scope或工作段。

## 历史：干净公平串行基线准备（2026-10-20）

**PREPARED / NOT APPROVED / NOT RUN**。新入口`pi05_m2_clean.py`复用已通过v3的数学、D1、VersionedKV和原五min事务；正确性/正常回放共用一套调度。A/B/B/A各16周期/8刷新，P=D=240ms，固定消费版本，计时64E/32C；含固定预热、参考、D1、版本gate、bootstrap共**43C/68E**，Autotune两槽36请求另账。全部128项/段覆盖前D2D留存，GPU和pinned Host各**974640128B**，统一窗口后D2H/全量比较/持久化，成功后复用；窗口内必要恢复、版本/Event/调度/账本/留存成本均计入。准备和文件fsync排空后才建t0，全部迟到计入，周期0保留。

本轮CPU **25/25 PASS、0失败**；冻结包23条目SHA/配置dry-run/15个Python语法核验通过，未导入Torch/numpy。仅板端只读核实五目标合法值及Autotune现有源码，**未部署新包、未启动模型、未启动真实scope、未写硬件**。未修改M1脚本、v3执行快照和数学/状态机模块，保留历史失败。新CUDA留存和真实公平性能仍待运行验收，不能以CPU通过升级为GPU PASS。

交付：`reports/m2_common/20261020/clean_serial_v1/PREPARATION_REPORT.md`、`GPU_PLAN.md`、`deployment/`、`MINIMAL_DIFF.patch`、CPU与容量/工作量清单、逐段结果模板。一次性方案为1个普通nvidia模型≤180s（+10s退出grace）、1次托管五min scope≤420s、0重试；固定CPU三policy min=2201600kHz、GPU min=1300500000Hz、EMC min=3199000000Hz，其他硬件设置不改，实际snapshot逆序恢复及独立读回。**停止原因仅为“本轮尚未授权新的性能运行及锁频”**。D1已通过、D2不实施且不作为本项/M3前置；B2试选不定线，不宣称收益或k_min。

## 历史：2026-10-20 M2 v3交接时状态表

| 项目 | 当前 |
|---|---|
| 阶段结论 | M2有限数值/版本/合法块/回放机制已通过；公平串行性能基线待验收，未取得B2性能收益 |
| 路线 | B2试选；最终定线未确认；D1已获用户批准，D2本项暂不实施，不作为本项/M3前置 |
| 最新GPU证据 | `gpu_run_05` / M2 v3：APPROVED/RUN/PASS，退出0，206项检查0失败，16.74s，单进程单配置 |
| 数值准入 | D1：同进程同槽/输入的原run_pipeline与拆分Context+Expert，x/K/V/原BF16/动作逐字节等价；跨进程阈值未改，作为配置测量报告 |
| 本批配置 | `H_frozen`；S0 Context完整SHA与冻结历史一致；每批保留configuration标签及完整SHA指纹 |
| 跨进程报告 | S0/S1原BF16最大差0.015625；动作0.007801711559/0.007801771164，均在原历史包络内；不等于任意配置均通过 |
| 版本/恢复 | 发布、跨发布旧读者、latest-published、旧读者阻止回收、Event完成后安全复用实际执行；gate journal18条，53项快照全exact；槽内接续，不含重启/磁盘恢复 |
| 完整工作账本 | 协议账本3700=252 Encoder+3420 Decoder+14 language+14 Vision前缀；额外等价性全pipeline、预热工作另计，不隐去 |
| 两模式机制 | 各8周期/4刷新、journal各57、backlog0、无INCOMPLETE/UNCERTAIN；迟到全部计入 |
| 时间口径 | 本批有逐单元D2H/快照/落盘插桩；周期PASS均1/8、p99约548.8/433.5ms、k_min不可计算，全部不能作性能证据 |
| 根因解释边界 | autotune选择翻面/离散数值配置为高置信解释，v2与旧v6 Context逐字节重现；BF16算法ID未直接读到；不外推为历史Graph/Vision并发问题均已解决 |
| 原始证据 | `gpu_run_05`归档125文件272,415,341B；交接时重新核验全部本地SHA与板端清单一致；全部历史FAIL/INCOMPLETE/UNKNOWN记录保留 |
| 下一项 | 干净公平串行基线已准备：ABBA各16周期/8刷新，43C/68E完整前向总量，GPU/Host各974640128B留存，CPU25/25 PASS；待一次性新GPU+五min scope批准，不增加D2/M1前置 |

交接核对记录：`reports/m2_common/20261020/M2_V3_HANDOFF_RECONCILIATION.md`。`serial_resumed`最长连续确定违约按原始JSON及逐周期序列为7；报告旧表的4为转写错误，已校订；这仍是插桩统计，不用于性能主张。本轮交接只核对本地证据和共享文档，未访问板端或启动模型。

## 历史：2026-10-20 各批次追加状态表（交接同步前快照）

| 项目 | 当前 |
|---|---|
| 本轮依据 | 已完整读取AGENTS、DOCX任务书、brief/status/code map、M1最终收口与quota结果；新用户授权覆盖历史“不进M2”阶段决定 |
| 路线试选 | B2试选，尚未最终定线；随后“执行下一步”另行批准既定GPU短批，已执行并耗尽该一次模型额度 |
| v0原型审计 | v4所有Expert固定S0/v0；S1/v1仅build/readiness。双槽不等于通用版本管理通过 |
| 新共用代码 | `m2_executor.py`、`m2_replay_driver.py`、`m2_pi05_ops.py`；代次/完整发布/读者Event/安全回收、合法块和完整账本、同一串行回放驱动 |
| CPU核验 | `validate_m2_cpu.py` 23/23 PASS；1000次槽复用、跨发布读者、超时隔离、缺失分母、同轨迹两次序；原计算函数体AST一致 |
| 本地输入 | 固定fixture/state/noise SHA及形状/状态关系CPU PASS；不是新GPU数值证据 |
| 中间状态 | 槽内持久激活/KV接续和generation保护；未实现进程重启/磁盘加载恢复 |
| GPU实际结果 | APPROVED/RUN/FAIL_OR_INCOMPLETE；唯一模型退出1；实际1完整Context/1完整Expert（18/180层），S0原BF16门槛FAIL，未重试 |
| 本轮真实执行 | 首次SSH超时，用户“重试”后连接；新目录部署1、模型1、scope0、硬件写入0；16部署SHA/967文件预检PASS，33原始文件20,845,031B本地板端SHA全匹配 |
| M2待验收 | 初始S0原BF16误差0.2041015625>0.015625；离线动作0.0683808476>0.01；新版本管理/gate/两回放均NOT_RUN，正式统计不可计算，根因UNKNOWN |
| 新增离线取证 | FL1差异起点在Context而非Expert；FL2误差为历史跨进程漂移7.39倍；FL3本批首个autotune项208.4µs vs 历史~66µs；FL5层8边界已偏离；FL6门只测跨进程、无进程内逐字节等价。全部CPU-only |
| 诊断批（已执行） | `gpu_run_02`：APPROVED/RUN/PROBE_DIAGNOSTIC_COMPLETE，退出0，30检查0 FAIL，11.173秒；13/13部署SHA、967文件预检PASS；Q1=B=C逐字节、Q3=A=B逐字节；A/B/C均≠历史S0 x/K/V；本批对冻结参考0.197265625/0.0608556867（阈值不变，仍>0.015625/0.01）；与run01互为不同（0.101562） |
| 冷启动autotune | 首个autotune起点GPU=306MHz（最小值）；#1 Vision patch embedding 冷测231.754µs/best=7，同进程0.75秒后热测66.1664µs/best=0，历史四次66µs/best=0；相位B re-autotune为缓存命中空操作（6ms、0新行）→ 未取得历史选择下的S0 |
| 选择差异 | 本批slot0与已接受v4标定在Context路径上**只差#1**；slot1 encoder侧选择与v4完全一致（#12/#13/#18为Decoder侧） |
| 新单点隔离批 | `reports/m2_common/20261020/selection_probe_01/PLAN.md` PREPARED（1进程/3C/2E）；冻结包13文件SHA自洽；`validate_m2_selection_probe_cpu.py` 16/16 PASS；**未部署、未执行、未批准** |
| 选择探针（已执行） | `selection_probe_01`：APPROVED/RUN/PROBE_COMPLETE，退出0，29检查0 FAIL，11.336秒；S1C正对照Context与层8边界**逐字节=冻结S1**；S0W与S0C的Context x/K/V**逐字节=冻结S0**；S0W=S0C全张量逐字节；对冻结参考**0.015625/0.007801711559=PASS**（与v7历史记录完全相同） |
| 根因（高置信） | autotune在GPU最小频率306MHz下测量不稳定，导致#1 Vision patch-embedding候选翻转（7 vs 0）；#1=7的两次运行Context≠历史、输出0.197–0.204；#1=0的本探针逐字节复现历史、输出0.015625。仍未读BF16算法ID，故属耗时+数值共变推断 |
| v2修复批（已执行） | `gpu_run_04`：APPROVED/RUN/FAIL_OR_INCOMPLETE（在自建S0 Context SHA准入处停，非CUDA/托管失败），退出1，16/16部署SHA、967预检、27检查中1 FAIL；预热2次即到1.3005GHz，autotune在满频开始，#1=0@68.31µs（修复对#1有效）；#3=1导致配置仍非历史 |
| 离散配置（关键） | v2的S0 Context x/K/V SHA `0c63ddfb/8b95b48f/3abed8cf` 与2026-10-16 v6 的Context**逐字节完全相同**；历史H为`ea62dc72/7ff20f0d/4357374f`；v5为`93287069/e2e4f9e9/fd4703fa`。平台在给定配置下确定、配置可跨天重现，选择靠候选测量（#3仅差约7%即翻面）→ v5/v6历史UNKNOWN Context FAIL归因为autotune配置差异 |
| M2数值口径D1 | 用户2026-10-20**批准D1**（进程内逐字节等价为准入；跨进程0.015625/0.01照原样计算并报告为平台配置漂移），并授权同轮执行M2 v3 |
| M2 v3（已执行） | `gpu_run_05`：APPROVED/RUN/**PASS**，退出0，206检查0失败，16.74秒；进程内等价5项逐字节；配置`H_frozen`；跨进程S0/S1原始0.015625、动作0.007801711559/0.007801771164全PASS；gate journal 18条、53项快照全exact、账本3700=252+3420+14+14 |
| 两模式回放 | serial_adjacent与serial_resumed机制均PASS（8周期/4刷新/journal 57/backlog 0/迟到保留）；**插桩值**：周期PASS 1/8、刷新1/4与0/4、p99 548.8/433.5ms、k_min NOT_COMPUTABLE → 不作性能证据 |
| M2剩余 | 公平串行性能基线需另批**干净（无逐单元快照）**回放；D2（固定BF16算法）是否排入M3前置待用户决定 |
| 交付 | 共用代码/CPU原交付保留；两批GPU结果、归档与取证：`reports/m2_common/20261020/gpu_run_01/`（RUN_REPORT、FORENSICS、board）、`gpu_run_02/`（RUN_REPORT、OFFLINE_AUDIT、board） |


GPU短批是正确性验证，包含D2H/SHA/落盘且不锁频，不作为性能/可靠尾部证据。公平轨迹预先固定消费版本（含奇周期预留）；默认latest-published另行核验。不因G1–G6全部未PASS而阻塞共用M2，不补跑M1或恢复Graph/Vision并发调查。既定短批已由用户“执行下一步”批准并执行一次，数值失败后停止；剩余计划工作不是可复用模型额度。新的GPU验证须另交具体范围并批准。


> **以下为 2026-10-21 及更早的历史记录**（逐字恢复自 `reports/m3_b2/20261022/empirical_plan_selector_v1_r1/before/PROJECT_STATUS.md`，未改写）。其中任何 PREPARED/未批准段落都是当时状态，不是当前状态。

## 2026-10-20 M2 v3 批次（gpu_run_05，已执行，PASS）

用户批准D1并授权执行。状态：APPROVED / RUN / **PASS**，退出0，206项检查0失败，模型段16.74秒；16/16部署SHA、967文件预检PASS；125文件272,415,341B板端/本地SHA全匹配；无root/scope/锁频/功耗/Graph/配额/并发、无硬件写入、0重试。报告：`reports/m2_common/20261020/gpu_run_05/RUN_REPORT.md`。

- **数值（D1口径）**：进程内`run_pipeline(0)`与`context()+transformer_decoder(0)`的Context x/K/V、原始BF16、动作**逐字节相同**（准入通过）；本批配置`H_frozen`（S0 Context x/K/V SHA=冻结历史`ea62dc72/7ff20f0d/4357374f`）；跨进程（阈值不变仅报告）S0原始0.015625、S0动作0.007801711559、S1原始0.015625、S1动作0.007801771164，全部PASS。
- **版本KV/合法子块**：gate段实际执行（bootstrap→旧读者→v1块→发布→latest-published→cancel_unsubmitted→旧槽被旧读者阻止回收→旧读者Expert10→回收），journal 18条；53项快照对照全exact（含跨槽隔离）；账本3700=Encoder252+Decoder3420+language14+vision27 14。
- **两模式回放机制PASS**：serial_adjacent/serial_resumed各8周期/4刷新、journal各57、backlog 0、无INCOMPLETE/UNCERTAIN、迟到全部计入。**但周期PASS 1/8、刷新1/4与0/4、p99 548.8/433.5ms是插桩值**（每块/Expert后全量21MB D2H快照+JSON写盘位于周期之间，造成231→549ms单调抬升），不得作性能证据；k_min按协议为NOT_COMPUTABLE。
- **M2交付项**：固定输入/轨迹、版本KV、合法子块与完整账本、数值正确性、统计链路均PASS；**公平串行性能基线NOT YET**（需干净回放另批）。
- 未改任何阈值；未取得性能主张；未涉及B2机制选择；未恢复历史Graph/Vision并发调查。

## 2026-10-20 M2 v2 批次（gpu_run_04，已执行，准入门停止）

用户批准P3。状态：APPROVED / RUN / FAIL_OR_INCOMPLETE；触发者是我们自己新增的 `S0_context_x_byte_exact`（**更严格**的前置检查），不是CUDA/托管失败；未重试、未改阈值、未进入Expert10或回放。报告：`reports/m2_common/20261020/gpu_run_04/RUN_REPORT.md`。

- S1预热生效：2次丢弃Context即把GPU从306MHz带到1300.5MHz，autotune确在满频开始；`#1 Vision patch embedding`回到best=0 @68.31µs（历史65.9–66.6µs）。
- S2准入生效：#1修好之后，`#3 Vision attention output`仍落到best=1（55.58 vs 59.49µs，约7%时间差即可翻面），S0 Context x/K/V≠冻结SHA，在Expert10之前即停（代价：2次预热+1次Context）。
- **决定性事实**：本批S0 Context x/K/V（`0c63ddfb`/`8b95b48f`/`3abed8cf`）与2026-10-16 v6的Context**逐字节相同**；历史H（`ea62dc72`/`7ff20f0d`/`4357374f`）对应v4/v7/Day2B与本次探针；v5为第三种。即：平台在给定autotune配置下逐字节确定、配置可跨天精确重现，差异是**离散配置**而非连续漂移；v5/v6当年UNKNOWN的Context FAIL由此归因。
- 结论：harness正确性已不再是疑问；跨进程SHA级复现只能靠固定BF16算法（D2），否则数值验收应改为M1式两层（D1：进程内逐字节准入 + 跨进程0.015625/0.01照原样计算并报告为平台配置漂移）。不建议靠重跑碰运气。
- 未改任何阈值与判据；本次停止正是更严格检查触发的。

## 2026-10-20 选择单点隔离探针（selection_probe_01，已执行）

用户批准P2。状态：APPROVED / RUN / PROBE_COMPLETE，模型进程退出0，29项检查0 FAIL，模型段11.336秒；13/13部署SHA、967文件预检PASS；无root/scope/锁频/功耗/Graph/配额/并发，无硬件写入，0重试。报告：`reports/m2_common/20261020/selection_probe_01/RUN_REPORT.md`，离线审核`OFFLINE_AUDIT.json`。

- **S1C正对照**：slot1自然S1状态的Context x/K/V与层8边界x/K/V**逐字节等于**冻结`reference_S1_x/K/V`与`reference_S1_boundary_*`。
- **S0W**（slot1热选择+S0语言覆盖）：Context x/K/V**逐字节等于**冻结`reference_S0_x/K/V`；**S0C**（slot0冷选择，另一槽位）**同样逐字节等于**历史；两者全张量逐字节相同。
- 对冻结参考：原始BF16**0.015625**、动作**0.007801711559**，按原判据`<=`**PASS**；这两个数值与v7已接受批次记录完全相同。
- autotune：三次进程都在306MHz开始slot0的#1测量；run01/run02落到best=7（208.36/231.75µs）→Context≠历史、输出0.197–0.204；本探针落到best=0（269.25µs，仍被低时钟放大约4倍）→Context逐字节复现历史、输出0.015625。1.3GHz下三次进程的#1均为best=0、约66µs。
- 结论：数值基准本身完好，平台可逐字节复现冻结S0/S1；失败的充分变量是#1 autotune选择，触发条件是autotune在DVFS爬升段测量。未读BF16算法ID，属耗时+数值共变的推断。
- 修复准备（PREPARED，未批准）：`m2_v2`，autotune前≤8次丢弃Context预热并校验GPU频率≥max的90%，再加S0/S1 Context逐字节SHA准入；阈值与共享模块不变。`validate_m2_v2_cpu.py` 23/23 PASS。

## 2026-10-20 可复现性诊断批（gpu_run_02，已执行）

用户批准P1（由代理SSH部署执行）。状态：APPROVED / RUN / DIAGNOSTIC_COMPLETE，模型进程退出0，30项检查0 FAIL，模型段11.173秒；13/13部署SHA、967文件预检PASS；无root/scope/锁频/功耗/Graph/配额/并发，无硬件写入，0重试。报告：`reports/m2_common/20261020/gpu_run_02/RUN_REPORT.md`，离线审核`OFFLINE_AUDIT.json`。

- **Q1 已答：新harness不改模型数学。** 同一进程内`run_pipeline(0)`与`context()+transformer_decoder(0)`的Context x/K/V、层8边界、原始BF16、动作**逐字节相同**（B=C）。
- **Q3 已答：同进程确定性。** 同槽位同缓冲重跑（A=B）六个张量+输出+动作**逐字节相同**，可见地址前后一致，cudaGetLastError=0。
- **Q2 未隔离：** 首个autotune起点GPU=**306MHz最小值**；#1 Vision patch embedding冷测231.754µs/best=7，同进程0.75秒后热测66.1664µs/best=0（历史四次66µs/best=0）。相位B re-autotune是缓存命中空操作（6ms、0条新行），因此没得到“历史选择+S0”的Context。
- 跨进程：A/B/C的S0 x/K/V均≠历史SHA；本批对冻结参考原始BF16最大差0.197265625、动作0.0608556867（阈值0.015625/0.01不变，仍FAIL）；本批与run01互比0.101562/0.0340268、层8 x均值0.0768。三组配置（历史/run01/run02）各自不同，历史两次参考彼此只有0.015625。
- 选择差异已缩小：本批slot0与已接受v4标定在**Context路径上只差#1**（#12/#17/#18属Decoder侧）；slot1的encoder侧选择与v4完全一致。故“#1选择→Context字节”是当前最有力解释，但仍是强相关而非已证因果。
- 新读到的量：四次图像/噪声设备缓冲读回全部与宿主一致（补上run01缺口）；S0/S1语言embedding SHA与历史一致；相位前后可见地址表完全相同。
- 限制：未读BF16 cuBLASLt算法ID；`best`只是当次候选列表序号；无历史S0层8张量（只有SHA）；本次未触及B2机制、无性能数字。
- 下一步（PREPARED，未批准）：`selection_probe_01`（1进程/3C/2E）用同进程slot1（历史选择）计算S1正对照与S0，直接判定#1选择与Context字节的因果及“autotune前预热”能否修复0.015625门。`validate_m2_selection_probe_cpu.py` 16/16 PASS。

## 2026-10-20 离线取证与最小可复现性诊断批（PREPARED，未批准）

CPU-only，无新模型、无SSH、无硬件写入、未改任何阈值。报告：`reports/m2_common/20261020/gpu_run_01/FORENSICS.md`。

- FL1 差距起点在Context：本批S0 x/K/V（含层8边界）与历史不一致；而v4/v7已接受运行的S0 x/K/V跨进程**逐字节相同**，历史最终输出差仅≤0.015625。因此本批不是已知的Decoder抖动。
- FL2 量级：本批对冻结参考最大差0.2041015625、均值0.005073；两次历史独立参考（Day2B全图 vs v4冻结统一参考）彼此最大差恰为0.015625、均值0.000687。本批为历史漂移的7.39倍，仍比历史S0↔S1差（2.043945）小10倍，且全部输入指纹与历史一致。
- FL3 autotune选择与历史不同：本批进程**第一次**autotune（#1 Vision patch embedding）208.4µs/best=7，同进程第二个runner同形状65.7µs/best=0，四次历史运行稳定~66µs/best=0；其余17项两runner相差≤数个百分点。异常集中在进程首个autotune调用。
- FL4 #3 Vision attention output在两runner均为best=1（57.9/57.0µs），历史四次全为best=2（55.9–56.7µs）；但#8/#12/#18历史上也变过且仍逐字节通过，故不得断言序号变化必然改变数值；`best`不是可跨进程比较的cuBLASLt算法ID（Day2H）。
- FL5 层8边界（Vision+投影+Encoder 0–8）已偏离：x 93.0%元素不同、均值0.0758（参考均值2.53）；K 85.0%/0.0144；V 90.4%/0.0137。参考侧为Day2E同fixture S0快照（受限证据，跨路径跨天）。差异早于Expert。
- FL6 门顺序：该M2门是跨进程门且是进程内唯一数值门，排在全部新版本/回放检查之前；进程内没有“原run_pipeline vs 拆分Context+Expert”的逐字节等价检查。M1 v4/v7是“进程内逐字节精确+跨进程绝对容差”两层。
- 未证实：首个偏离算子与根因UNKNOWN；208.4µs属低时钟/首次workspace首触/候选列表顺序变化中的哪一种UNKNOWN；BF16算法ID当前不可读。历史v5/v6 Context FAIL、Graph/Vision并发FAIL、Day2E最终复核失败原因不变。

准备（未执行）：`reports/m2_common/20261020/repro_diag_01/PLAN.md` 与冻结包`deployment/`（13文件SHA自洽，240KB）。方案A/B/C三相位回答Q1 harness是否改变数学（B vs C逐字节）、Q2冷/热autotune（A vs B）、Q3同进程确定性（A vs B）；1进程、4完整Context（含1次out-of-reference预热）、3完整Expert10、1完整pipeline、4次autotune、0重试、300秒上限、普通用户、只写新目录；新增只读观测：图像设备缓冲读回、autotune期GPU/EMC/温度采样。进程内**不**做跨参考比较、不产生数值PASS。`scripts/validate_m2_repro_diag_cpu.py` 24/24 PASS。待用户批准P1；D1（M2数值验收是否改为M1式两层）与D2（固定BF16算法）为需用户确认的决策项，本轮未自行采纳。

## 2026-10-20 M2唯一GPU短批结果

S0参考计算完成18 Encoder/10×18 Decoder，原BF16输出对独立历史参考最大绝对差0.2041015625（阈值0.015625），1285/1600元素不同，触发停止；CPU离线动作误差0.06838084757328033（阈值0.01），295/350元素不同。输出有限，输入源/预处理/语言/noise指纹一致，实际噪声读回通过；S0末态x/K/V历史SHA不同仅作诊断，根因及首故障算子UNKNOWN。

已到达运行检查22 PASS/1 FAIL；两个原runner Autotune另账。准备参考S1、版本gate、两个各8周期/4刷新的串行回放均NOT_RUN，没有回放t0，不填写0违约率或性能数字。不扩大容差，不恢复M1 Graph/Vision根因调查，不追加GPU。旧CPU23项PASS不升级为GPU正确性通过，M1历史事实不改。

归档33/33文件SHA全匹配，未发现限定匹配的本批残留；后态46.812°C，CPU/GPU/EMC min读回729600/306000000/204000000，无硬件写入。本次GPU失败尚未触及B2机制，不据此判断B2有效/无效。详见`reports/m2_common/20261020/gpu_run_01/RUN_REPORT.md`。原准备报告/方案保留为当时快照。

## 2026-10-20 用户提出B2试选

用户原话：“我准备尝试选用B2”。据此将后续研究准备聚焦于块耗时与边界阻塞、Expert在合法边界的优先次序、完整VLM有界推进和同等优化串行对照；不把现成双块当作已有效的B2机制。M1负面结果与全部历史状态保留，约10倍违约率降低仍是挑战目标。

决定记录：`reports/m2_common/20261020/B2_TRIAL_DIRECTION.md`。既有M2交付报告为本次试选前的交付快照；共用正确性仍先验收。试选本身不增加模型、scope或硬件权限；随后用户“执行下一步”另行批准既定GPU短批，执行结果见上节。

## 历史：2026-10-18 M1收口顶部快照

更新时间：2026-10-18
当前阶段：2026-10-18 第一周收口；主指标、v10 配额曲线、首图 v2 已交；除路线选择（用户延期）外可执行项完成；M2 未启动。挑战目标未达成；旧 FAIL/INCOMPLETE/UNKNOWN 保留。
主研究路线：未选择；2026-10-18 用户明确暂不选 B1/B2、保留 B2 建议、不进入 M2。部署锚点为 180/240ms 探索锚点（紧≈串行 187.2ms 能力边界，松 240ms），不是部署 SLO。

## 历史状态表（2026-10-18）

| 项目 | 当前 |
|---|---|
| 阶段 | M1 收口 |
| 主路线 | 未选；用户 2026-10-18 延期，B2 建议保留 |
| 最新实测 | v10 配额 sweep PASS（1模型/72样本/454检查0失败） |
| 首图 | v2 已回填（A=实测配额曲线） |
| 未闭合 | 仅路线选择（用户延期） |
| 下一阶段 | M2 未启动（不自动） |
| 关键限制 | 隔离 2–14+16SM；配对仅 8+8/全 GPU；无 TPC/10+6/NX/长跑 |

## 2026-10-18 第一周收口增补与用户决定

- 离线补齐：`reports/m1_acceptance/week1_closure_20261018/WEEK1_CLOSURE_METRICS.md`；24格逐格/合并CSV与`CYCLE_DISTRIBUTION.svg`同目录。关键：180ms p99 267.5–359.9ms、违约9–15/192（4.69–7.81%）；240ms p99 259.9–263.7ms、违约3–4/192（1.56–2.08%）；刷新180ms 2–6/96未达2P、240ms 0/96；180ms双块+访存backlog 1、窗口不确定2。p99.9≈max，n=64/192，不称可靠分位数。
- 用户决定（2026-10-18）：暂不选B1/B2、保留B2建议、不进入M2；接受180/240为探索锚点（非部署SLO）；NX按表8 M5；libsmctrl未验证、Green Context作为同等验收替代；批准并执行配额 sweep 全部配额。
- 配额 sweep v10（已实际执行）：2026-10-18 用户执行`run_scope_now.sh`；1模型退出0、`status=PASS`、72样本、454检查0失败；2/4/6/8/10/12/14+16SM全legal；Context 750.4/382.0/263.4/199.7/165.3/145.3/130.7/129.2ms，Expert 183.1/107.9/88.3/84.0/84.2/84.1/84.5/87.9ms（full ref n=1）；SM探针0..q-1；频率telemetry 72/72无偏离，`RESTORED_FIVE_MINIMA`+独立读回PASS；运行后50.156°C。关键交叉核对：8SM B2 penalty 27.813ms 与v7固定−归还Event尾差28.212/28.352/28.421ms一致；B1 penalty 42.683ms不被归还回收。原始tar 361041235B、本地/板端SHA `3e238501…`完全匹配；`result.json` SHA `28c1adfc…`。
- 未闭合：仅路线选择（用户2026-10-18主动延期，保留B2建议，不写成遗漏/已选）；SM→TPC按工具边界（2–14SM探针0..q-1，TPC未暴露）；无10/6配对、NX、libsmctrl、运行中温度、第二次独立重复。
- 配套文件：最终收口报告`reports/m1_acceptance/week1_closure_20261018/FINAL_CLOSURE_REPORT.md`；配额实测同目录`QUOTA_SWEEP_RESULTS.md`/`QUOTA_SWEEP.csv`/`QUOTA_SWEEP.svg`；首图v2同目录`M1_OPPORTUNITY_OVERVIEW_V2.svg`；SM/TPC取证同目录`SM_TPC_TOOL_BOUNDARY.md`；原始`quota_sweep/board/cooverlap_quota_sweep_v10_20261018T054616Z_1200195/`（含tar/result/telemetry/BACKUP_VERIFICATION）。
- 2026-10-18 收口：用户执行板端恢复命令后完成；配额曲线不再是缺口。旧FAIL/INCOMPLETE/UNKNOWN全部保留，不覆盖旧数据。

## 历史交付入口：2026-10-17 v9（当时状态）

> 以下 v9/v8/v7/... 均为历史快照；当前状态只看上面的“当前状态”表和 2026-10-18 节。

- 总入口：`reports/m1_acceptance/M1_FINAL_REPORT.md`；按原任务书逐项验收：`reports/m1_acceptance/ACCEPTANCE_MATRIX.md`。本次实际报告、索引与所有CSV：`reports/m1_acceptance/tegra_root_trace_20261017_v9/`。
- 用户明确执行`--allow-root-diagnostic`确认一次身份例外。root权限烟测PASS，随后唯一模型18.963380秒退出0，scope20.743763秒结束；无重试。9完整Context/9完整Expert、162 Encoder层/1620 Decoder层，两Autotune及两SM探针另账。新增正常/周期样本均0，复用已审核v7/v4。
- 193运行检查、64记录对照、99张量完整性、55配对字节对照、5采集后参考字节对照全部PASS。旧v0保护、S1完整KV/最终x/边界和动作通过；历史九项中间SHA本次实际亦精确相同。跨进程绝对误差容差通过，非跨进程逐位一致；误差来源仍UNKNOWN。
- 完整CONCURRENT_KERNEL采集、API correlation及区间并集/交集审计PASS：串行0、普通4.866901、固定8+8为42.064817、合法归还44.063100ms。各模式108+99 Encoder Kernel及2410 Expert Kernel，10组重复序列完整；丢失0、窗口内未归属Kernel0。仅诊断n=1，不混入正常性能。
- v7普通用户正常各n=3：Host窗口中位串行187.191、普通187.698、固定218.184、归还189.964ms；同轮固定−归还Event尾差28.212/28.352/28.421ms。归还改善固定点，但未优于串行。完整控制成本已留账，v9补齐B2真实context/stream首次执行；不能把Kernel重叠量当净收益。
- v4 24格原样保留：两预算各三独立进程、1536 Expert/768完整刷新、安全固定访存干扰。180ms Expert存在1–3/64违约，240ms才全0/64；完整周期双块无稳定改善。旧v7路线页“Expert均0/64”过宽，当前以v4原始CELLS.csv为准，旧文件不覆盖。
- 五min自动恢复与普通nvidia独立核验PASS，无残留；19/19硬件样本SATISFIED_SAMPLED、49.500–52.750℃，不称连续物理锁频。236可读原始文件297318740bytes本地/板端SHA完全匹配；root snapshot仅板端，v4大KV历史备份范围未扩张。
- **M1测量可提交收口审核**不等于所有方法均PASS、性能改善或路线已批准。主建议优先B2问题，但当前双块不是性能胜者；B1/B2最终由用户确认。不自动开新实验、不进入M2。

## 历史交付：v8权限验证（其当时PARTIAL结论保留）

- 报告：`reports/m1_acceptance/permission_capture_20261016_v8/FINAL_REPORT.md`；实际执行发生在10月16日20:50–20:51，未虚报为17日新模型。
- 1模型23.054177秒退出1、1scope24.595575秒，无重试；准备3Context/3Expert、配对闸门1/1共4/4；正常新增0，明确复用v7，采集后参考及4诊断NOT_RUN。两原Autotune与两SM探针另账。
- 本地/板端14项CPU及1036文件预检PASS。模型UID/GID1001，采集前CapInh/Prm/Eff/Bnd/Amb均仅CAP_SYS_ADMIN、NoNewPrivs=1；真实授予通过，采集仍35。129项运行检查与27项数值对照PASS，未提高阈值或修改核心计算。
- CUDA13.2.1官方Known Issues明确Tegra tracing需root/sudo，与本次结果相符。此前通用capability方式的平台核查不充分；尚未测试root路径，不声明root采集通过。新例外仅准备一次诊断模型/监督身份，需明确确认；正常性能仍沿用v7普通用户数据，不改驱动、用户组或永久权限。
- 五min自动恢复及独立读回PASS，无残留；23用户/23BPMP样本SATISFIED_SAMPLED，69.625–73.250℃。133可读原始文件125,496,268bytes完整本地SHA通过，root snapshot留板端。M1剩余缺口仍是正确配对Kernel/correlation及实际生效完整审计，不是本次数值失败。
- root诊断例外已准备并部署，`reports/m1_acceptance/tegra_root_trace_20261017_v9/RUN_COMMANDS.md`、最小diff和冻结配置可审查；本地/板端14项CPU、SHA、dry-run及967源/checkpoint预检PASS。尚未批准此具体身份例外、root烟测0、scope0、模型0；不得把准备当实测成功。

## v7限定配对交付（历史保留，正常性能仍有效）

- 总报告：`reports/m1_acceptance/scoped_equivalence_20261016_v7/FINAL_REPORT.md`；证据索引、原始数据、CSV、机会图、路线建议同目录。协议及SHA启动前冻结，13项受影响CPU检查PASS；原模型数学、配对提交逻辑、后端、算法选择、采集器SHA不变。
- 实际1模型51.420856秒退出1/1scope53.686207秒，无重试。准备3Context/3Expert、配对闸门1/1、正常13/13，共16/16；采集参考1/1与诊断4/4未执行。两个原runner Autotune和两个8SM探针另账，全部18层/10步工作完整。
- v7历史中间SHA改作诊断，固定输入精确与同进程字节检查保留，增加独立历史S1完整输出门槛；原最终阈值0.015625/0.01未变。本次9项历史Context/边界SHA实际也全匹配，因此不将成功归因于合同修改。S0/S1原BF16跨参考最大差均0.015625、动作分别0.007801711559/0.007801771164；跨进程绝对误差容差通过，非跨进程逐位一致；误差来源仍UNKNOWN。
- 12正常样本数值PASS、297项运行检查PASS、123项记录对照精确；13配对保存张量143项离线逐位PASS。Host配对窗口中位：串行187.191、普通187.698、固定218.184、归还189.964ms。同轮固定−归还Event尾差28.212/28.352/28.421ms，归还仍未快于串行；n=3不称稳定收益。
- Expert→数学边界Event等待全部0；D2D后可调度边界等待0.297–0.405ms。归还判断前→B2提交前0.054335–0.056192ms，至提交返回6.313098–6.459784ms；一次性资源准备11.625078ms。Host完成宽界如实保留，Event和Host不混减，成本不重复扣除；首次真实Kernel生效与物理重叠仍UNKNOWN。
- CUPTI首个`cuptiActivityRegisterCallbacks`返回35，尚未启用任何活动；本机头文件定义权限不足，`RmProfilingAdminOnly=1`且nvidia无debug组。具体策略与旧Nsight差异UNKNOWN。失败采集0缓冲/0丢失不构成覆盖或零重叠，不以root跑模型、不改驱动权限或追加采集。
- 五min自动恢复及独立读回与预检原值匹配，无本批残留。52用户/51BPMP样本SATISFIED_SAMPLED，温度49.093–52.375℃。396个可读原始文件518,659,613bytes完整本地备份SHA通过，root snapshot留板端；v4大数据历史备份范围不变。
- v4的24正式格、独立重复/安全干扰/单Streamtrace不补跑。当前实质缺项收窄为限定配对完整物理时间线/覆盖、首次Kernel生效与完整净损失审计；不是数值闸门再次FAIL。路线页建议优先B2问题，现成双块无稳定改善，最终路线待用户确认。

## v6执行接续历史入口（2026-10-16）

- 报告：`reports/m1_acceptance/pair_plain_20261016_v6_resume/FINAL_REPORT.md`；索引、执行链最小diff、冻结配置/SHA、机会图及路线建议页同目录。模型/配对/采集原文件SHA未变，不是新模型方案。
- 有效scope1、模型1、无重试：模型PID970113，退出1、20.643678秒；控制器22.456855秒，退出1是如实传递数值FAIL，不是托管失败。实际完成S0 Vision27层/投影/Encoder18层，Expert前断言停止，Decoder0层；剩余20Context/20Expert及2探针NOT_RUN，两runner Autotune完成另账。
- 最终普通用户预检967源/checkpoint、合计1014文件通过；先期2份凭据在CPU冻结期间作废保留、无硬件/模型。8项CPU+8个假sysfs/子进程情形通过；旧41项模型/采集证据复用。临时service Restart=no，内部期限300秒，Runtime340/Start15/Stop60秒总边界415<420，停止先清理再恢复。没有永久服务/开机配置。
- 保存Expert前x/K/V及实际输入/噪声。x不同1125397/1148928、max_abs336；K不同2312508/2585088、max_abs3.5；V不同2405083/2585088、max_abs11。BF16正确解码，均无NaN/Inf；K/V第0层已有持久差异，不等于首故障算子。Expert未执行、采集未加载，不把Nsight或Autotune当已证实根因，不放宽Context标准。
- 运行硬件21用户/20BPMP样本SATISFIED_SAMPLED，温度71.125–74.031℃；自动RESTORED_FIVE_MINIMA实际记录，普通nvidia独立读回五min匹配、残留为空。无手动恢复，不借用旧恢复证据。
- 本次50个可读运行文件14328725bytes全部本地备份SHA匹配；root私有snapshot仍板端，未绕过权限。没有新配对trace/动作/正常样本，不能报重叠0或收益0。当前负载/后端复现性阻断，M1仍PARTIAL；剩余实质缺口是正确配对物理时间线、完整边界/生效成本及净分区损失。研究取舍待用户确认，停止自动“最后一次”循环。

### v6首次准备与中断（历史保留）


- 当前报告：`reports/m1_acceptance/pair_plain_20261016_v6/FINAL_REPORT.md`；路线建议页同目录；尝试/工作量：`ATTEMPT_AND_WORK_LEDGER.json`，模型0、有效scope1、snapshot重入拒绝1、手动恢复1。原scope退出码/具体中断信号UNKNOWN，用户确认曾中断。
- 实际部署从v4归档恢复，普通Python启动、不预加载采集器；在原Expert前Context读回处立即检查冻结x/K/V。41项CPU、固定配置dry-run及部署SHA通过。两次现有工具编译成功，Torch/Kineto支持CUDA活动，CUPTI头文件/实际库版本130201一致；小适配器只启用CONCURRENT_KERNEL。运行时采集与全部新端点仍NOT_RUN，不把编译当trace验收。
- 18:06有效scope设置五min；首次执行被中断后，没有scope/launcher/模型进程而五min仍为目标。用户完成本次snapshot的手动恢复；首apply至最后恢复读回249.493秒，随后nvidia独立核验PASS、无相关残留。原scope没有自动恢复标志，独立核验事件另行记录，不伪造stdout。
- 本次51个可读板端文件597,352bytes完整本地备份并SHA匹配；root私有snapshot仍板端。没有模型原始张量或活动trace。v4数据不重跑，v5失败不覆盖；已停止，不用剩余模型额度自动启动第二scope。

### v5最后数值补测（历史保留）

- 最后有界补测及M1收口：`reports/m1_acceptance/pair_close_20261016_v5/FINAL_REPORT.md`；路线建议页：同目录`M1_ROUTE_RECOMMENDATION.md`（建议优先B2，未获路线确认）；验收矩阵：`reports/m1_acceptance/ACCEPTANCE_MATRIX.md`当前增补。
- 新额度实际1模型/1scope；模型退出1、20.985秒，scope约35.313秒。停止前源码/checkpoint967项、fixture/实际噪声/图像/语言一致；离线x及有效K/V不同，K/V第0层相同、第1层起不同，仅为最早持久观测，首故障算子和根因UNKNOWN。Expert误差亦超既有阈值，不扩大容差。
- 新观测/配置/事务/双层闸门36项CPU PASS；Host上下界、独立GPU端点与完整控制计时已改，但未在配对上实际执行，不能把修复实现称GPU验收PASS。无新配对报告是门槛提前停止，非已证实Nsight故障。
- 本次91个可读板端文件27,151,010bytes完整备份及SHA匹配；root私有snapshot仍板端。21个用户/20个BPMP样本SATISFIED_SAMPLED；五min恢复独立核验PASS。原始输出、未执行16样本表、脚本/配置SHA均在新目录。已停止，不自动追加实验。

### v4冻结交付（不重跑、不覆盖）

- 总报告：`reports/m1_acceptance/completion_20261016_v4/FINAL_REPORT.md`；逐格表：`summary/CELLS.csv`；本批完整9次尝试：`board/archive/results_20261016T054314Z_770131/ATTEMPTS.json`。
- 三重复正式1536 Expert/768刷新；含诊断/校准1696/848，配对正式另13/13。进程内精确通过；跨进程绝对容差通过，非跨进程逐位一致；误差来源仍UNKNOWN。
- 180ms whole无干扰完整周期违约3/64、3/64、3/64，双块3/64、6/64、3/64；安全干扰whole6/64、3/64、5/64，双块3/64、3/64、9/64。240ms多数1/64，双块无干扰第二重复2/64，Expert全部0/64；双块未证明稳定周期/刷新改善。
- Encoder限定配对四模式各3样本数值通过；8+8短探针实测两组SM不重叠。普通双流Host窗口与串行接近，固定/归还同批Event尾差27.822–28.322ms，仅本路径覆盖；物理Kernel重叠UNKNOWN、配对Host下界观测FAIL，完整净损失/成本验收仍PARTIAL。历史Vision并发FAIL不变。
- 新唯一trace把段首约93ms归到Host cudaMemcpyAsync API，GPU相关复制仅约5微秒；具体停顿根因UNKNOWN。原CPU分析timeout124保留，已对同一SQLite完成离线分析，无重采。
- 五min恢复独立核验PASS，无残留。本地完整元数据/trace/小参考已校验；18.698GB完整原始数据保留AGX，大型KV尚未全量本地备份，范围明确记录。当前停止，等待研究审核，不自动追加实验。

## 状态说明

本文件记录已确认事实、进行中的工作和待验证假设。实验结果只能依据可追溯的原始数据更新。每个阶段结束后更新本文件，并生成独立的阶段交接报告。任务书原文位于 `/Users/moblumen/Desktop/CoOverlap/Student_B_CoOverlap_Revised.docx`，是最终研究依据。

## 已确认

- 已阅读修订版任务书，并完成项目理解与总体分析。
- 项目采用“一个 CoOverlap 项目、多阶段独立对话、共享项目文档”的开发方式。“项目解读与总体规划”对话负责项目理解、科研要求、全局技术规划与重大研究决策；重大路线及边界决策仍须用户确认。
- 用户拥有 NVIDIA Jetson AGX Orin 64GB 主平台；本项目已通过授权 SSH 实际访问该设备并完成候选 Pi0.5 推理。
- 主研究对象是固定计算负载下的 GPU 执行组织与周期时限；Orin NX 是对照平台。
- B1 与 B2 仍是候选路线。第一周真实负载验证完成前不选路线。
- 任务书给出的约减半 `k_min`、约缩短 50% 刷新时间、约降低 10 倍违约率均为挑战目标，尚非实验结果。
- 共享文档 `AGENTS.md`、`docs/PROJECT_BRIEF.md` 和本文件已在项目目录创建。
- 用户确认 `/Users/moblumen/Desktop/CoOverlap` 为正式项目根目录；本周源码公开归档目标为 `https://github.com/lyl-rain/CoOverlap`，提交身份已确认为 `lyl-rain <141541014+lyl-rain@users.noreply.github.com>`。GitHub归档仅含源码与小型说明文档，内部任务书、报告/原始实验数据和模型留在本地/板端。原 `/Users/moblumen/Documents/ChatGPT/CoOverlap` 空仓库保留。
- 项目已通过授权 SSH 访问 `jyh-orin`，板端型号为 NVIDIA Jetson AGX Orin Developer Kit。CUDA 13.2 官方接口在当前设备视图中报告 16 个 SM；这不等于已确认 TPC 映射或分区生效。
- Day 2A 的短时 `sm_87` CUDA Kernel 与两个现有 PyTorch 环境的基础 Tensor/矩阵乘法检查通过。两个 PyTorch 构建仍提示未将 `sm_87` 列入受支持架构。
- FlashRT/Pi0.5 是首个候选验证对象，checkpoint 为 `/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5`，尚未选为论文主负载。显式指定动作序列长度 50、双路图像、10 个去噪步骤与 `rtx_sm87` 后端后，AGX 上 BF16 完整推理通过，输出为 `(50, 7)`。固定 prompt 与状态产生 49 个 token，这不是完整视觉/语言计算的全部 token 数。固定输入/噪声下，完整图与 Context + 2 个去噪组的原始 BF16 输出及最终动作逐位一致；Decoder-only 对两份不同固定噪声的输出也分别与完整图逐位一致，但仅证明固定状态及固定 Context/KV 的顺序复用，不证明 VLM 内部切分或动态状态下复用。原始日志、脚本和小型参考数据位于 `reports/day2b/`、`scripts/` 和 `data/fixtures/pi05_candidate/`。
- FlashRT quickstart 默认动作序列长度为 10；其成功烟测不计作上述动作序列长度 50、去噪 10 步负载的正确性证据。
- Pi0.5 `state_cond=false` 的状态进入 prompt/Encoder K/V，Decoder-only 没有直接输入新状态；旧 K/V 意味着旧输入快照语义。顺序双块（vision/投影/Encoder 层 0–8 与层 9–17）在固定输入噪声下，边界激活、有效 K/V 和最终动作与完整执行逐位一致；原始检查见 `reports/day2c/REPORT.md` 和 `reports/day2b/encoder_two_blocks.log`。这不是跨周期恢复、独立图切分或双版本并发验收。
- CUDA 13.2 Green Context 最小功能探针源码及预审运行方案见 `reports/day2c/REPORT.md`；Day 2D 获得单独批准后已运行。
- Day 2D 经批准的 Green Context 短探针已执行：CUDA 13.2 资源查询为 16 SM、最小配额 2、对齐 2；8 SM Green stream 三次短 Kernel 观察到 SM ID 0–7，普通 stream 观察到 0–15，数值与资源释放检查通过。精确并发隔离与 CUDA Graph 节点归属仍 UNKNOWN，详见 `reports/day2d/REPORT.md`。
- Pi0.5 S0/S1 单进程受控对照已完成：S1 改变状态和 prompt embedding，token 长度仍为 49；绑定旧 S0 KV 的 B 与 S0 完整参考逐位一致，重建 S1 Context 的 C 与 S1 完整参考逐位一致，B 与 C 的原始 BF16 动作不同。此结果仅验证顺序状态版本语义，不代表双版本并发安全。
- Day 2E 已将一次完整 VLM/Context 刷新与每周期 Expert 的工作分账，见 `reports/day2e/WORK_LEDGER.md`。独立 Block 1（vision/投影/Encoder 0–8）与 Block 2（Encoder 9–17）CUDA Graph 曾在一次运行中与完整图、Python 顺序双块及固定参考逐位一致，含 0.05 秒受控阶段间等待与 Block Event 完成检查；另一次最终复核在新增块图捕获前即发现原完整图相对 Day 2B 参考不一致，原因未知，已停止模型测试。通过与失败原始日志均见 `reports/day2e/REPORT.md`，不能宣称双图跨进程稳定。
- Day 2E 8 SM Green Context 单节点短 Kernel CUDA Graph 功能探针通过：普通图观察 0–15，Green 图观察 0–7，API/数值/释放均成功。未测试真实 Pi0.5 图节点归属、并发隔离或性能。
- Day 2F 静态审计确认 Day 2B 参考、checkpoint 和关键 FlashRT 源码哈希未变，旧日志的 `max_abs=254` 是 uint8 字节差，不能解释为 BF16 误差。原完整图在两个完整独立进程内各重放两次均逐位匹配旧参考，输入缓冲读回一致；另一个进程因诊断脚本 JSON 序列化错误中断，不计作数值通过。Day 2E 失败输出未存，首个差异阶段及根因 UNKNOWN。按三进程上限未重跑独立双块图。详见 `reports/day2f/REPORT.md`。
- Day 2G 三个独立完整图进程按同一固定配置顺序运行：前两进程各两次 Replay 与 Day 2B 逐位相同；第 3 进程首次 Replay 出现 BF16 原始输出 1056/1600 元素不一致、最大绝对差 0.015625，已先落盘输出与后态缓冲并停止。输入 staging、fixture/权重/源码/脚本哈希一致，CUDA last error 为 0。最终后态 Encoder K/V 的可观察前缀最早从第 2 层出现差异，但首个出错算子及根因仍 UNKNOWN；双块图未复验。原始文件、SHA 清单、脚本和日志见 `reports/day2g/REPORT.md`。
- Day 2H 只读复核 Day 2G 的 44 个原始文件 SHA 全部通过，并从源码将 18 条 BF16 GEMM Autotune 日志映射至具体阶段：Run 01/03 变化的最后一项属于 Decoder 动作输出，Run 02 变化的 Encoder Attention 输出投影项仍得到正确结果。层 2 V 缓存直接来自 QKV 拆分，单独 RoPE 运算变化不足以解释 V 差异；但生产图内最早差异点、算法 ID、工作区状态及根因均未确定。分层观测与最小鉴别实验方案、未运行脚本和代码 diff 见 `reports/day2h/REPORT.md`，本轮没有运行模型或修改 FlashRT 核心。
- Day 2I 经批准的增强前后态脚本通过缓冲指针、大小、生命周期和 Attention 路由安全检查；2 个独立进程各执行 2 次完整图 Replay，四次原始 BF16 输出、有效 K/V、最终 `encoder_x` 与 Day 2B/Day 2G 成功参考一致，CUDA last error 为 0。两进程的持久语言 embedding、Encoder RoPE 和 Vision pooled 后态哈希相同，原始数据及 SHA 清单见 `reports/day2i/REPORT.md`。这些新增观测未在 Day 2G 失败进程中取得，且新增同步可能改变执行时序，因此历史失配根因与首个差异算子仍 UNKNOWN；未复验独立双块图。
- M1 恢复首批实测：两个独立非 Graph 正确性进程的原完整计算与顺序 Block 1→2→Expert 在边界激活、有效 K/V、原始 BF16 与动作上逐位一致；随后唯一 profiling 进程记录每模式 1 次预热和 5 次正式 CUDA Event/CPU 样本。Block 1、Block 2、完整 Context、Expert、同工作量串行 Event 中位分别为 78.813、43.844、122.614、99.114、183.829 ms。Expert 独立与串行区间不可简单相加，且 CPU 提交占 Expert 区间大部；默认 Stream/内部同步与运行中频率尚未核验，因此这些是初筛区间而非纯 Kernel 时间或正式公平基线。报告、原始 JSONL、日志和 SHA 位于 `reports/m1_recovery/FIRST_PROFILE_REPORT.md` 及 `raw/`。
- 获批的一次短 Nsight Systems 追踪进程完成 Context、Expert、串行各一次受插桩的 Event/CPU 记录，但 nsys 输出 `No reports were generated`，无 `.nsys-rep`/SQLite，故 CUDA API 阻塞、实际 Kernel 时间、GPU 空隙和默认 Stream 逃逸仍 UNKNOWN；没有按异常停止条件重跑。Expert/串行各记录一次 Decoder `(0,10)` 调用范围，但无逐步 Kernel 证据。只读源码审计确认 Encoder 前缀与 Decoder 后缀共用一组 K/V，且另有 Q、噪声、输出及 scratch 复用，不能直接在同一 pipeline 上双 Stream 并发。见 `reports/m1_recovery/TRACE_REPORT.md`，G6 保持 PARTIAL。
- Nsight 最小恢复：注册字符串的 CUDA/NVTX smoke 全程采集与范围采集均产生非空报告、有效 Kernel/API/NVTX；一次获批 Pi0.5 追踪在启用动态 NVTX 字符串匹配并分离输出路径后生成有效 `.nsys-rep`/SQLite。诊断 trace 中 Context/Expert/串行 Event 约 145.236/117.195/203.859 ms，对应 Kernel 时间并集约 143.879/58.189/182.032 ms；Expert 独立首末 Kernel 间有约 58.841 ms 无 Kernel，2400 次 `cudaLaunchKernel` API 总计约 35.589 ms，无单个约 95 ms 的阻塞 API。被测 Kernel 均在 stream 13；Expert 与串行各有完整 `(0,10)` 调用及 10 组重复 Kernel 序列。上次无报告的动态 NVTX 匹配和同名输出目录两个配置问题同时存在，无法唯一归因。详见 `reports/m1_recovery/NSYS_RECOVERY_REPORT.md`；诊断插桩结果不与未插桩正式样本混用，G6 仍 PARTIAL。
- 已用未插桩原始 Event 样本和获批 Nsight SQLite 离线生成 `reports/m1_recovery/OPPORTUNITY_DRAFT.svg`，标题明确为“单任务与串行执行结构初稿”，不含真实配对/分区收益。`reports/m1_recovery/SAFE_PAIR_PREP.md` 只读审计表明现有 frontend 默认共享 Attention backend/GEMM，单套 K/V 前缀、Decoder 后缀及 Vision/Encoder/Decoder scratch 均需按作业隔离；额外 K/V+边界激活仅有 12.931 MiB 理论下界，实际增量未知。拟审批唯一短配对为旧完整 v0 Context 的全 10 步 Expert 与新 v1 完整 Block 1，在独立地址/工作区验证后运行，并补做 Block 2 完成刷新；本轮未实施模型并发或修改 FlashRT 核心。
- 双槽实施静态审计：`scripts/pi05_dual_slot_adapter.py` 可用原 `Pi05Pipeline` 注入接口共享一份权重并为 v1 构造独立 Attention backend/GEMM/pipeline，但当前 C++ `GemmRunner` 的 256 MiB 私有 workspace/handle 实际地址未导出到 Python。根据用户的工作区归属与指针审计停止条件，适配层在加载 checkpoint 前拒绝运行；未产生双槽指针表、内存峰值、S0/S1 Eager 双槽参考或顺序 GPU 预检结果。最小只读接口补丁差异仅保存、未应用/编译；详见 `reports/m1_recovery/DUAL_SLOT_PREFLIGHT_REPORT.md`。此前单槽正确性事实不变，双槽功能与并发安全均 UNKNOWN。
- 后续获批隔离构建：只读 getter 补丁已应用于 `/home/nvidia/rtvla/cooverlap_diag_20261014_resource` 的源码副本，使用未改数学实现的原 `gemm_runner.cu` 编译独立 `flash_rt_gemm_diag`，生产源码/扩展未覆盖。一次无 checkpoint smoke 创建两个 runner，前置 workspace/scale 指针有效及区间无重叠检查未触发错误，但在“两个 handle 标识不同”断言处失败，未重跑或启动模型。首次 smoke 在断言后才落盘，具体地址/内存值未保留；收集脚本已修正但未重新执行。详见 `reports/m1_recovery/DUAL_SLOT_RESOURCE_VALIDATION.md`。handle 值相等尚不能推出 workspace 冲突或并发安全，双槽验收仍 UNKNOWN。
- 用户随后撤销“opaque handle 值必须不同”的单独硬失败条件。获批的一次增强无 checkpoint smoke 已先落盘资源与内存：两 workspace/scale 区间独立、地址稳定；两个非默认 Stream 20 轮小型 BF16 GEMM 与基准逐位一致；销毁 runner1 后 runner0 仍计算正确。此证据仅覆盖小算子和指定生命周期，未证明真实模型 GPU 重叠或全部内部资源安全。
- 条件放行后，仅一个 Pi0.5 模型进程完成双槽顺序预检（timeout 120、退出码 0）：一份共享只读权重、两个独立 backend/GEMM/pipeline；180 条可写设备条目无跨槽或只读冲突、45 组权重/515 个指针叶子共享且有 owner、前后地址稳定。S0/v0 发布后依次运行 S1/v1 Block 1、v0 全 10 步 Expert、v1 Block 2；旧前缀/语言状态不变，边界/最终 K/V 与 S1 Eager 参考、Expert 与 S0 Eager 参考逐位一致，85 项检查/19 数值对照及四个完成 Event 均通过。全部模型工作、原 Autotune 与初始化在单一默认 Stream 0，未捕获/重放 Graph。v0→v1 构造阶段 CUDA free 减少 562397184 B（536.344 MiB），RSS 增加 567876 kB；VmHWM 23683416 kB。详见 `reports/m1_recovery/DUAL_SLOT_LIFECYCLE_REPORT.md` 及原始地址/内存/张量；本轮已停止，未做真实模型并发。

- 首次获批真实双 Stream 配对：仅一个模型进程、一次顺序对照和一次 Pair01。相同进程的顺序对照13项数值逐位通过；Pair01 Expert原始BF16/动作及旧S0 KV保持一致，但新S1 Block1边界1018346/1148928元素不同（最大绝对差4.0），有效9层K/V也不同，最早已保存差异为层0（不等于首个故障算子）。按停止条件未执行配对后Block2/新发布、未重试。Nsight有效trace经Runtime correlation归因显示stream13/17共2875个Kernel、物理重叠约15.192ms；失败窗口不能作共执行收益结论。配对后完整地址复查未到达，库内竞争根因UNKNOWN。详见 `reports/m1_recovery/FIRST_SAFE_PAIR_REPORT.md` 及 `first_safe_pair/` 原始输出/地址/内存/trace/SHA；当前普通双流数值闸门FAIL，不放行Green Context真实配对。

- Pair01定点定位（2026-10-14）：75个原始Run文件再次SHA校验通过。层0 K/V全部差异限于第一视角token0–255（K34823/V37777），第二视角与语言49token均逐位一致；层1起差异扩散到三个区间。既有trace按Runtime correlation及Kernel序列映射表明Expert首Kernel在Block1起点后21.919968ms、Vision层6 QKV期间启动，早于Encoder层0；不能排除并发资源问题，也不能据重叠指定根因。新前后态脚本仅完成设计/语法检查，未部署/运行；SSH三次握手重置（255），未完成本轮完整CUDA/FA2/temporary源码审计及设备预检，故条件GPU授权未执行。详见 `reports/m1_recovery/PAIR01_FAILURE_LOCALIZATION.md`、`pair01_localization/offline_final/`。G4并发数值子项仍FAIL，项目级G1–G6全部PARTIAL。

- 访问恢复与增强Pair01（2026-10-14）：SSH第一次恢复尝试成功；取回Vision/Encoder/FA2/GEMM源码且关键SHA未变，未发现当前BF16/vendor FA2分支的确定共享写冲突，闭源内部状态仍UNKNOWN。仅1模型进程/120秒、1顺序对照（19数值PASS）、1配对（FAIL），无重试。两视角图片/S1语言/RoPE前态逐位一致；第一视角Vision终态253215/294912元素不同、max_abs4.5，第二视角一致；第0层K/V仍仅第一视角不同。旧KV/Expert与可见前后地址通过；有效trace确认18.438976ms Kernel交集。失败后不执行Block2/发布；168原始文件SHA校验通过。根因/首错算子UNKNOWN，G4双流数值FAIL。按用户要求冻结并发调查，不自动追加诊断/分区；交接见 `reports/m1_recovery/PAIR01_ENHANCED_HANDOFF.md`。提出基于原未插桩AGX数据的180/240ms候选及最多1进程、32Expert/8完整Context的有限单Stream观察计划，尚未执行，见 `B2_OPPORTUNITY_PLAN.md`。

- 六组合单Stream机会观察尝试（2026-10-14）：已固化150/180/240ms×whole_context/two_blocks×8周期协议。唯一模型进程中B1→旧v0 Expert10→B2顺序闸门11项数值逐位PASS、64项已到达检查通过；首段150/whole_context的E0执行180个Decoder层后，journal(kind, **rec)与rec.kind冲突，日志TypeError退出1。未持久化E0完成时间/输出，未执行计时Context或后续5段；首段INCOMPLETE，其它NOT_RUN，违约/响应/边界等待UNKNOWN，完整周期违约率NOT_DEFINED。未重启或追加GPU。CPU记录最小修正版及实际journal载荷测试PASS（尚未部署/运行），旧执行583ad824版本与56个原始文件保留。报告 `reports/m1_recovery/B2_OBSERVATION_REPORT.md`、未完成图 `b2_observation/OPPORTUNITY_INCOMPLETE.svg`。下一轮仅可审核同一48Expert/12Context协议的至多1模型120秒重试授权，当前上限已用完。

- 日志修正后六段完成（2026-10-14）：用户授权合理修改并完成实验后，仅启动1个新模型进程（119秒TERM+1秒KILL上限，退出0），150/180/240ms×完整Context/两块边界×8周期均排空并验证。计时账本48 Expert/12完整Context，参考与闸门另列；417项检查及143项数值对照全部PASS/逐位一致，302原始文件跨设备SHA一致。Expert违约分别为150ms完整2/8、分块1/8；180ms完整1/8、分块0/8；240ms两者0/8。150/180ms分块最大边界阻塞较小但刷新可能更晚，不代表稳定净收益或已选B2。Host完成观测有轮询误差，Event不是纯Kernel时间；完整Context内部B1没有独立完成观测，逐周期账本为已退休单元。完整周期违约率NOT_DEFINED，分区响应/损失未测。失败尝试及其原始文件全部保留。见 `reports/m1_recovery/B2_OBSERVATION_COMPLETED.md`、`TASK_CONFORMANCE_REVIEW.md` 与 `b2_observation_retry/`。

- 最后一次逆序复核（实验2026-10-14，交付2026-10-15）：仅1模型进程/总timeout120秒、退出0、无重试；只反转实际六组合清单，保持全部计算及观测策略。417检查/143数值对照PASS，48Expert/12Context排空，302原始文件SHA跨设备一致。两批违约计数均为150ms完整2/8、双块1/8，180ms完整1/8、双块0/8，240ms两者0/8；不确定违约样本均0。180ms双块第二刷新364.338→358.504ms，观测k由3→2，刷新进度对顺序/设备状态敏感，不追加第三批。有限机会观察阶段收口，未宣称可靠尾部/稳定改善/k_min/B2选择。完整启动账本含前轮失败1次、修正成功1次、本次逆序成功1次；150ms来自用户直接授权，不是脚本扩权。见 `reports/m1_recovery/B2_REVERSE_REVIEW.md`、`B2_REVERSE_AUDIT.md` 和 `b2_observation_reverse/`；固定k/每周期必做工作/刷新约束仅离线草案 `NEXT_MINIMAL_PROTOCOL_DRAFT.md`，未生效。

- 固定周期义务v1（2026-10-15）：独立协议m1_period_obligations_v1将刷新间隔改为2P、目标Q+2P；偶周期同刷新B1、奇周期B2/完整就绪，全部Expert仍旧v0。CPU账本/fake Event审查及GPU顺序闸门PASS。仅1模型进程/总120秒，无重试；32Expert/16Context计时全部排空，前三段验证PASS，第四段段外BF16比较收到超时信号并最终退出137，整体INCOMPLETE。180完整/双块、240双块的完整周期确定违约为7/8、7/8、1/8；第四段240完整保存时间为3/8，但末尾验证INCOMPLETE，不能扩为PASS。32周期无deadline区间不确定。340已到达检查/123数值记录全通过；292原始文件SHA一致，116组已保存计时张量离线逐位一致；第四段末尾语言活态读回/validated内存/observer正常收尾未完成。新统计仅对本协议有定义，旧机会观察仍NOT_DEFINED。没有因负面结果改k/deadline或追加回放。见 `reports/m1_recovery/PERIOD_OBLIGATION_VALIDATION_REPORT.md` 及 `period_obligations_20261015/`。

- 孤立限额响应（2026-10-15）：仅1模型进程/总120秒、退出0、无重试；普通full与合法8SM Green完全顺序，单权重/pipeline/backend/runner。当前查询16SM/min2/align2，普通/Green stream探针分别SM0–15/0–7，当前FVK/GEMM/FA2显式stream检查通过，资源/语言地址稳定并正常释放。被测Context8/Expert8（各配置1预热+3正式），另full参考各1及Green闸门各1；133检查PASS，81原始文件SHA一致，40保存张量离线逐位通过（含参考自比较）。同批正式Event中位：Context122.790→199.718ms，B1 78.877→127.988ms，B2 43.967→71.729ms，Expert80.417→81.892ms；均为包围区间非纯Kernel。全部真实Kernel物理SM及闭源辅助流未逐一观测，限额归属仍未完整验收。孤立端点不等于安全共执行/Expert结束后的净分区损失，不能覆盖双流FAIL。未补跑周期、未恢复Graph/并发、未改锁频/功耗/系统/依赖。见 `reports/m1_recovery/ISOLATED_LIMIT_RESPONSE_REPORT.md`、`M1_EVIDENCE_GAPS_20261015.md` 与 `isolated_limit_20261015/`。

- 顺序合法边界切换（2026-10-15）：仅1模型进程/120秒、退出0，无重试；A(full→full)/B(8→8)/C(8→full)均在B1完成确认、同样D2D留存及依赖后提交B2，没有Expert或块重叠。预热ABC、正式ABC/BCA/CAB；12被测完整Context+原full参考1+混合闸门1，115检查PASS，169原始文件SHA一致，84保存张量逐位一致（含参考自比较）。同批Host完整刷新中位A123.469/B201.502/C173.458ms；B1确认后的尾段A44.444/B72.641/C44.526ms，逐轮B−C差值27.785/28.108/28.260ms。Host间隔包含诊断D2D/路径及依赖成本，不等于纯GPU上下文切换；不是真实Expert竞争下归还净收益，不覆盖双流FAIL。资源/语言/地址/层账本/释放通过，全部Kernel物理限额归属仍未完整验收。报告 `reports/m1_recovery/BOUNDARY_SWITCH_REPORT.md`，原始 `boundary_switch_20261015/`。阶段建议页 `M1_ROUTE_RECOMMENDATION.md` 明确优先B2（工程可用性+边界机会），不声称B2已性能胜过B1、M1全验收或路线已选；本批收口停止，不自动追加短测。

## 候选模型硬性验收 G1–G6

此编号是项目自定义标准，定义见 `docs/PROJECT_BRIEF.md`，不是原任务书编号。局部通过不扩大为整项 PASS。

| 编号 | 状态 | Pi0.5 当前证据与缺口 |
|---|---|---|
| G1 真实模型完整运行 | PARTIAL | 固定 checkpoint、合法双视角固定图像、BF16、10 去噪步、50 动作长度的完整推理有效且无 CUDA 运行错误；目前图像由脚本生成，尚无真实相机/数据集输入的完整验收。 |
| G2 VLM / Expert 合法分离 | PARTIAL | 固定旧v0独立Expert及双槽顺序/周期调用PASS；10月16日Encoder限定组配对数值PASS。新v1仅构建观察，最新版本切换/通用执行器未验收，非M1额外前置。 |
| G3 真实 VLM 可分块推进 | PARTIAL | Eager 0–8/9–17合法切分、跨Expert恢复及本批1536个正式周期完整工作账本PASS；8SM至普通B2合法接续通过。覆盖固定快照有限回放，不扩大为通用恢复。独立双图仍未知且不作为当前Eager M1前置。 |
| G4 数值与版本正确性 | PARTIAL | v7限定Encoder正常12样本及v9四诊断、同进程原始字节/采集前后参考/旧v0保护PASS；独立S0/S1输出满足固定绝对阈值。历史v5/v6 Context FAIL、Vision并发FAIL及Graph UNKNOWN保留；本次历史中间SHA也匹配，不证明历史根因或任意并发已解决。 |
| G5 固定负载可复现 | PASS（本协议固定fixture范围） | 10月16日固定checkpoint/BF16/双视角/token/18层/10步/50动作及工作账本、统一参考、实际输入读回均可追溯；两预算各3独立进程、24格完整，14个安全worker容量/哨兵/计数PASS。旧越界干扰FAIL保留，不追溯升级旧结果。 |
| G6 可用于真实执行测量 | PARTIAL（当前限定路径测量子项PASS） | v4周期/刷新/k/积压及单Streamtrace、v7正常四模式公共Event/Host保守界与完整控制成本、v9完整Kernel/correlation覆盖和目标B2首次执行、v10隔离2–14+16SM配额响应及SM ID探针已交。支持当前有限公平回放/对照；不扩到任意Vision并发/Graph、TPC或可靠长尾保证，旧v4下界FAIL不追改。 |

## 历史：2026-10-17 限制与待决定（v10 前状态；v10 已补配额曲线，路线用户延期）

- M1有限测量与产物已交齐，等待用户审核收口和确认主路线；未取得相对串行的配对净优势，双块周期亦无稳定改善。负面结果不等于实验未做。
- 任意Vision并发安全仍FAIL，历史Context/Graph失配根因UNKNOWN；本次限定Encoder数值及物理重叠通过不覆盖旧FAIL，不恢复旧调查。
- 隔离配额2–14+16SM已测（v10）；配对仍只有合法8+8与普通全GPU；全部闭源Kernel逐SM物理集合未穷尽；TPC未暴露。已取得探针、显式路由、真实context/stream活动，不再把该限制串成无限前置。
- 正式部署预算/SLO、全配额公平**配对**优化（隔离响应已有）、可靠长尾/k_min、长期热稳定、最新版本切换/通用回收器、NX及论文六图均未全验收，属于后续范围，不扩为M1首周额外门槛。
- v4原始约18.698GB完整在AGX，本地大KV395文件未全量备份；v7/v8/v9/v10各自可读原始范围完整本地SHA通过（v10本地tar 361,041,235B、SHA `3e238501…`），root snapshot仅板端。

## 待验证问题

1. 候选 Pi0.5 是否适合作为最终论文主负载；其他真实负载的软件环境与正确性尚未验收。
2. AGX 的SM→TPC映射、libsmctrl新栈兼容性及全部真实算子限额归属仍未完整确认；v10 已取证 TPC 不由 CUDA/nvidia-smi/设备树暴露、libsmctrl 未安装，用户 2026-10-18 确认按工具边界收口；Green Context 2–14SM合法配额、两组不同SM探针和短Kernel/单节点Graph已通过，不能继续列为从未验证。
3. S0/S1双槽单Stream分块恢复、发布Event和旧Context复用已通过；v4有限64周期独立回放已通过。长期热稳定、独立双图重复、并发版本发布/回收仍UNKNOWN。`state_cond=false`将状态编码进Context，旧S0动作不称S1即时响应。孤立8SM与v7/v9限定Encoder配对数值有限PASS，v9物理Kernel重叠及覆盖已测；历史v5/v6 Context FAIL和全部闭源Kernel物理SM集合未穷尽分别保留。
4. 限定Encoder配对干扰/物理重叠/固定分区与归还尾差已实测；v10隔离2–14+16SM配额响应已实测；10/6或其他配对、全Context安全及稳定相对串行净优势仍未证明。
5. 块粒度、边界等待、launch/同步和跨周期状态维护对 Expert 尾部的影响。
6. CPU、内存和相机搬运干扰，以及实际频率和热状态对尾部样本的影响。
7. 任务书引用的已有工作与目标软件版本的具体能力边界；历史 NX 记录与未附 trace 的原始证据。

## 历史：开始 M1 前需确定的实验定义（已由后续协议具体化）

- 真实 checkpoint、推理后端、精度、去噪步数、输入形状、视角与实际 token 数。
- 目标部署周期、宽松/紧预算的候选范围，以及预先规定的违约要求。
- 数值一致性容差、固定输入和噪声、刷新到达轨迹、当期必做 VLM 工作清单及未完成作业的统计规则。

以上历史待定项现已在双层数值、固定fixture、2P义务与v4预算协议中冻结。仍未确认的是正式部署规格，不能将旧段落理解为当前尚无实验定义。

## 本轮M1验收准备（2026-10-15）

- 对照原任务书§1/§2/§8.3建立 `reports/m1_acceptance/ACCEPTANCE_MATRIX.md`，区分实测FAIL、NOT_RUN、BLOCKED；不用孤立限额/顺序切换/失败配对代替安全共执行或真实净分区损失。
- 七套历史清单2639条匹配、0缺失；9差异是后续修改的共享文档或.gitignore；原始实验数据未发现变化。详见 `prep_20261015/EVIDENCE_HASH_AUDIT_FINAL.json`，原历史SHA不改。
- 原2P周期协议整体PARTIAL、前三段PASS、第四INCOMPLETE，180ms两计划均7/8完整周期违约、双块积压保留；旧4P机会观察完整周期仍NOT_DEFINED，不追溯重算。无补跑、无追加短测。
- 新协议仅已准备未运行：一次独立180/240/320ms校准，冻结紧松预算后3次独立重复，每组合64周期，有/无同一CPU内存干扰；另一次最小诊断trace。最多5个新模型进程、计时1696 Expert/848刷新，准备另账。需要全新明确授权，不能借旧120s授权启动。
- 新驱动复用原Eager/双槽/统计路径；同两计划对称保留B1边界，所有原逐位/旧v0保护/完整工作量检查保留。11项CPU测试和13份无torch配置dry-run通过；新增驱动尚无板端结果，不称GPU PASS。
- 只读确认CPU可用最高2201600kHz、GPU1300500000Hz、bwmgr EMC3199000000Hz；MAXN0不变。已准备五个min节点的备份/限值设置/恢复脚本，仅CPU模拟恢复PASS，未实际写入。sudo非交互权限未具备，需要用户单独批准和现有交互执行途径。mask=0已读取，不据此推断SM→TPC拓扑。

## M1定点安全核对（2026-10-15）

- 本轮模型启动0、硬件写入0、root scope执行0。L4T只读确认39.2.0，安装jetson_clocks的tegra234 do_emc使用bwmgr接口；请求target204MHz与报告cur3199MHz已区分。独立BPMP EMC rate当前nvidia权限不足，UNKNOWN，不称已锁频。
- B1义务完成用留存前Event；双块可调度点用留存后Block1末Event确认；whole_context仍立即按同Stream顺序提交B2，不内部调度。新增仅Host时间戳/既有Event事后计时，最小diff已保存。
- 实际频率条件未满足/UNKNOWN的段完整保留、单列，不删迟到周期、不补跑、不混称固定频率结果；校准条件无效则保留结果后停止后续模型。原预算筛选数值规则/五进程范围不变。
- root范围限五个min节点及必要只读遥测/本批清理；模型/干扰/分析降权nvidia并记录uid/gid。正常/SIGTERM/超时先清理本批后代再恢复，SIGKILL/断电保留手工恢复。CPU模拟核验通过，板端root操作尚未执行，不称实测PASS。
- 交付 `reports/m1_acceptance/targeted_20261015/REVIEW.md`、实际scope/shell/launcher片段与SHA；等待一次性明确批准硬件范围和既定有限批次，不再追加泛化准备任务。路线未选择、M1未全部验收、不进入M2，并发/Graph冻结不变。

## 已批准批次的CPU停止记录（2026-10-15）

- 用户已批准既定五节点范围及m1_completion_batch_v1，无需重复申请同范围授权；root仍由用户在板端交互提权。
- 最小事务恢复修复已实现：apply前建立责任、拒绝已有snapshot、限定本事务有效文件，覆盖apply返回责任窗口。
- 新CPU故障注入5项：4 PASS、1 ERROR（恢复mock仅接收1参数，实际传2参数），测试退出1。依用户“CPU核验失败则停止”未继续测试、部署或模型执行；保留原失败，不将其称GPU/硬件回滚失败或PASS。
- 模型启动0、部署0、root scope0、真实硬件写入0；五进程额度未消耗。执行快照、部署SHA及失败详情：`reports/m1_acceptance/execution_20261015/REPORT.md`。本修复版本尚未通过门槛，不应部署执行。
- 并发继续冻结，路线未选择，M1未全部验收；批次范围不扩大。

## 已批准批次接续：CPU通过及部署（2026-10-15）

- 保留前次CPU FAIL脚本/日志/SHA，仅修指定测试函数：严格断言restore的root为临时假sysfs，并将其显式传入原restore；原事务恢复逻辑不替换为空操作。五个假节点原值10/11/12/13/14在中断后全部恢复。
- 本轮各一次运行5项事务、8项定点及11项协议回归，24项全部PASS。正式m1_clock_scope生产代码本轮未再改动；执行快照/部署SHA已更新。
- 已向独立新目录部署21个文件，板端SHA全部OK。只读预检MAXN0、既定max/支持频点、固定输入/隔离扩展SHA匹配；当时约49.9°C、可用52GiB，无相关模型进程。
- 当前仅缺用户指定的板端交互sudo步骤；命令见`reports/m1_acceptance/execution_resume_20261015/REPORT.md`。模型尝试0/5、root scope0、真实硬件写入0，无新的批次性能/恢复实测结果；不重复申请同范围授权。
- 已批准范围/校准/时限/干扰保持，不追加重试，不解冻并发，不选线、不进M2。

## 首次板端scope设置失败及恢复（2026-10-15）

- 用户已交互执行scope一次：apply设置读回FAIL，输出RESTORED_FIVE_MINIMA；随后只读SSH独立核对CPU三policy/GPU/bwmgr五个min均回到运行前值729600/729600/729600kHz、306000000Hz、204000000Hz，恢复匹配。
- 模型尝试0/5、Expert/Context均0；异常早于runuser/Popen，批次NOT_STARTED。实际硬件设置曾尝试，不再称硬件写入0；具体失败节点/读回值及写入次数未记录，UNKNOWN。
- 原snapshot和scope日志保留；不复用snapshot、不自动重试、不改目标/增加等待绕过读回。只准备未应用的错误详情最小diff，当前源码和部署不改。
- 24项CPU PASS保留，真实设置FAIL不改写成模型FAIL；详见`reports/m1_acceptance/scope_failure_20261015/REPORT.md`。路线未选择、M1未全部验收，并发保持冻结。

## 设置读回修复及部署（2026-10-15）

- 用户要求必要修改后，scope改为每min写一次、最多1秒只读确认，精确值判据不放宽；成功/失败均记录节点、目标与实际读回序列。恢复同样有界确认；全部设置后再核对完整请求限值。scope总计时包含设置阶段。
- 新4项读回测试及原5/8/11回归共28项PASS，仅CPU假文件，无GPU/真实节点写入。旧scope FAIL及恢复核验保留，历史根因仍UNKNOWN，不能称板端已修复PASS。
- 已保留板端旧scope/旧部署SHA，更新22个部署文件SHA全部OK；部署后无scope/模型进程，五个min仍为原值。首次SSH只读检查断连日志保留，后续连接成功，不计模型尝试。
- 本轮模型尝试0/5、root scope0、硬件写入0；等待用户按已批准交互方式运行batch02唯一snapshot，命令及详情见`reports/m1_acceptance/readback_fix_20261015/REPORT.md`。不自动重试、不改频点、不增加模型范围；M1未全验收、路线未选择，并发冻结。

## m1_completion_batch_v1实际停止（2026-10-15）

- batch02五min设置通过；CPU三policy确认约10ms读回延迟，旧batch01原因仍不能唯一追溯。用户scope终端显示五min全部恢复读回成功。
- 实际启动2/5模型进程：校准退出0、三个32周期段PASS，采样频率条件满足；规则冻结紧180/松240。校准完整周期违约180为3/32、240/320各0/32，刷新目标180为15/16、240/320各16/16；仅校准有限结果。
- repeat1启动后非零退出触发停止；具体退出码、原因、最终已完成段数UNKNOWN，未擅称超时或数值FAIL。repeat2/3及诊断trace NOT_RUN，不自动重试。
- 两次有限只读SSH取证均被reset，已停止板端读取尝试，未改SSH/系统或写硬件；恢复当前仅由用户完整终端日志确认，独立事后复核及原始张量离线核验尚待访问。
- 停止记录与用户scope完整输出：`reports/m1_acceptance/batch_20261015/REPORT.md`。校准原始数据待取回复核；不宣布三重复、干扰、时间线或M1全验收。

## m1_completion_batch_v1最终取证（2026-10-15）

- SSH访问恢复，实际ATTEMPTS确认校准退出0、151.351s；repeat1退出1、260.190s，状态INCOMPLETE_TAIL_RESERVED。在下段启动前超过300−60s阈值主动停止，不是外层timeout强杀。后两重复和trace NOT_RUN，未补跑。
- 实际计时288 Expert/144完整Context（校准96/48、repeat1的3段192/96），准备另4 Expert/6 Context、Autotune另账。五min通过独立只读核对恢复为原值；原snapshot不覆盖。
- repeat1三个180ms段均段内数值PASS、SATISFIED_SAMPLED、不确定0。完整周期违约：whole无3/64、whole访存干扰5/64、two_blocks无7/64；Expert违约1/64、2/64、2/64；刷新目标未达1/32、1/32、3/32，最大k为3、3、4。双块当前结果更差，负面结果保留，不选线。
- 时间分解：三段回放合计34.372s，窗口外结束至校验/落盘合计205.936s。定位到窗口外成本，不将其当模型服务时间；源码反复整份JSON/fsync为候选开销来源，未声称唯一瓶颈。
- 板端普通用户CPU离线：2488文件SHA、1218张量元数据/有限值PASS，1170项保存结果对各自参考PASS；本地1270元数据SHA匹配。
- 新发现：两个进程Expert参考不逐位一致，原BF16动作1101/1600元素不同、max_abs0.015625；最终float32动作183/350不同、max_abs0.00780171156，无NaN/Inf。输入/预处理hash及Context最终x、有效KV、B1边界参考一致。跨进程Expert逐位子项FAIL、根因/首故障算子UNKNOWN，不放宽标准、不扩大Graph/并发诊断。
- 原raw约3.112GB完整留AGX；本地完整metadata及四个跨进程小参考已核验，慢速全量拷贝的partial.tar明确不完整，未冒充完整备份。最终报告：`reports/m1_acceptance/batch_20261015/FINAL_REPORT.md`；Host机会图及CSV同目录board结果下保留。
- G4/G5保持PARTIAL并记录新跨进程Expert子项FAIL；G6仍PARTIAL（未完成三重复/新trace）。M1未全验收，路线未选，不自动执行剩余进程。

## 2026-10-15最新授权接续与停止

- 最新时间线采用18:30停止新模型启动、19:00前交付，不沿用旧22:30/23:30。新增最多9进程、2scope；实际只用1进程/1scope，不与旧剩余额度叠加。
- 首轮离线核对输入/config/脚本/扩展/槽配置一致；旧现场原始噪声未单独保存，UNKNOWN。算法best变化不认定根因。窗口外逐检查反复整份报告改为增量持久日志、原显式点原子提交；新5项CPU及原28项回归PASS，隔离部署恢复/读回另9项PASS，无核心数学修改。
- crosscheck1冻结旧calibration统一参考，实际1次完整S0 Context/1次完整Expert，18 Encoder/10×18 Decoder；原Autotune另账，计时回放0。13.241s退出1：1094/1600原BF16元素不同、max_abs0.015625；离线最终动作174/350不同、max_abs0.00780171156，NaN/Inf0。不改容差、不更换算法、不筛成功、不执行第二进程。
- 执行前实际噪声与固定fixture及上传源一致；执行前/后的18层有效KV和最终x均与旧calibration哈希一致。最早已观测差异为Expert最终动作，首故障算子/根因仍UNKNOWN；旧/新预计算time/style内容及具体算法身份尚未对照，不声称全部隐藏有效条件一致。
- 本轮统一参考失败后，校准、三重复、trace、mutex鉴别及真实分区/归还均NOT_RUN/BLOCKED，不消耗更多模型额度；并发再次保持冻结，原双流FAIL保留。
- scope01设置/恢复每节点读回PASS，16:52:42只读独立核对五min为CPU各729600kHz、GPU306000000Hz、EMC204000000Hz；无匹配模型残留。运行采样SATISFIED_SAMPLED，不扩为连续物理频率保证。
- 本轮50个原始Run文件完整取回并SHA核验；scope日志/root遥测保存，root snapshot仍板端原权限。历史约3.112GBraw仍AGX完整、本地历史全量备份仍不完整。
- 静态发现原驱动设置t0后仍整份save，可能跨首个释放；v2写入方式变化可能影响首次Host发现延迟，已登记协议风险。未进入新回放，不宣称新旧窗口行为全部严格等价或板端收尾瓶颈已解决。
- 交付 `reports/m1_acceptance/resume_20261015_v2/FINAL_REPORT.md`、完整尝试账本、逐格三重复缺失表、原始输出/配置/脚本SHA及阶段建议页。**今天未完成任务书全部M1要求**，不以离线交付替代剩余实验。

## 新双层数值协议批次交付（2026-10-15）

- 用户替代旧跨进程Expert逐位门槛，冻结`m1_completion_dual_gate_v3`。进程内原始字节严格一致；跨进程BF16 max_abs≤0.015625、最终动作≤0.01，无rtol/epsilon，fixture/实际噪声/语言/有效KV/x精确一致。统一表述“跨进程绝对误差容差通过，非跨进程逐位一致；误差来源仍UNKNOWN”。历史FAIL不追改。
- 新9项CPU闸门/形状/非有限/阈值/时钟顺序检查和13个配置dry-run通过；初次CPU夹具字符串断言失败保留，范围内纠正后通过。全部一次性save/flush在t0前，窗口内正常观测与日志成本仍保留。无额外gate-only、首差分或并发进程。
- 使用第二/最后scope。实际3/5模型：校准92.239s退出0；repeat1 222.618s退出0，八格完成；repeat2 255.444s退出1，六格完成后触发原240s新段准入门槛/60s收尾预留，不是外层timeout或数值FAIL。repeat3、trace NOT_RUN，无补跑。
- 本批计时992Expert/496刷新，准备另6/9，Autotune另账。连同此前v2失败核验，当日新授权实际4/9模型；两scope已用完且均恢复，不把未用模型额度当重试授权。
- 校准180/240/320各32周期完整违约3/1/0，Expert1/0/0、刷新目标均16/16，按原规则冻结180/240。14个正式格均完成64Expert/32刷新，原模型数值/硬件采样通过，不确定0；第三重复全部未做，第二重复180whole两格未做。
- 本批三个进程跨参考原BF16最大差均0.015625，最终动作均0.00780171156；不同元素与位置完整保留。三个进程norm_stats及新time/style设备哈希一致；旧现场style内容缺失仍UNKNOWN，Autotune日志不当因果证明。
- 独立CPU离线10337文件SHA、5113张量完整性/有限值PASS，5011项计时保存结果对本进程参考精确PASS。原始约10.446GB完整在AGX；本地metadata/小参考/噪声/状态5253项导出核验通过，完整KV未全量本地备份。
- 原始结果：180双块无干扰两重复3/64、3/64；240四格每重复均1/64，未见完整周期改善。干扰格保留原观测4/64→8/64及刷新积压，但不能用于合格干扰归因，原因见下一项。完整24格索引包括10格NOT_RUN，不填零。
- **交付前发现干扰安全FAIL**：执行worker SHA f802949…，`create_string_buffer(bytes)`源为32MiB+1，目标32MiB，按源长度复制越界1字节；7个干扰格模型数值PASS不等于干扰协议PASS。CPU有界owner内哨兵复现旧错误；独立修正版显式等容量并拒绝长度不符，3项CPU检查通过，仅供未来使用，未改执行快照/补跑。旧M1批次同SHA worker附加相同风险，原日志/计数不覆盖。
- 窗口外验证/落盘：repeat1约83.165s，repeat2约143.848s，瓶颈未完全解决。段首噪声上传提交Host包围88.953–94.088ms，后续中位0.032–0.054ms；保留段首违约，不能称纯GPU复制耗时或已定位驱动原因。新trace未执行，旧有效trace不冒充本批。
- scope日志RESTORED_FIVE_MINIMA，17:35:27独立只读核对五min为CPU各729600kHz/GPU306000000Hz/EMC204000000Hz，无匹配模型/干扰残留。所有完成段SATISFIED_SAMPLED，不扩为连续物理频率保证。
- 交付 `reports/m1_acceptance/dual_gate_20261015_v3/FINAL_REPORT.md`、带干扰安全限定的逐组合表/机会图、完整尝试账本及SHA。三重复整体INCOMPLETE，新trace NOT_RUN，安全配对/固定分区/真实净损失仍BLOCKED。M1未全验收、不选线、不进入M2，已停止。

## 历史：2026-10-15 下一步（当时状态；v10 已补配额曲线，路线由用户 2026-10-18 主动延期，M2 仍未启动）

> 以下为当时待办，不覆盖当前状态。

1. 审核`reports/m1_acceptance/M1_FINAL_REPORT.md`与最新矩阵：限定首周测量是否收口，负面结果原样接受。
2. 按任务书§2.3确认路线；主建议优先B2问题，不等于当前双块已有优势。未获用户确认前不选线、不进入M2。
3. 原始证据保留；不追加“最后一次”模型，不恢复历史Graph/Vision调查，不将尚未通过的全部G项扩为新首周前置。

> 以下为仍然有效的阶段交接约定（非历史记录）。

## 阶段交接约定

每个阶段结束时，先更新本文件，再生成阶段交接报告。报告至少包含：阶段目标与完成状态、硬件软件配置、原始数据和代码位置、正确性与公平性检查、已证实结论及其适用范围、失败实验、未解决问题、重大决策依据、下一阶段前置条件。不得将理论算例、历史 NX 数字或挑战目标写入“已取得结果”。
