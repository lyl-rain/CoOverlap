# 源码入口与阶段边界

> 2026-10-27 源码归档：`codex/week2` 逐项保留 M2/M3 源码的原始路径。`reports/` 下只有选定源码进入 Git，相关 JSON 配置、实验报告、原始数据和图不随源码分发；文中这些路径属于本地证据入口。归档范围见 `WEEK2_SOURCE_HANDOFF.md`。

## 当前：graph_prototype_v1_r1（真实接口/CPU准备；GPU NOT_RUN）

- `deployment/graph_backend.py`：真实 CUDAGraph API、真实句柄与设备地址检查、独立replay账本；`m2_pi05_ops.py`仅stream参数化；`m2_clean_cuda.py`共用复制/Event/bank路径与数学/审计接口。
- `graph_orchestrate.py`调用原`m3_b2_core.run_segment`，`pi05_graph_validation.py`复用已验收准备AST/D1；`graph_control.py`一次性托管、snapshot原值核对与两层读回；`graph_evaluate.py`声明分母统计。
- `CONFIG.json`/`DEPLOY_SHA256.txt`与34项payload，`tests/`用原生CUDA边界夹具；CPU30项通过；`DESIGN`/`REVISION`/`GPU_PLAN`/`BUDGET`/`FINGERPRINTS`列实现与未运行项。
- 模型、真实捕获/replay、SSH、部署、硬件写入、scope均0；仅PREPARED，不是GPU PASS。历史v1与B10冻结包保留。

## 历史：graph_prototype_v1（仅CPU接口草模，原完成口径已更正）

> 无真实模型/捕获/调度集成；见r1。

- `proto/graph_backend.py`（Graph 单元/注册表/replay 账本/假设备）、`proto/math_backend.py`（共享数学函数）、`proto/executor.py`（Eager/Graph 共用执行器，冻结 VersionedKV）、`proto/test_graph_cpu.py`（13/13）。
- `DESIGN.md`、`BUDGET.json`、`FAIRNESS_CHECK.json`、`GPU_PLAN.md`、`APPROVAL_CHECKLIST.md`、`RESULTS_TEMPLATE.json`、`FINGERPRINTS.json`、`MINIMAL_DIFF.patch`。
- 状态：原型/CPU 准备完成；Graph GPU 捕获、正确性、性能 NOT_RUN；执行包未构建。

## 当前补充：legal_schedule_gap_v1_r2（修正，CPU，2026-10-23）

- `reports/m3_b2/20261023/legal_schedule_gap_v1_r2/`：`lsg2/search.py` 无状态剪枝 DFS，monotonic / 核心内截止检查，判据 B 要求刷新通过；`transition.py` 增加 exact_times，`gap/inputs.py` 不用显示舍入作分类。
- `run_cpu.py` / `CPU_RESULTS.json`：19/19；真实碰撞 `COLLISION_REGRESSION.json`；小树递归对照与冻结默认路径等价均通过。
- `outputs/SEARCH_COVERAGE.json`：12 段均 WALL_CAP、0 COMPLETE、探索部分 0 改善；`DECISION.md` 为分支 4（截断、结论不足）。不生成 B11、不修改 GPU 原始数据或执行器。
- `GAP_SUMMARY.md`、`REVISION.md`、`MINIMAL_DIFF.patch`、`SOURCE_VERIFICATION.json`、`FINGERPRINTS.json`；共享文档修改前副本在 `before_docs/`。

## 历史：legal_schedule_gap_v1_r1（动作级搜索；完整性结论已撤回）

> 旧状态去重不保目标；以下 COMPLETE 为历史输出，不是穷尽证明。

- `lsg2/transition.py`（冻结调度器逐字副本 + `policy_fn` E/C/I/STOP 钩子，无钩子时逐事件等价）、`lsg2/search.py`（前缀重放 DFS、状态键去重、100k/10 s 上限）、`lsg2/run_search.py`、`lsg2/test_search_cpu.py`（7/7）。
- `outputs/{BASELINE_VS_SEARCH.csv,SCHEDULES.json,SEARCH_COVERAGE.json,RESIDUALS.csv}`、`GAP_SUMMARY.md`、`DECISION.md`、`RESIDUAL_CHECK.md`、`FINGERPRINTS.json`。
- 12/12 段 COMPLETE、0 改善；前一版 `legal_schedule_gap_v1` 仅全局策略族，保留为历史。

## 历史：legal_schedule_gap_v1（2026-10-23，全局策略族）

- `reports/m3_b2/20261023/legal_schedule_gap_v1/`：`gap/inputs.py`（12 段逐操作成本）、`gap/run.py`（4 策略对照与改善判据）、`gap/test_gap_cpu.py`（6/6）、`outputs/BASELINE_VS_SEARCH.csv`、`SCHEDULES.json`、`SEARCH_COVERAGE.json`、`RESIDUALS.csv`、`GAP_SUMMARY.md`、`DECISION.md`、`FINGERPRINTS.json`。
- 复用 `credible_plan_selector_v2_r1/cps2/model.py`（冻结调度器逐字副本 + 单实例时长钩子）与 `core.py`；未改任何冻结文件。
- 动作级 DFS 未实现，覆盖范围在 `SEARCH_COVERAGE.json` 显式标注。

## 当前：M3成果与验收审阅（2026-10-23，决策待确认）

- `reports/m3_b2/20261023/m3_stage_acceptance_review_v1/`：M3_STAGE_REVIEW.md（任务书对照/成果/缺口/四项建议）、ONE_PAGE.md、DECISION_RECORD.json（全部待用户确认）。
- `build_review.py`只读原始记录并复用冻结replay_stats/classify；METRICS_BY_CELL.csv、METRICS_BY_SEGMENT.json、VERIFY_RESULT.json记录7批52段核心统计重建0差异，不构成新GPU证据。
- TASK_REQUIREMENTS.json、EVIDENCE_INDEX.json、SOURCES.md为任务书原文与来源SHA/链接；原包、原数据、执行器均未改。
- 建议分项验收而非M3整体PASS；B2仍候选，不自动进入M4。


## 历史：B10 r1 执行与收口（2026-10-23，RUN / PASS(official)）

- `reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/`：冻结包（r1，59 项 CPU）。执行一次：`gpu_run_01/board/run_01/`（result.json `a4e66318…`）、`analysis/EVALUATION.json`、`closeout_eval/EVALUATION.json`（独立复算，逐字节一致）、`RUN_REPORT.md` + `RUN_REPORT.diff`、`RECOVERY_CHAIN.md`、`BACKUP_VERIFICATION.md`、`B10_CLOSEOUT.md`。
- 评价入口 `analysis/evaluate_b10.py`：A 正确性 / B 官方 / C 双预留 / D 推荐拒绝 / E 预测 / F 条件。
- 结论：官方 64/64/32 全 PASS；双预留全部满足；150 ms 模型拒绝为样本层面过度拒绝；微扰未实测。

## 历史：v2/B10 r1 集成修复（未执行GPU，已被执行取代）

- `reports/m3_b2/20261023/credible_plan_selector_v2_r1/cps2/`：integrity.py冻结来源条件/身份检查；core.py与run.py统一G0；S0–S3不再绕过缺证据。
- `reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/`：selection_contract.py共用入口/控制器身份合同；analysis/evaluate_b10.py六部分评价；freeze_package.py单一生成路径；run_cpu_checks.py本地核验。
- CPU22+32+5=59通过；预测480行、8段960次比较。REVISION.md、MINIMAL_DIFF.patch、FREEZE.json、CPU_RESULTS.json为交接依据。
- 仍PREPARED / NOT APPROVED / NOT RUN。B9为最近实测，B2候选、M3未全面验收、不进入M4。


## 历史：credible_plan_selector_v2 与 B10 准备（2026-10-23，PREPARED / NOT APPROVED / NOT RUN）

离线实现与准备；0 模型/worker/SSH/部署/硬件写入/scope。

- `reports/m3_b2/20261023/credible_plan_selector_v2/cps2/`：`core.py`（成本、轨迹、门禁、选择、微扰）、`model.py`（冻结调度器的逐字副本 + 单实例 `extra_ms` 钩子，等价性由测试保证）、`run.py`（S0–S3 消融与输出）、`test_cps2_cpu.py`（14/14）。
- `outputs/`：`RULES.json`、`COSTS.json`（B9 主来源 + B8 历史，条件映射与“目标未测量”声明）、`PERTURBATION.json`（160/150 各 80/96 场景）、`ABLATION.csv`、`SELECTION.json`；`SUMMARY.md` 给出消融表与 M3 证据状态。
- `reports/m3_b2/20261023/credible_selector_validation_b10_v1/`：`deployment/m3_b10_plan.py`（160/150 矩阵）、CONFIG/BUDGET、`prediction/PREDICTION.json` + `SELECTION_FREEZE.json`（B9 180/140 两来源）、`GPU_PLAN.md`、`APPROVAL_CHECKLIST.md`、`EVALUATION_PROTOCOL.md`、`FREEZE.json`。
- 待审：B10 的 CPU 校验器与评价入口尚未按 B10 协议适配（当前为 B9-r2 重命名副本），不声称可执行。

## 历史：B9 前瞻验证批修订 r2（2026-10-23，已执行并收口）

离线修订 + 针对性 CPU 核验；0 模型/worker/SSH/部署/硬件写入/scope。v1、r1 保留，r2 在 `reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/`。设计不变（RE=10 ms、A/B/C/D、8 周期/4 刷新、1 进程 + 1 scope、170/180+10/420 s、0 重试）。M2 已验收；M3 未全面验收；B2 候选；不进入 M4。

- `analysis/evaluate_b9.py`：新增 `declared_rows()`，按冻结 CONFIG 生成未执行段的声明义务（8 Expert/8 Cycle/4 Refresh/按 plan 块，全 INCOMPLETE、余量与完成时间 None）；`segment_official(segment, declared)` 以 CONFIG 为身份来源，预创建 `NOT_STARTED`（无 manifest/t0）不再当结构损坏，身份冲突或“有作业无 manifest”仍 `INVALID_EVIDENCE`；`official_summary()` 所有 row 都带 cell/plan/period，分母恒 64/64/32；`condition_check()` 仅在 8 段全部执行时比较 phase/cycles/binding/block_plan/retention，否则记 UNKNOWN 并输出 `not_started`，排序用 `(x is None, str(x))` 键；`compare_segment()` 增加 `completion/response_exceedance = actual − predicted`，stress 只统计 `>0` 并输出正超出量；`reserve` 输出 `short/satisfied/unknown/total`，未开始段的缺失余量既不算不足也不算满足；`prediction_status` 在仅部分记录时为 `NOT_EVALUABLE`。
- `tests/fixture_b9.py`：按真实入口形状预创建 8 段记录（`index/cell/plan/policy/period_ns/segment_id/status=NOT_STARTED/planned_*`），执行段再合并 manifest/t0/作业；提供 `set_expert_completion`/`predicted_stress` 便于方向反例。
- `tests/test_evaluate_b9_cpu.py`（19 项）：B8 真实数据 64/64/32；5 完成 + 3 真实 NOT_STARTED（24/24/12 INCOMPLETE）；全 NOT_STARTED CLI；身份冲突 INVALID + 退出码 2；stress ±10 ms 与相等；条件不匹配保留数值评价；冻结篡改被拒。
- `tests/path_summary.py` → `CPU_PATHS.md`：正常 / 5+3 / 全未开始 / 条件不匹配四条路径的退出码、verdict、条件、预测状态、Expert/Refresh 计数与预留计数。
- `tests/run_cpu.py`：结构 56 + 评价 19 = **75/75**，写 `CPU_RESULTS.json`/`CPU_TESTS.log`。
- 冻结：CONFIG `6af4210da8df42b004c50169823ba4ba94d42cc7bbad283839ac6d2e44a04cc3`、DEPLOY `f3b4f1b0742721a0af1b45cb5fbde177910059ef50d0f7bf73d4684f7ec591c0`、PREDICTION `301726555eeefa43337d447803365778fe7fd3f0388d03cade7539fb99a53c49`、SELECTION `6503989f40577b358749b3cc01d0b0c774dc84220354e2d780738035fb31ffdf`、评价器 `1f741badf658ec6800787c3bab8b6e4a08fd172443af48382fe690f1d517d7c2`。预测、选择冻结、入口、控制器与 r1 逐字节相同；plan 仅 `ANALYSIS_MODULES` 变化。
- `gpu_run_01/`：run 01 归档与报告。`RUN_REPORT.md`（A/B/C 三部分）、`APPROVAL_RECORD.json`、`analysis/EVALUATION.json`、`board_small/model/result.json`（SHA `d314f69b…`）；整包 4.8 GB 回传与 `LOCAL_SHA256.txt` 由采集器完成。执行：1 模型（45.97 s）+ 1 scope（48.53 s，restored），278/278 检查、D1 逐字节、两 gate PASS。
- 收口件：`CORRECTION_MATRIX.md`（5 项修正：失败组归属 group 0、C 的 UNCERTAIN 区间、规则 MC/ME/MR 口径、6/16 拆分、Expert-only 预留列表）、`gpu_run_01/corrections/`（`reserve_correction.py` 只读重建、`EVALUATION_CORRECTED.json`、6 项定向 CPU 测试、`SHA256.txt`）、`B9_CLOSEOUT.md`、`gpu_run_01/BACKUP_VERIFICATION.md`、`BOARD_FILES.txt`/`BOARD_SHA256.txt`/`LOCAL_SHA256.txt`。
- 状态：**RUN / PASS(correctness)**；140 ms 冻结推荐未获前瞻可行性支持。性能与预测见 `gpu_run_01/RUN_REPORT.md`，收口结论见 `B9_CLOSEOUT.md`。见 [REVISION.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/REVISION.md)、[GPU_PLAN.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/GPU_PLAN.md)、[APPROVAL_CHECKLIST.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/APPROVAL_CHECKLIST.md)、[FREEZE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/FREEZE.json)、[CPU_RESULTS.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/CPU_RESULTS.json)、[CPU_PATHS.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r2/CPU_PATHS.md)。

## 历史：B9 前瞻验证批修订 r1（2026-10-23，已被 r2 取代）

离线修订 + CPU 核验；0 模型/worker/SSH/部署/硬件写入/scope。v1 保留，r1 在 `reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/`。**实验设计不变**（RE=10 ms、A/B/C/D、顺序、8 周期/4 刷新、1 进程 + 1 scope、170/180+10/420 s、0 重试）。M2 已验收；M3 未全面验收；B2 候选；不进入 M4。

- `prediction/prediction_model.py`：预测生成与补齐（只读冻结 B8 成本 + r1 规则）。`build_jobs` 产出 Expert/Context块/Cycle/Refresh × typical/stress 的逐作业行（release/deadline/dispatch/completion/response/margin/status/版本/义务组），`boundary_rows` 产出释放点距离，`completeness` 检查缺失字段。生成器与评价器共用同一代码，避免两套预测。
- `prediction/build_b9_prediction.py`：冻结 `PREDICTION.json`（schema v2，240 行）与 `SELECTION_FREEZE.json`；不读任何 B9 数据。
- `analysis/evaluate_b9.py`：三部分评价。B 部分逐段调用冻结 `replay_stats`，Expert 用冻结 `classify` 且 completion 与 deadline 分开；缺失 completion→INCOMPLETE、区间跨 deadline→UNCERTAIN、非法区间→INVALID；分母取 CONFIG 声明义务（64/64/32），未开始段整体 INCOMPLETE。C 部分把冻结预测与实测逐作业比较（齐全性双向、次序与首次分歧、版本、completion/response 误差、deadline 状态、误判可行/不可行、stress 超出、预测满足预留而实际不足），并逐字段判定条件（MATCH/MISMATCH/UNKNOWN）。`verify_frozen` 校验 CONFIG/规则/成本/预测/selection/分析模块，不一致 → `INVALID_EVIDENCE`，CLI 退出 2。
- `tests/fixture_b9.py`、`tests/test_evaluate_b9_cpu.py`、`tests/run_cpu.py`：B9 结构夹具（`fixture: true`）与 15 项评价链反例；`run_cpu.py` 合并结构 56 + 评价 15 = **71/71**，写 `CPU_RESULTS.json`。
- `freeze_docs.py`：从最终文件一次性生成 `APPROVAL_CHECKLIST.md` 的完整 SHA 表并写 `FREEZE.json`（30 项）。v1 的摘要不一致（`ba7fa9a7…`/`45729522…` 对本地 `3549c671…`/`df07e42f…`）已查明为不同构建版本的手写摘要混用；r1 不再手写。
- 冻结：CONFIG `4db22946c2baad42df5d59ea59d5bf53a1226b2646043ed59c7688123025e7f4`、DEPLOY `04d292807e8d7c4d0dba7ee1f5a99dd564a41b3d23e647aedcd645e01d5cfbde`、PREDICTION `301726555eeefa43337d447803365778fe7fd3f0388d03cade7539fb99a53c49`、SELECTION `6503989f40577b358749b3cc01d0b0c774dc84220354e2d780738035fb31ffdf`、评价器 `d3efaa64d18e3fd313d1f21a4195c72888e1117a7c1b0657fe2efe3cd754ffc1`。
- 状态：**PREPARED / NOT APPROVED / NOT RUN**。见 [REVISION.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/REVISION.md)、[GPU_PLAN.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/GPU_PLAN.md)、[APPROVAL_CHECKLIST.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/APPROVAL_CHECKLIST.md)、[FREEZE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/FREEZE.json)、[CPU_RESULTS.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1_r1/CPU_RESULTS.json)。

## 历史：Expert 预留验证批 B9 准备 v1（2026-10-23，已被 r1 修订包取代）

离线准备 + CPU 核验；0 模型/worker/SSH/部署/硬件写入/scope。未获新批准不得执行。M2 已验收；M3 未全面验收；B2 仍候选；不进入 M4。

- 目录：`reports/m3_b2/20261023/expert_reserve_validation_b9_v1/`；协议 `m3_b9_expert_reserve_validation_v1`。
- 选择器修订：`reports/m3_b2/20261023/expert_reserve_selector_v1_r1/`（v1 保留）。`ers/select.py` 修两处——缺声明候选 → `INSUFFICIENT_EVIDENCE`；`lifecycle_ok=False` → 不可行不可选；`RULES.json` 规则 ID 改 `…_r1`，RE/成本/顺序不变。**37/37 PASS**，B8 选择不变（CSV 逐字节相同）。
- `deployment/m3_b9_plan.py`：四 cell、A,B,C,D,D,C,B,A、8 周期/4 刷新、每预算 canonical manifest；新增 `prediction`/`selection`/`reserve` 身份块（SHA 与预算→推荐映射）。
- `deployment/pi05_m3_b9_validation.py`：B8 入口的 B9 副本；新审批 flag 与 `COOVERLAP_APPROVED_BATCH` 令牌；运行前校验 `SELECTION_FREEZE.json` 的 SHA/指纹，并把该预算的冻结推荐写入**每个段记录**（`selection`/`selection_fingerprint`/`reserve_ms`），赛后校验其未被改写。**推荐不改变执行计划**：`run_candidates` 只被调用一次，固定矩阵两个预算都跑两个候选。
- `deployment/m3_b9_control.py`：preflight / 唯一 submit / scope / verify-restored；五节点事务沿用；systemd unit 与文件名改为 B9，要求新 flag 与精确 credential SHA。
- `deployment/validate_m3_b9_cpu.py`：**57/57 PASS**（协议/凭据/入口、8 段顺序、预算与 plan 驱动 manifest、冻结推荐 SHA 与可复算、禁止回写成本/规则、S0/S10 不重复分母、条件不匹配不伪造 SELECTED、性能失败继续、正确性/资源/截止停止、公平/留存、失败归属、缺失不填零、部署清单与语法）。
- `deployment/build_manifests.py`：写 CONFIG/BUDGET/FAIRNESS/COMPATIBILITY 与 `DEPLOY_SHA256.txt`；并用 B8 plan 做“去 schema 后 manifest 逐字节相同”的兼容核对。
- `prediction/`：`build_b9_prediction.py` 只读 B8 冻结成本 + r1 规则，产出 `PREDICTION.json`（逐作业余量、派发次序、版本、释放点距离、S0/S10）与 `SELECTION_FREEZE.json`（段前记录用）。
- `analysis/evaluate_b9.py`：赛后离线三部分评价（A 正确性 / B 官方性能 / C 选择与预留）；`condition_status()` 决定 `MATCH` / `CONDITION_MISMATCH`，域不匹配时记 `INSUFFICIENT_EVIDENCE`，不伪造 SELECTED。
- 冻结（`FREEZE.json`）：CONFIG `ba7fa9a7…`、DEPLOY_SHA `45729522…`、PREDICTION `62e6c476…`、SELECTION_FREEZE `f251e438…`、RULE `1e46e495…`、COSTS `ebee939d…`、B8 result `1d48e537…`、B8 prediction `d7b41775…`、plan_model `2ee21ef1…`、executor `7890fa54…`。
- 状态：**PREPARED / NOT APPROVED / NOT RUN**。方案 [GPU_PLAN.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/GPU_PLAN.md)、审批 [APPROVAL_CHECKLIST.md](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/APPROVAL_CHECKLIST.md)、模板 [RESULTS_TEMPLATE.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/RESULTS_TEMPLATE.json)、CPU [CPU_RESULTS.json](../reports/m3_b2/20261023/expert_reserve_validation_b9_v1/CPU_RESULTS.json)。

## 历史：Expert 预留约束的计划选择与回顾性消融（2026-10-23，离线 + 回顾性）

离线/CPU，无模型、worker、SSH、部署、硬件写入或 scope。**M2 保持已按约定范围验收完成**（本轮不重跑）。规则（RE=10 ms）在 B8 之后提出，属回顾性设计与评价；不改生产执行器、历史冻结包、原始数据、B8 冻结预测或 r1 选择器的适用域。B2 仍候选，M3 未全面验收，不进入 M4。

- 目录：`reports/m3_b2/20261023/expert_reserve_selector_v1/`；状态 `RETROSPECTIVE_SELECTION_RESEARCH`；命令 `python3 ers/cli.py all`。
- `ers/common.py`：路径与复用接线——把 `release_boundary_evaluator_v1/rbe` 的 `env`（冻结输入 SHA 与导入接线）、`costs`（逐 cell 成本）、`replay`（冻结模型重放）、`audit`（实测作业表）接进来；本包不重写成本提取、执行器或统计。
- `ers/rules.py`：`RULES.json` 的生成与校验；RE=10 ms 的身份字段（非任务书、非 WCET、非安全界、官方 deadline 不变、轮内不可调）。
- `ers/select.py`：纯函数选择器——`summarize_candidate` 把两场景折成 MC/ME/MR 并派生 `feasible`（MC/ME/MR≥0 且完整、无 lifecycle 错误）；`select` 按“义务/官方 deadline → ME≥RE（**按本次决策的 RE 求值**）→ 块数最少 → MC 大 → 稳定 ID”返回五类状态；`fixed` 只报告固定方案的可行性与预留，不做选择。
- `ers/ablation.py`：逐预算构建候选证据（B8 自身成本，typical/stress 分场景）、实测指标、逐作业预留与“预测不足 vs 实际不足”计数；实测侧不回调规则。
- `ers/cli.py`：`freeze`（RULES/COSTS/EVIDENCE_CATALOG）、`select`、`ablate`、`fingerprints`、`all`。
- 结果（回顾性）：180 ms S0=S10=`two_9_9`（未改变）；140 ms S0=`two_9_9`、S10=`three_prefix_9_9`（**改变**）。140 ms 实测最小 Expert 余量 2.551→24.322 ms、预留不足作业 8/16→0/16、官方均 16/16 周期与 8/8 刷新；代价为最小周期 2.551→1.934、最小刷新 82.821→82.131 ms、每刷新边界 3→4、留存 64→76 entry。
- 复用与等价：S0 与 F2 完全相同（等价，复用同一记录，不重复分母）；S10@180 复用 F2、S10@140 复用 F3，逐行标 `reused_from`/`equivalent_to`；本轮**没有**选择器 GPU 运行。
- CPU：`ers/test_ers_cpu.py` **31/31 PASS**（ME=10 边界、预留足但周期/刷新失败、可行但预留不足、少块选择、仅三块满足时改选、单候选不可行、缺证据/条件不匹配、RE=0≡F2、规则不看实测、冻结 SHA 不变）。
- 状态：M2 已验收；M3 未全面验收；B2 候选；不进入 M4。详见 [MAINLINE_RESULT.md](../reports/m3_b2/20261023/expert_reserve_selector_v1/MAINLINE_RESULT.md)、[RULES.json](../reports/m3_b2/20261023/expert_reserve_selector_v1/RULES.json)、[ABLATION.csv](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/ABLATION.csv)、[FINGERPRINTS.json](../reports/m3_b2/20261023/expert_reserve_selector_v1/outputs/FINGERPRINTS.json)。

## 历史：M3 释放点敏感的计划评价（2026-10-23，离线方法 + 回顾性分析）

离线/CPU，无模型、worker、SSH、部署、硬件写入或 scope。**M2 保持已按约定范围验收完成**（本轮不重跑）。不修改生产执行器、历史冻结包、原始数据与 B8 运行前预测。B8 执行正确性 PASS 与预测失败（`CONDITION_MISMATCH`）同时保留；B2 仍候选，M3 未完成，不进入 M4。

- 目录：`reports/m3_b2/20261023/release_boundary_evaluator_v1/`；状态 `OFFLINE_ANALYSIS_ONLY`。同日工作快照 `reports/m3_b2/20261022/release_boundary_evaluator_v1/` 保留并标 `SUPERSEDED.md`，不覆盖。
- `rbe/env.py`：冻结输入身份（`FROZEN_SHA256` 含 B8 `result.json`、`PREDICTION.json`、r1 costs/rules/freeze/plan_model、frozen `m2_executor.py`），不一致直接抛错；`prepare_imports()` 只把 r1 `selector/` 与 B4 冻结 deployment 加入 `sys.path`。
- `rbe/costs.py`：两个**不混池**的成本对象——`b4_source`（冻结 r1 表，`OTHER_S0_0c63ddfb1c91`）与 `b8_measured`（逐 cell 从该 cell 自身 `operations.GPU_total_envelope_ms` 提取，`H_frozen`，回顾性）；`BLOCK_KEY`/`BLOCK_KIND` 分离操作名（`R{q}/B1..B3`）与声明 kind（`P/B1/B2`），三块尾块是 **B3**。
- `rbe/audit.py`：从原始 `decisions/blocks/experts/published/journal/operations/progress` 重建每个合法决策边界——决策 Host 时刻、完成确认开销、已释放可运行/版本未就绪队列、下一未派发 Expert 的 release/deadline/版本证据、`release-boundary distance`、以及该边界的实际选择与备选；对冻结预测用同一套重建（预测侧无 Host 确认项，单独标注）。绑定版本取自 journal `bind`。
- `rbe/replay.py`：`replay_b4` 用冻结 r1 成本重放（逐值复现冻结预测，作为完整性校验）；`replay_b8` 用该 cell 自身成本重放，只作回顾性解释；`compare` 给出派发次序与完成误差。
- `rbe/sensitivity.py`：在明确边界上，只改**前序 Expert E(2q)** 的耗时，用派发次序作判据二分出临界 Δ；再以 1 ns 生成释放点前/后两条可执行轨迹（仍由冻结 `VersionedKV` 驱动）。构造记录操作归属、Δ、是否在已观察范围内（`SENSITIVITY_CONSTRUCTION`）、未覆盖项；同时给出“全操作取该格观测最大值”的 `stress_envelope`。
- `rbe/evaluation.py`：两块/三块的逐预算评价与证据类别（`EMPIRICALLY_FEASIBLE` / `MODEL_FEASIBLE_*` / `SENSITIVE_TO_CHECKED_CONSTRUCTION` / `INSUFFICIENT_EVIDENCE_FOR_RATE`），不合并成单一结论。
- `rbe/cli.py`：`audit`/`replay`/`sensitivity`/`evaluate`/`fingerprints`/`all`；只写 `outputs/`。
- 输出：`BOUNDARY_AUDIT.csv`（528 行=176 实际+176 预测×2 场景，覆盖 32 次刷新）、`REFRESH_COVERAGE.csv`（32 刷新）、`DEADLINE_MARGINS.csv`、`MARGIN_IDENTITY.csv`（32/32，**仅当前 manifest 与这些完成依赖下**成立：`release_distance = cycle 余量 − 确认开销`，非通用恒等式）、`ORDER_FLIPS.csv`（32 条，仅 140 ms）、`BOUNDARY_CRITICAL.csv`、`REPLAY.json`、`SENSITIVITY.json|csv`（16 组两支构造）、`PLAN_EVALUATION.json|csv`、`FINGERPRINTS.json`。
- CPU：`rbe/test_rbe_cpu.py` **30/30 PASS**（释放点前/相等/后、Expert 已完成/未释放/已释放但版本未就绪、队列与未来到达不混淆、区间跨释放点标 UNCERTAIN、耗时变化改次序而释放与 deadline 不变、翻转后工作量/依赖/版本/读者合法、Expert 提前但刷新推迟不误报改善、缺记录不填零保留分母、B4/B8 不混池、冻结输入 SHA 不变）。
- 结果边界：140 ms 两块/三块均出现派发次序翻转（实测距离 +2.54…+4.18 / +1.91…+3.23 ms，预测 −0.04…−1.17 / −0.41…−2.04 ms），180 ms 0/16；翻转阈值 3.20/2.51 ms，翻转使发布晚 **≈72 ms 但刷新仍按时**（构造 199.670→271.605 / 199.655→271.743 ms，deadline 280 ms），失败的是偶数周期与（两块的）E0——**Expert/周期/刷新分别判定**。本批已观察轨迹与已检查的同条件最大值构造**未跨过**释放点（余 +2.49/+1.74 ms），但这不是同条件波动的上界；B4 源与 B8 的 Expert 中位差 3.32/3.05 ms 只是数值对应，**不作因果归因**，底层原因未知。B8 该批 0/64 周期、0/32 刷新（只作 0/n，非零风险）；**B5 180 ms 有有限配对收益（8/16 对 0/16）**，**B6 180 ms boundary 非零违约（周期 28/32、刷新 12/16）**；不同批次不合并成总体率。M3 验收差距见 [M3_ACCEPTANCE_GAP.md](reports/m3_b2/20261023/release_boundary_evaluator_v1/M3_ACCEPTANCE_GAP.md)，复核与恢复见 [reconciliation](reports/m3_b2/20261023/reconciliation/)。
- B8 报告表述更正：`RUN_REPORT.md` 一句（140 ms 周期余量 1.934–2.551 ms；Expert 余量两块 2.551/三块 24.322 ms），统计未改，副本+diff 在 `B8_REPORT_CORRECTION/`。

## 历史：M3 split × budget challenge b8（2026-10-22，RUN + PASS / 预测条件不匹配）

唯一一次模型 + 一次五节点 scope 已执行：模型 76.680 s、scope 78.600 s、261/261 checks PASS、restored/独立读回 PASS、无残留。B2 仍候选，M3 未完成，不进入 M4。

- 目录：`reports/m3_b2/20261022/split_budget_challenge_b8_v1/`；协议 `m3_b8_split_budget_challenge_v1`。
- 矩阵：A two/180、B three/180、C two/140、D three/140；顺序 A,B,C,D,D,C,B,A；每段 8 周期/4 刷新；同预算配对，跨预算非同一墙钟轨迹；无 serial 对照。
- `deployment/m3_b8_plan.py`：四条件、每预算 canonical manifest、预算/工作/兼容性/公平性/预测身份。
- `deployment/pi05_m3_b8_challenge.py`：实际入口；每段 `confs=manifests()[P]`，并传 `expects=manifest(P)` 作为 canonical 期望；记录预测身份但窗口内不评价。
- `deployment/m3_b3_orchestrate.py`：唯一共享运行时修改；`run_candidates` 新增可选 `expects`，在 `run_segment` 前核对段 manifest 与本批 canonical manifest。
- `deployment/m3_b8_control.py`：preflight/一次 submit/scope/独立读回复用 v6 五节点事务；新协议、新 token、`run_01` only。
- `deployment/validate_m3_b8_cpu.py`：**17/17 PASS**；复用 B3/B4/B5 符号设备/夹具，覆盖四条件、8 段顺序、两块/三块义务、140 ms 队列/积压/版本/读者、性能 FAIL 继续、总截止 INCOMPLETE、首/中段失败归属、预测域/时间原点、配置/入口/凭据一致性。
- `prediction/`：`predict_b8.py` 复用 r1 冻结成本/规则/模型，仅改 P；`PREDICTION.json` 状态 `EXTRAPOLATIVE_PREDICTION_NOT_VALIDATED`、条件 `OUT_OF_SOURCE_APPLICABILITY_DOMAIN`；r1 正式域仍拒绝 180/140 正式选择。`EVALUATION_PROTOCOL.md` 固定事后比较口径（无容差、无 prediction PASS）。
- 交付：`GPU_PLAN.md`、`APPROVAL_CHECKLIST.md`、`RESULTS_TEMPLATE.json`、`BUDGET.json`、`FAIRNESS_CHECK.json`、`REUSE_AND_DIFF.md`、`MINIMAL_DIFF.patch`、`FREEZE.json`。
- 实际执行：A/B/C/D/D/C/B/A 全 8 段 PASS；**64/64 周期、32/32 刷新 PASS**；min cycle/Expert/refresh：A 41.921/41.921/162.200 ms、B 40.587/91.303/157.805、C 2.551/2.551/82.821、D 1.934/24.322/82.131；各格 backlog_max=1、ready_experts_max=1、version_wait_rows=0、deferred=0。
- 预测比较：180 ms order/version/status 全部匹配，误差 max 10.8 ms；140 ms 预测判不可行但实际 16/16+8/8 PASS，false infeasible C 16/16、D 8/8，order mismatch，completion max 81.7 ms，stress Expert 超出 34–37.5 ms。实际条件为 `CONDITION_MISMATCH`：B4 成本来源 `OTHER_S0`，B8 实际 `H_frozen`（S0 context SHA 不同）；不是原条件下预测验证，预测失败不是执行器正确性失败。
- 结果/停止：正确性 PASS；性能/预测负面结果保留；每条件两段同进程、非独立重复；不支持长尾/违约率/WCET/k_min/最终切分/serial 收益/M4。结果 [RUN_REPORT.md](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/RUN_REPORT.md)、[PREDICTION_COMPARISON.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/analysis/PREDICTION_COMPARISON.json)、[BACKUP_VERIFICATION.json](reports/m3_b2/20261022/split_budget_challenge_b8_v1/gpu_run_01/BACKUP_VERIFICATION.json)。

## 历史：M3 实测驱动计划选择器 r1（分析基线，保留）

> r1 是 b8 预运行预测的成本/规则/模型来源；其正式适用域未被 b8 修改。v1 原目录保留。

### r1 实现记录（2026-10-22）

B7 的运行与收口仅作历史。r1 当时是 **offline empirical plan selector r1**：无模型、worker、SSH、部署、scope 或硬件写入；不修改生产执行器/历史冻结包/原始数据。v1 原目录保留。

- 新目录：`reports/m3_b2/20261022/empirical_plan_selector_v1_r1/`。
- `selector/plan_model.py`：复制已修正模型，SHA `2ee21ef1…`；直接驱动 B4 冻结 `m2_executor.py`（SHA `7890fa54…`），生产执行器不导入选择器。
- `selector/evidence.py`：B4 pass 1 B/D 原始 operation Event total、stage Host 启动；新增结构化 condition（period/phase/cycles、lead、pressure、数值 configuration、输入/checkpoint/精度、版本消费、义务分组、留存/观测、clock limits）及指纹；无法取得字段标 UNKNOWN。
- `selector/evaluator.py`：固定释放/冻结 VersionedKV 时间线；三类 margin；刷新显式区分 `completion_offset_ms`、`refresh_response_ms`、`refresh_margin_ms`，最大刷新响应只取 `refresh_response_ms`。
- `selector/selection.py`：两候选、typical/median + stress/sample-max、非支配输出；条件必要字段缺失/不匹配 → INSUFFICIENT_EVIDENCE；域外/未识别目标参数 → UNSUPPORTED_INPUT；一候选不可行不删除另一可行候选；全部候选不可行才 NO。
- `selector/freeze.py`：冻结 costs/rules/condition/catalog/selection，并写 `FREEZE.json`（7 个分析模块、executor、9 项输入）。
- `selector/validate.py`：显式接收 `--freeze`，评价前校验清单；不一致拒绝且不创建输出；不重写清单。B4 pass 2 为**第一遍成本提取、第二遍分离评价的回顾性检验**，completion 与 deadline 匹配分列。
- `selector/supplemental.py`：B5/B6/B7 自身条件 sample-in-batch；不进入 B4 选择。
- CPU：`selector/test_selector_cpu.py` **30/30 PASS**；含刷新时间原点、条件/freeze 拒绝、冻结规则目标不相容、NO/INCOMPLETE、Expert 完成/时限分列等反例；0 GPU/模型/worker/SSH/hardware/scope。
- 结果：P240 两候选均可行、非支配；two max refresh response **200.868 ms**、three **201.880 ms**；旧 1640.709/1641.690 ms 仅作完成偏移；三块只有有限 Expert 结论；P180 为 INSUFFICIENT_EVIDENCE。B2 仍候选，M3 未完成，不进入 M4。

## 历史：M3 实测驱动计划选择器 v1（2026-10-22，已被 r1 取代）

> 历史原文保留。v1 的 `max_refresh_ready_ms` 实为完成偏移，不是最大刷新响应；v1 的 28/28、32/32 是合并 job/status 匹配，不是时限分类。r1 已修正。

### v1 实现记录（2026-10-22）

v1 当时是 **offline empirical plan selector**：无模型、worker、SSH、部署、scope 或硬件写入；不修改生产执行器/历史冻结包/原始数据。

- 新目录：`reports/m3_b2/20261022/empirical_plan_selector_v1/`。
- `selector/plan_model.py`：复制已修正 `plan_feasibility_v1_r1/plan_model.py`，SHA `2ee21ef1…`；直接驱动 B4 冻结 `m2_executor.py`（SHA `7890fa54…`），非生产执行器导入。
- `selector/evidence.py`：B4 pass 1 B/D 原始 operation Event total、stage Host 启动、条件/SHA；不按层均分，不混 B5/B6/B7。
- `selector/evaluator.py`：固定释放/冻结 VersionedKV 时间线；三类 margin；startup 只在首次/后续 stage 的实际位置进入一次。
- `selector/selection.py`：两候选、typical/median + stress/sample-max、非支配输出；状态 EMPIRICALLY_FEASIBLE / NO_EMPIRICALLY_FEASIBLE_PLAN / INSUFFICIENT_EVIDENCE / UNSUPPORTED_INPUT。
- `selector/freeze.py`、`selector/validate.py`：先冻结成本/规则/模型，再读 B4 pass 2 D/B；`VALIDATION_RECEIPT.json` 记录顺序。
- `selector/supplemental.py`：B5/B6/B7 自身条件 sample-in-batch；不进入 B4 选择。
- CPU：`selector/test_selector_cpu.py` **13/13 PASS**；无 GPU/模型/worker/SSH/hardware/scope。
- 结果：P240 两候选均可行、非支配；two 周期/刷新余量更好，three Expert 余量更好；无三块完整周期/刷新优势证据；P180 为 INSUFFICIENT_EVIDENCE。B2 仍候选，M3 未完成，不进入 M4。

## 历史：B7 stage-startup（2026-10-22，RUN + PASS diagnostic）

B7 已执行一次：1 模型 + 1 scope，0 压力 worker、0 retry。A=10 ms、B=4 s；A 16/16+8/8，B 14/16+6/8；B cycle0 VLM 与 R0 refresh 失败。22 个 Host 时间戳进一步定位 B 首次延迟到 Event0 record Host 包络（B 99.47/99.53%，A 8.42/8.11%）；底层机制未知，B7 定位不是 B6 直接子调用测量。B6 r1 的实际执行证据保留在下方历史段。

- 协议：`m3_b7_stage_startup_v1`；A lead 10 ms、B lead 4 s；两条件 quiet/b2_boundary/two_9_9/180 ms，顺序 A,B,B,A，4 段，每段 8 周期/4 刷新；0 压力 worker，0 retry。
- 入口：`scripts/pi05_m3_b7_stage_startup.py`；plan：`scripts/m3_b7_plan.py`；control：`scripts/m3_b7_control.py`；观测：`scripts/m3_b7_stage_observe.py`。
- 共用窗口：`scripts/m3_b6_window.py.SegmentWindow` 新增可选 `lead_ns`，B7 两条件都走它；默认 B6 仍 4 s。
- 阶段观测：`BoundaryBackend.stage`/`CleanBackend.stage`/`CudaDevice` 的可选 observer 钩子，只有 B7 传入；B6 无 observer 路径保持默认。
- 工作/预算：32C/38E；观察 29C/37E = 7,240 行；4×64/487,320,064 B；磁盘 3,342,248,562 B（3.11 GiB）；内部 170 s、外层 180+10 s、scope 420 s；B6 推导投影 54.457 s（非保证）。
- CPU：`scripts/validate_m3_b7_cpu.py` **25/25 PASS**；B6 `scripts/validate_m3_b6_cpu.py` **37/37 PASS** 回归；均无 GPU/model/worker/SSH/hardware/scope。
- 冻结：`reports/m3_b2/20261021/stage_startup_b7_v1/deployment/` 35 文件；[GPU_PLAN.md](reports/m3_b2/20261021/stage_startup_b7_v1/GPU_PLAN.md)、[APPROVAL_CHECKLIST.md](reports/m3_b2/20261021/stage_startup_b7_v1/APPROVAL_CHECKLIST.md)、[FREEZE.json](reports/m3_b2/20261021/stage_startup_b7_v1/FREEZE.json)、[RESULTS_TEMPLATE.json](reports/m3_b2/20261021/stage_startup_b7_v1/RESULTS_TEMPLATE.json)。
- 结果：B7_RUN_REPORT/B7_ANALYSIS/B7_STAGE_TIMELINE；首次 stage A 0.748–0.751 ms、B 93.328–94.008 ms；B 的失败保留；Event0 Host 可观测区间已定位，底层根因未知，不修正。
- 离线收口：`corrections/analyze_b7_stage_intervals.py`（read-only，输入/输出显式），16 stage 区间 CSV/JSON/MD，targeted CPU 7/7；原始 result SHA `17c17c33…` 与冻结 source `a5c968f0…` 未变。B2 仍候选，M3 未完成，不进入 M4。

## 历史：b6 r1 实际执行（2026-10-21，RUN + PASS protocol）

状态：**RUN + PASS_IN_PROCESS_CONTROLLED_INTERFERENCE_V1**；协议/正确性/留存/恢复 PASS，性能违约和 boundary refresh 负面结果如实记录。B2 仍候选，M3 未完成，不进入 M4。

- 部署 SHA `96a1c748…` 执行一次：1 模型 + 1 scope、0 重试；模型 83.853 s、scope 86.602 s、scope restored/readback PASS。
- 8 段 A,B,C,D,D,C,B,A；257 checks；D1 byte exact、gates 22/24、52C/70E、13,400 ledger、每段 64 entry/487,320,064 B 留存、worker conditions 8/8 valid。
- 周期 PASS：A 8/16、B 14/16、C 8/16、D 14/16；刷新 PASS：A 8/8、B 6/8、C 8/8、D 6/8。A/C 为 cycle 0/2/4/6 Expert 违约；B/D 为 cycle 0 VLM + R0 refresh 违约（refresh deadline 360 ms）。
- fixed worker：4 个 C/D/D/C，copies 598/598/595/598、2,389/80,161,538,048 B logical；guards/affinity 11/资源/coverage 全 PASS；worker loop 在 declared end 后 2.063–3.129 ms 退出，保留为观察边界。
- 结果：[RUN_REPORT.md](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RUN_REPORT.md)、[RUN_ANALYSIS.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RUN_ANALYSIS.json)、[RUN_SUMMARY.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RUN_SUMMARY.json)、[EXECUTION.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/EXECUTION.json)、[RESTORE_COMPARISON.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/RESTORE_COMPARISON.json)、[BACKUP_VERIFICATION.json](reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/BACKUP_VERIFICATION.json)。
- 原始数据：本地 192 文件/4,649,349,033 B；192 文件 SHA 全通过；root snapshot 可读副本 SHA `22b1b679…`；B5 历史 board 191/4,649,192,413 B 未改。
- 边界：两遍非独立重复；n=8 无可靠尾；copy_bytes 非 DRAM 带宽；无 k_min/因果/最终路线/M4 声明。

## 历史：b6 r1 PREPARED（2026-10-21，CPU only）



状态：**r1 准备包已冻结；未部署、未批准、未运行。** 模型、真实压力 worker、SSH、硬件写入、scope 均为 0。

- 协议/设计不变：`m3_b6_controlled_interference_v1`；A/B/C/D 与顺序、工作量、预算、worker r1 历史包均不改。v1 原包保留，r1 只修收尾。
- 修复：`run_candidates` 用 `window_resource_safety()` 区分资源已释放与未确认；资源安全但覆盖/工作证据无效时允许一次全量校验/保存，但段 `overall_status=FAILED_INTERFERENCE_CONDITION`，非 PASS；资源未确认时禁止 validate/D2H/比较/写表/bank 释放，记录 `FAILED_UNSAFE_WORKER_RESOURCES`，保留完整分母/生命周期证据，bank 不可复用，停止后续。
- 实际入口：`pi05_m3_b6_interference.finish_failed_active` 统一异常清理；`export_failed_retention` 使用 active 安全闸门；不安全返回 `NOT_EXPORTED_no_reliable_worker_release`，已持久化返回 `NOT_EXPORTED_already_validated_and_persisted`，不重复 D2H/导出最小报告。
- CPU：`scripts/validate_m3_b6_cpu.py` **37/37 PASS**（v1 29 + 8 项实际 SegmentWindow/lifecycle 故障与真实 main 凭据）；B5 8/8、B3 entry 10/10；r1 worker/lifecycle 52/52 复用。真实 main 合法凭据到 prepare sentinel，错协议/过期前置拒绝，不导入 GPU。
- 冻结：`controlled_interference_b6_v1_r1/deployment/` payload **33** 文件（含 manifest 共 34），`DEPLOY_SHA256.txt` `96a1c748d7651c40c38b4ba97b6a82a681c781632bac7bf93e2ce77a125c37d2`，`CONFIG.json` `b03a275b0d4a9542a18103de51929ea0c998590f6421309c835cc58b5f77fe77`；dry-run 0；v1/historical board 不改。
- 边界：CPU PASS 不是 GPU/板端安全、干扰效果或新计时窗口 PASS；B2 仍候选，M3 未完成，不进入 M4。

## 历史：b6 四条件受控干扰 v1（2026-10-21，PREPARED / NOT APPROVED / NOT RUN，CPU only）



状态：**整批准备包已冻结；未部署、未批准、未运行。** 模型、真实压力 worker、SSH、硬件写入、scope 均为 0。

- 协议/轨迹：`m3_b6_controlled_interference_v1`；`two_9_9`、P=D=180 ms、Expert +15 ms；A quiet/serial、B quiet/boundary、C fixed_cpu_mem/serial、D fixed_cpu_mem/boundary；顺序 A,B,C,D,D,C,B,A；每段 8 周期/4 刷新。
- 新文件：`scripts/m3_b6_plan.py`（四条件/顺序/manifest/预算/时间与 worker 预算/protocol）、`scripts/m3_b6_window.py`（r1 控制器适配：唯一 t0、固定窗口、coverage、无写盘）、`scripts/pi05_m3_b6_interference.py`（唯一入口，复用 B5 准备/gate 路径）、`scripts/m3_b6_control.py`（preflight/submit/scope/verify-restored；三处同一 b6 令牌）、`scripts/validate_m3_b6_cpu.py`（**29/29 PASS**）。
- 共用驱动：`run_segment` 增加可选 `window`，仅在启用时于 `backend.ready` 后用 `t0=now+4 s`；旧路径仍 `clock()+10 ms`。`run_candidates` 增加可选 `window_factory`；replay 完成后先等固定 `worker_end`/确认退出/释放，再统计、coverage、D2H/比较/写盘和 bank 复用；条件无效或 overrun 在安全验证后停止后续段。
- 时间：`t0=准备完成+4 s`；`nominal_end=t0+1.440 s`；`drain=0.720 s`；`worker_end=t0+2.160 s`；quiet 同一时间轴、零 worker；fixed 最多 4 个顺序 CPU11 worker，任一时刻 1 个、0 重试。
- Worker 证据：r1 `m3_interference_worker.py`/`m3_interference_lifecycle.py` 未改；**52/52 CPU** 既有证据复用。`finalize` 成功只表示证据已保存，不等于资源释放；资源以 `resource_release.resources_released` 为准。
- CPU：b6 29/29；共用驱动回归 B5 8/8、B3 entry 10/10；r1 52/52 复用；未重跑历史全集。结果/日志见 `reports/m3_b2/20261021/controlled_interference_b6_v1/`。
- 冻结：`deployment/` payload **33** 文件（含 manifest 共 34），`DEPLOY_SHA256.txt` `ce630787dc2e598f2db008cbda5aa5aebfa7169d9467e65c82d92486fe3b5610`，`CONFIG.json` `b03a275b0d4a9542a18103de51929ea0c998590f6421309c835cc58b5f77fe77`；dry-run 0；历史 B5 board 191 文件/4,649,192,413 B 未改。
- 边界：CPU PASS 不是 GPU 数值/性能、板端安全、干扰效果或新计时窗口 PASS；B2 仍候选，M3 未完成，不进入 M4。

## 历史：受控干扰 worker 修订组件 r1（2026-10-21，CPU only）

状态：**worker 修订组件 CPU 核验；四条件批次尚未集成、未冻结、未批准、未运行。** 模型、真实压力 worker、SSH、硬件写入、scope 均为 0；未接入 GPU 入口。

- r1 修复：执行结果/持久化分离（`persistence_status`/`persisted` 独立，finalize 不改 `state/status`）；`copy_window` Host 工作边界（loop enter/exit、first call、last return、copies/bytes、`work_valid`）且 `copies=0` 不能 WINDOW_COMPLETE；就绪使用单一绝对 deadline（spawn、接收、验证都计入）；quiet 只有完整窗口才 QUIET_COMPLETE；`SubprocessHandle.release()` 逐项释放并独立于 finalize；成本表述修正。
- 文件：`scripts/m3_interference_worker.py`、`scripts/m3_interference_lifecycle.py`；CPU 测试 `scripts/validate_m3_interference_lifecycle_cpu.py` **52/52 PASS**；`scripts/fixtures/m3_nonpressure_worker_fixture.py` 仅为非压力夹具。
- 证据：`reports/m3_b2/20261021/controlled_interference_worker_v1_r1/`（R1_FIX_MATRIX、WORKER_REUSE_REVIEW、WORKER_LIFECYCLE、NEXT_STEP、CPU_RESULTS/CPU_TESTS、CONFIG、EVIDENCE_INDEX、MINIMAL_DIFF）；v1 与 `before_v1/` 保留。
- 边界：CPU PASS 只证明生命周期/工作证据/guard/心跳/资源逻辑，不是板端安全、干扰效果、计时窗口或 GPU PASS；B2 仍候选，不进入 M4。


## 历史：受控干扰 worker 组件 v1（2026-10-21，CPU only）

状态：**worker 组件完成 CPU 核验；整批准备仍在进行，未批准、未运行。** 本轮只阅读/最小修改/CPU 核验；模型、真实压力 worker、SSH、硬件写入、scope 均为 0；未接入 GPU 入口。

- 新 worker：`scripts/m3_interference_worker.py`（窗口门控、stdout 就绪/最终证据、64 B 共享内存心跳；复用 v4 的 `GuardedBuffer`/`copy_once`/64 B guard/CPU11/身份/PDEATHSIG）。
- 新生命周期：`scripts/m3_interference_lifecycle.py`（quiet 不创建 worker；fixed 创建→就绪→等待预声明开始→运行→停止→退出确认；窗口后持久化；有界 TERM/KILL；只清理自有 PID）。
- CPU 测试：`scripts/validate_m3_interference_lifecycle_cpu.py` r1 **52/52 PASS**（v1 的历史计数已被 r1 取代，不再作为当前计数；历史证据保留）；`scripts/fixtures/m3_nonpressure_worker_fixture.py` 仅为非压力进程夹具。
- 证据：`reports/m3_b2/20261021/controlled_interference_worker_v1/`（WORKER_REUSE_REVIEW、WORKER_LIFECYCLE、NEXT_STEP、CPU_RESULTS/CPU_TESTS、CONFIG、EVIDENCE_INDEX、MINIMAL_DIFF）。
- 边界：CPU PASS 只证明生命周期/guard/心跳/证据逻辑，不是板端安全、干扰效果、计时窗口或 GPU PASS；B2 仍候选，不进入 M4。

## 历史：M3 边界优先 180/240 ms 两锚点（修订 r1，2026-10-21，已执行）

两锚点批次已执行（2026-10-21，1 模型 + 1 scope，零重试）：`PASS_IN_PROCESS_BOUNDARY_BUDGET_ANCHORS`，253 checks/0 失败。实测：240 ms 下 serial/boundary 均 0 违约（8/8）；**180 ms 下 serial 两遍均 4/8（4 周期违约）**，同预算 boundary 两遍 8/8；刷新四条件 4/4（~198.1–198.6 ms）。证据 `reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/gpu_run_01/`。历史（准备）：`reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/`。四条件 A 240/serial、B 240/boundary、C 180/serial、D 180/boundary，8 段 A,B,C,D,D,C,B,A；每段 manifest 自带预算；`m3_b3_orchestrate.run_candidates` 新增 per-segment `confs`（向后兼容）；新 `m3_b5_plan/m3_b5_control/pi05_m3_b5_anchors/validate_m3_b5_cpu`；冻结 40 文件、CPU 8/8、dry-run 通过。历史（离线分析）：`reports/m3_b2/20261021/plan_feasibility_v1_r1/`。模型**直接驱动冻结 `m2_executor.VersionedKV`**（slot/generation/RETIRED/读者预留/安全回收），非法回收按执行器语义拒绝并保留分母；统计改为从 `manifest/t0_ns/experts/units/published` **独立重建**（64 周期/32 刷新、逐作业 0 mismatch、4/4 故障注入被发现）；审阅算例修正为 P=180（deadline 375/360）；尾块覆盖改用真实最后块（两块 `/B2`、三块 `/B3`）；删除过强结论与"+0.55 ms 在噪声内"。`validate_plan_feasibility_cpu.py` 19 项 PASS。原 v1 保留并标为历史（分析缺口见 `REVISION.md`）。结论：偶数周期在冻结语义下必须串行完成"本周期 VLM 单元 + Expert"，条件化和 139.58/140.06 ms，B/D 实测 +0.9%/+1.0%；切分只改先后不改和，故三块只降 Expert 等待（65.3→16.2 ms）而周期 +0.55 ms；`b2_slack` 反例为负（审阅算例 Expert −5.6/周期 +39.0；整轨迹 Expert −19.9/周期 +100.2/发布 +175.4），且实测轨迹不触发；**决策 A：不新增生产策略，保留 `b2_boundary`**。B2 仍候选，不进 M4。

修订r1统一gate预算与入口三块GATE_PLAN（15条/124,121,472 B），磁盘估算5.27 GiB；成功标识改为PASS_IN_PROCESS_BOUNDARY_BUDGET_ANCHORS。3个工作源码已同步，旧v1包原样保留；本轮仅针对性CPU核验，模型/SSH/硬件/scope均0。详见本包REVISION.md。

历史：2026-10-20 四组消融已执行：1 普通模型 + 1 五节点 scope、零重试，8 段（A,B,C,D,D,C,B,A）各 8 周期/4 刷新，`PASS_IN_PROCESS_SPLIT_PRIORITY_ABLATION`，255 checks/0 失败。实测：优先次序（serial→boundary）在两种切分下都把偶数周期响应降 ≈44.7 ms；额外切分只把偶 Expert 等待 65.3→16.2 ms、完成 140.9→91.8 ms，周期响应实测 +0.55 ms（未建立噪声范围或等价性；B 为 Expert-bound，D 为 VLM-bound）；刷新发布就绪四组均值 200.6–201.2 ms；64 周期零违约。数值上 autotune 落在 config X（S0 `0c63ddfb…` 非 H_frozen），D1 逐字节准入通过，跨进程仅报告（S0 0.168/0.0527 超包封、S1 为 0）。证据：`reports/m3_b2/20261021/split_priority_ablation_v1_r2/gpu_run_01/`。四组 A `two_9_9+serial_context`、B `two_9_9+b2_boundary`、C `three_prefix_9_9+serial_context`、D `three_prefix_9_9+b2_boundary`，8 段（两遍相反顺序）各 8 周期/4 刷新；仅 plan 与 policy 不同。**修订 r1**：入口凭据改用本批 `m3_b4_control`（原从 r2 控制器导入会拒绝合法 B4 凭据），新增经过真实入口的凭据回归；磁盘按 r2 实测逐项分解（二进制 5,087,214,824 B，估算 5.83 GiB）；准入门槛统一为实际 **12 GiB**。**修订 r2**（执行前）：r1 获批后 submit 一次被 argparse 拒绝（控制器自身开关仍为 r2 令牌），未执行任何实质步骤、一次性标记未创建、额度未消耗；r2 修正该 2 行并新增 3 项控制器 CLI 回归与内部一致性断言。冻结包：`reports/m3_b2/20261021/split_priority_ablation_v1_r2/`（REVISION、DESIGN、GPU_PLAN、APPROVAL_CHECKLIST、MINIMAL_DIFF、BUDGET、CPU/FAIRNESS、TEST_ENVIRONMENT、deployment 36 文件）；r1 与 v1 原样保留。

2026-10-21 离线勘误见本批 `gpu_run_01/OBSERVATION_NOTES.md`；`corrections/audit_report_corrections.py --verify` 仅用 CPU 从原始时间戳重算关键路径、32 次完成/发布与 32 次实际边界间隙，并核对本地 191 文件和冻结 36 文件 SHA。root 快照内容与特权 journal 尚未归档，不以可读范围 SHA PASS 代替全源归档。原始数据及冻结源码保持不变。

| 模块 | 责任 |
|---|---|
| `scripts/m3_b6_plan.py` | b6 四条件/顺序、共享 180 ms manifest、预算、4 s/1.44 s/0.72 s/2.16 s 时间契约、worker/时间预算、protocol |
| `scripts/m3_b6_window.py` | r1 控制器适配：唯一 t0、readiness、fixed/quiet 窗口、finish/exit/release、每操作/周期/刷新 coverage；不写文件 |
| `scripts/pi05_m3_b6_interference.py` | 唯一 b6 GPU 入口：复用 B5 准备/gate，8 段 window_factory，逐段 condition_valid/协议/资源检查 |
| `scripts/m3_b6_control.py` | b6 preflight/submit/scope/verify-restored；CLI/闸门/命令三处同一 b6 令牌 |
| `scripts/validate_m3_b6_cpu.py` | **37 项 CPU**：v1 29 + 资源未确认阻断、release 失败、零拷贝安全失败、正常路径、真实入口异常清理、真实 main 凭据；实际编排/Actual SegmentWindow/r1 lifecycle |
| `scripts/pi05_m3_b6_interference.py` | 唯一 b6 入口；新增 `finish_failed_active`，异常留存导出走同一 active 资源安全闸门 |
| `scripts/m3_b3_orchestrate.py`（r1 改） | `window_resource_safety` + resource-safe closeout：unsafe 不 validate/D2H/写表/释放；safe condition-invalid 独立 validation 且段总体 fail |
| `scripts/m3_b2_core.py`（改） | 可选 window 在 `backend.ready` 后取唯一 t0；旧路径保持 `+10 ms`；统计延后到窗口结束后（b6）；r1 不改调度语义 |
| `scripts/m3_b3_orchestrate.py`（改） | 可选 window_factory；finish/统计/coverage 先于 D2H/比较/写盘/bank 复用；无效条件安全停止 |
| `reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/deployment/m3_b5_plan.py` | 两锚点协议：四条件、8 段 RUN、每预算 manifest、按本轮重算的预算（bank 487,320,064 B、磁盘以冻结 CONFIG 声明为准、轨迹 13.44 s） |
| `.../pi05_m3_b5_anchors.py` | 唯一 GPU 入口（本批已执行）：固定工作后 8 段，逐段用自身 manifest 与 policy，失败归属实际活动段 |
| `.../m3_b5_control.py` | 一次性托管：preflight/submit/scope/verify-restored；CLI/闸门/命令三处同一 B5 令牌 |
| `.../validate_m3_b5_cpu.py` | 8 项 CPU：四条件与顺序、180/240 释放与 deadline、每段预算驱动、失败归属、控制器令牌 |
| `m3_interference_worker.py` | 受控干扰窗口 worker：复用 v4 guard/copy；fixed 32 MiB、CPU11、预声明绝对起止、窗口内不写 JSON/日志；stdout 就绪/最终证据 + 64 B 共享内存心跳；未接入 GPU 入口 |
| `m3_interference_lifecycle.py` | 单进程生命周期：quiet 零启动；fixed prepare/ready/await start/run/finish/stop/exit；就绪失败/超时阻止窗口；有界 TERM/KILL；只清理自有 PID；窗口后 finalize |
| `validate_m3_interference_lifecycle_cpu.py` | **52 项 CPU**（r1 已接受）：quiet、就绪成功/失败/超时、开始前无压力、完成时刻不改轨迹、正常/提前/父死、TERM/KILL 有界、重复启动/零重试、容量/长度/guard、异常阶段证据、窗口内无序列化/写盘/无界等待、持久化/资源分离、0 拷贝、绝对 deadline、quiet 完整窗口 |
| `fixtures/m3_nonpressure_worker_fixture.py` | **仅测试夹具**：真实 ready/final/heartbeat 协议、无 memmove/无 32 MiB；验证真实 `SubprocessHandle` 管道+共享内存；不得部署 |
| `plan_feasibility_v1_r1/plan_model.py`（历史分析） | 单流时间模型，直接驱动冻结 `VersionedKV`；非法回收=拒绝并保留分母；支持域 `0≤φ<P` 显式校验 |
| `plan_feasibility_v1_r1/rebuild_stats.py`（分析） | 从原始映射独立重建统计（冻结 `replay_stats`）、operations Event 交叉核对、临时副本 4 类故障注入 |
| `plan_feasibility_v1_r1/validate_plan_feasibility_cpu.py`（分析） | 19 项：重建逐作业比对/注入/生命周期/非法回收/支持域/次序/空等/版本/超时/终止/尾块覆盖/P=180 算例 |
| `plan_feasibility_v1/plan_model.py`（历史分析） | 单流时间模型：固定释放/相位、义务分组、块不可抢占、合法边界、固定版本、发布守卫、双槽 FIFO、安全回收、完整分母；仅被分析脚本导入，执行器不引用 |
| `plan_feasibility_v1/scenarios.py`（分析） | 实测重算 + 声明式反事实：b2_slack 算例、尾块跨越、次序、空等、版本未就绪、超时、终止、条件化和 |
| `plan_feasibility_v1/validate_plan_feasibility_cpu.py`（分析） | 13 项 CPU：模型 vs 实测残差、义务分组、条件化和、b2_slack 正反算、次序/空等/版本/超时/终止；不声称 GPU/WCET |
| `m3_b4_plan.py` | 四组 `CELLS`、两遍 `RUN`/`SEGMENT_IDS`、共享 `manifest()`（8 周期、+15 ms 相位）、按本轮重算的 `budget()`（bank 597,617,152 B、payload 4,339,748,864 B、磁盘分项：二进制 5,087,214,824 B / 估算 6,259,915,173 B / 准入 12 GiB、轨迹 15.36 s）与 `protocol()` |
| `pi05_m3_b4_ablation.py` | 唯一 GPU 入口（PREPARED）：固定工作（2 预热/2C+2E 参考/D1/两槽前缀参考/装配/两 gate）后连续 8 段，逐段断言 plan/policy/protocol，失败归属到实际活动段；**凭据校验用本批 `m3_b4_control.verify_credential`**（r1 修正） |
| `m3_b4_control.py` | 一次性托管：preflight/submit/scope/verify-restored；与 r2 控制器仅 spec 行不同（单测断言），**argparse/闸门/模型命令/scope 命令四处使用同一个 B4 令牌**（r2 修正；CLI 回归覆盖） |
| `validate_m3_b4_cpu.py` | **23 项** CPU：四组配置驱动、serial 不插队/boundary 只在边界、无 Expert 连续、队列与版本等待、FIFO、8 段唯一 ID 与 bank 复用、中间段失败归属与导出、协议来源、窗口无侵入、spec-only（13）+ 真实入口凭据 5（B4 通过到 `prepare` 哨兵、B3/过期/包变化/错 SHA 被拒、无 CUDA 导入）+ 磁盘分项与 12 GiB 门槛 2 + **控制器 CLI 3**（批准命令形状可解析并到达 sudo 闸门、r2 令牌被拒、控制器自身协议路径） |
| `check_m3_b4_fairness.py` | 四组公平性：同 manifest/输入/消费/释放/deadline/义务组/工作量；A/B、C/D、A/C、B/D 配对；两遍相反顺序 |
| `m3_b2_core.py`（改） | 段级 `protocol` 取自 manifest `schema` 并与 `expect` 声明核对（11 行） |
| `m3_b3_orchestrate.py`（改） | `run_candidates` 由 `candidate['policy']` 驱动策略、`conf['cycles']` 决定留存与义务单元；逐段断言 protocol/policy/plan 并记入 summary（24 行） |

## 历史：M3三块r2唯一批有限PASS与离线收口

本批已执行并有限PASS，1模型/1 scope，18C/14E；本轮仅报告勘误、CPU审计与只读取证，新增模型/硬件写入/scope均为0。原始字段及执行冻结包不改写。107个普通用户可读文件及原root快照已联合归档，108源文件/1,063,439,813 B全部SHA一致；服务journal实核apply/restore各5次及10次读回，收口完成。

- 实际报告：`reports/m3_b2/20261020/three_block_v1_r2/gpu_run_01/RUN_REPORT.md`。
- 观察勘误：同目录`OBSERVATION_NOTES.md`。
- 可复算审计与归档：同目录`closeout/audit_closeout.py`、`CLOSEOUT_AUDIT.json`、`BOARD_READABLE_INVENTORY.json`、`LOCAL_RUN_SHA256.txt`。
- 原始`segments[].protocol`误沿用旧ID；按顶层冻结配置与manifest识别本批，不改原始SHA。
- B2仍候选，可靠长尾/k_min/最终切分/净收益未验收。

## 历史：M3 三块候选准备（修订 r2，2026-10-20，PREPARED，随后已执行）

本轮只授权源码阅读、最小修改、CPU 核验与重新冻结：模型 0、SSH 部署 0、硬件写入 0、scope 0。r1 修正入口编排（前缀参考补完 B2、gate journal 22/24 逐条核对、segment ID 唯一贯穿）；r2 修正代码审核三项（两块对照真实账本、候选失败证据归属、共享 `serial_context` 待发布停滞），预算不变。原包保留，当前修订包与审批清单在 `reports/m3_b2/20261020/three_block_v1_r2/`。三块候选 = `language+Vision27+norm/project/bias`（有效新 KV=0，只留存 x）｜`Encoder0–8`（9）｜`Encoder9–17`（18，可发布）；两块 `9+9` 保留为控制与兼容路径。仓库环境 6 套 **119 项**全 PASS（含真实适配器账本 7 项、入口编排 10 项、调度 25 项），部署包环境 3 套 42 项 PASS（`validate_m2_clean_cpu` 在包内缺依赖、不记 PASS）；公平性 PASS；r2 包 **31 文件** SHA 自洽。设计/最小 diff/下一批方案/验收：`reports/m3_b2/20261020/three_block_v1_r2/`（原 `three_block_v1/`、`three_block_v1_r1/` 保留）。

| 模块（scripts/）| 作用与限制 |
|---|---|
| `m3_b3_plan.py` | 三块 `BlockPlan`（blocks/valid_layers/(prefix,mid,full)/kinds/groups）、预声明相位 φ=+15 ms、协议/预算/`SEGMENT_IDS`/gate 期望条数（22/24）与全批↔观察账本分列；不含任何模型数学 |
| `m3_b3_orchestrate.py` | 入口实际调用的编排：`run_prefix_reference`（B1→B2 + 完整 Context 逐字节）、`run_gate`（旧读者/人工接续，逐条 journal 内容与顺序）、`run_candidates`（两 plan 连续、唯一 segment ID、持久化后才复用 bank、失败归属 `active`）；`mark_active`/`describe_active`/`export_failed_retention`（仅截止时间内且 bank 安全时导出，永不 PASS） |
| `pi05_m3_b3_prepare.py` | PREPARED 入口：D1、前缀同进程参考（两块 block1 层 0 只读钩子）、三块装配逐字节比对、两个三块 gate、两候选 4 周期/2 刷新；需新 flag 与 env，未批准即退出 2 |
| `m3_b3_control.py` | PREPARED 一次性控制器：普通用户 preflight / 交互 sudo 一次 scope+唯一模型 / 独立恢复读回；不复用上一批授权 |
| `validate_m3_b3_entry_cpu.py` | 10 项**入口编排**回归：两槽前缀参考完整收尾（含负例）、两种 gate 的 22/24 逐条内容与顺序、两个 plan 连续运行+持久化+唯一 ID、全批/观察账本计数、入口确实调用同一份编排、**失败归属**（第一段/第二段/gate）与四种 `NOT_EXPORTED_*` |
| `validate_m3_b3_adapter_cpu.py` | 7 项**真实适配器账本**回归：真实 `CudaDevice.run_math`+真实 `CallLedger`+假 pipeline；两块 B1/B2、三块 P/B1/尾块、Expert 10×18；漏算/重复/多余/错槽/重复 ID 负例 |
| `validate_m3_b3_cpu.py` | 21 项 CPU：0/9/18 状态与发布拒绝、顺序/重复/越界拒绝、前缀/Encoder 期到达边界选择、版本等待/FIFO 积压、读者与回收、Event 超时/失败分母、留存容量/延后读取、两计划同工作量、前缀调用序列、相位只移 Expert、窗口无侵入观测 |
| `check_m3_b3_fairness.py` | 两候选同一 manifest/binding/相位/版本轨迹/工作量、仅切分不同的机器可读核对 |
| `m2_executor.py`（改） | 新增 `BlockPlan`/`Version.valid_layers`/按 plan 的 block 校验、READY、发布守卫；默认两块行为不变 |
| `m2_pi05_ops.py`（改） | 新增 `prefix_block`/`encoder_block`（与原 `block1` 同参同序，CPU mock 比对）；`CallLedger.execute` 支持计划内显式 expected/work |
| `m2_clean_core.py`（改） | `retention_layout(cycles, plan)` 增加 `prefix` 形状；默认调用与已归档布局逐字节一致；gate 布局可按 plan |
| `m2_clean_backend.py`/`m2_clean_cuda.py`（改） | 按 plan 取块 work/kind、`prefix` 捕获（只 D2D x）、按 plan 的层号审计、`use_plan` 切换（窗口外） |
| `m3_b2_core.py`（改） | `run_segment(..., expect=plan)`：按 `len(plan)` 发布、按 `plan.groups` 形成两个义务单元、发布前版本保留守卫（`publication_deferred`）；r2 起 `atomic_context` 仅在 Context 仍在计算时生效，等发布时允许已释放偶 Expert 解除依赖（`publication_unblocking_experts`）；原 `protocol()` 不变 |

未执行：三块 GPU 数值/边界成本/真实时钟驱动的优先覆盖 = NOT_RUN；不进入 M4、不改阈值、不重开历史根因。修订 r1 的入口回归与冻结校验见 `three_block_v1_r1/REVISION.md` 与 `APPROVAL_CHECKLIST.md`。

## M3 B2候选有限GPU批（2026-10-20，已执行）

M2 clean_serial_v1阶段PASS保留。用户已批准唯一`m3_b2_boundary_profile_v1`批并完成：1模型17.438s、1scope19.340s、零实验重试，15C/13E+36 Autotune另账，88entry全exact，D1及人工接续/旧读者gate通过，独立离线1007检查0失败。C0/C1各4周期2刷新均0/4违约；自然块内到达未观察到，B2未最终定线、无净收益结论，不进入M4。实际报告/块与控制表/完整备份：`reports/m3_b2/20261020/boundary_profile_v1/gpu_run_01/`。

|模块（scripts/）|作用与限制|
|---|---|
|m3_b2_core.py|固定释放/FIFO/边界Expert优先、无Expert继续Context、版本依赖等待；串行控制与B2同驱动，单在途真实fence|
|m3_b2_backend.py|继承M2数学/留存，stage及所有操作实际Event完成确认；GPU观测与Host完成字段分列；旧M2 false不改|
|m3_b2_profile.py|预分配410细Event+原320操作Event；原函数入口/出口观测，不增加合法切点；必要成本两策略对称|
|m3_m2_preparation.py|通过M2实际源码SHA锁定72条原准备/D1 AST，不复用M2一次性授权或维护第二套数学|
|pi05_m3_b2_profile.py|新授权入口，两个正确性gate+两个4周期短profiling；本批全量留存/动作/工作量有限PASS；人工与自然覆盖分开|
|m3_b2_control.py|M3名称/旗标/入口的原托管控制器；本批五min恢复/独立读回/无残留PASS；唯一额度已用完，不复用授权|
|validate_m3_b2_cpu.py|29项CPU符号/故障/容量/完成字段/公平性/AST/拒绝无批准测试；不作为GPU证据|

原M2数学、VersionedKV、留存/统计及M1执行快照均不改。只保留完整Context决策控制和9+9两个候选；Vision/投影不可中断，其他切点待测。

## M2 共用基础（2026-10-20）

M2 v3有限正确性/版本机制PASS保留；clean_serial_v1唯一批阶段串行基线已执行并有限PASS（ABBA各16周期8刷新，0/16违约，524留存entry全exact，恢复/备份通过）。D1沿用，B2仍试选，D2不作为前置；本批交付时未进入M3，现有用户新授权的M3候选准备见顶部。实际报告：`reports/m2_common/20261020/clean_serial_v1/gpu_run_01/RUN_REPORT.md`。

| 模块 | 文件（均在scripts） | 状态与范围 |
|---|---|---|
| 干净公平串行基线（已执行，有限PASS） | `pi05_m2_clean.py`、`m2_clean_core.py`、`m2_clean_backend.py`、`m2_clean_cuda.py`、`m2_clean_stats.py` | v3数学/D1/版本模块不改；同一执行器的即时/延后观测模式；ABBA各16周期8刷新，全部128项/段覆盖前留存，正常窗口移出D2H/比较/写盘，保留必要D2D/Event成本；GPU/Host各974640128B；本批全量exact/逐段0违约；stage.completed漏填边界见实际报告 |
| 干净批控制及验收（已执行，PASS） | `m2_clean_control.py`、`validate_m2_clean_cpu.py`、`audit_m2_clean_saved.py` | CPU25/25 PASS、配置dry-run/23清单SHA通过；新批CPU预检+一次普通模型180s+一次五min托管scope420s+独立恢复读回；唯一scope46.451s自动恢复、独立读回/无残留/原始备份PASS；冻结CPU审核1076项0失败；详见`reports/m2_common/20261020/clean_serial_v1/` |
| versioned_kv / block约束 / deadline_stats | `m2_executor.py` | CPU PASS；不可变快照、slot-generation-version、完整发布、旧读者Event、安全回收/隔离、固定释放/统计；单控制线程 |
| replay_driver / 公平串行 | `m2_replay_driver.py` | 同一驱动串行相邻/跨周期接续；版本轨迹/全部工作相同；错误保留完整分母；CPU符号回放PASS |
| Eager计算回调 / 实际工作账本 | `m2_pi05_ops.py` | 原v4计算函数体AST一致；实际调用观察；槽内持久状态接续；不改模型数学 |
| CPU验收 | `validate_m2_cpu.py` | 23项；含1000次回收、跨发布读者、超时、迟到/缺失统计、GPU无批准拒绝 |
| 初版GPU入口（历史） | `pi05_m2_correctness.py`、`run_m2_once.sh` | 已执行唯一模型，S0原参考门槛FAIL；实际1Context/1Expert，余项NOT_RUN，不重试；执行快照和结果见`reports/m2_common/20261020/gpu_run_01/` |
| 可复现性诊断（已执行） | `pi05_m2_repro_diag.py`、`run_m2_repro_diag.sh`、`validate_m2_repro_diag_cpu.py`、`audit_m2_repro_diag.py` | `gpu_run_02` 已执行（退出0）：A冷autotune、B热re-autotune、C原始run_pipeline；A=B=C逐字节，B=C证明harness不改数学；进程内无数值门，跨参考比较全在离线审核。报告`reports/m2_common/20261020/gpu_run_02/RUN_REPORT.md` |
| 选择单点隔离（已执行） | `pi05_m2_selection_probe.py`、`run_m2_selection_probe.sh`、`validate_m2_selection_probe_cpu.py`、`audit_m2_selection_probe.py` | `selection_probe_01` 退出0：S1C正对照与S0W/S0C的Context均逐字节复现冻结SHA，输出0.015625/0.007801711559=PASS；见`reports/m2_common/20261020/selection_probe_01/RUN_REPORT.md` |
| M2 v2 修复入口（已执行一次） | `pi05_m2_correctness_v2.py`、`run_m2_v2_once.sh`、`validate_m2_v2_cpu.py` | `gpu_run_04`：预热生效（2次到1.3005GHz、#1=0@68.31µs），但#3近并列候选翻面，在自建`S0_context_x_byte_exact`准入处停止；确认平台为**离散数值配置**（本批Context与2026-10-16 v6逐字节相同）；见`reports/m2_common/20261020/gpu_run_04/RUN_REPORT.md` |
| M2 v3 正式入口（已执行，PASS） | `pi05_m2_correctness_v3.py`、`run_m2_v3_once.sh` | D1口径：进程内`run_pipeline` vs 拆分逐字节等价为准入，跨进程0.015625/0.01仅报告；`gpu_run_05` PASS（206检查、H_frozen、两模式回放机制PASS、插桩值不作性能）；见`reports/m2_common/20261020/gpu_run_05/RUN_REPORT.md` |

直接复用旧 `pi05_dual_slot_adapter.py`、`period_obligation_stats.py`、`m1_dual_gate.py`。M1根脚本及执行快照保持原SHA；下面是冻结M1入口。M2 v3已实际验证限定单流路径的新版本切换、读者保护与回收；不扩大为任意并发/重启恢复/跨配置性能验收。Graph、配额调度与路线机制未新增实现，不能从M1有限证据升级为通用PASS。离线取证（差异起点在Context、误差7.39倍历史漂移、首个autotune项异常、层8边界已偏离、门只测跨进程）见`reports/m2_common/20261020/gpu_run_01/FORENSICS.md`。

## M1 源码入口与版本说明（截至 v10）

## 阶段入口

| 工作 | 主要文件 | 范围与限制 |
|---|---|---|
| Eager 完整/双块正确性 | `scripts/pi05_m1_correctness.py`、`pi05_encoder_two_blocks.py` | 完整工作量数值对照；历史 Graph 路径另行保留 |
| 独立与串行 profiling | `scripts/pi05_m1_profile.py`、`pi05_m1_trace.py` | Event/Host 与诊断时间线分别解释 |
| 双槽与地址清单 | `scripts/pi05_dual_slot_adapter.py`、`pi05_dual_slot_sequential.py` | 单权重所有者、独立可写状态；不可仅由对象不同推断并发安全 |
| Green Context | `scripts/green_context_sm_probe.cu`、`green_context_graph_probe.cu`、`green_runtime_resource.py`、`green_pair_resources_v4.py` | 合法配额、短探针和资源路径；探针不能替代所有真实算子的物理归属检查 |
| 正式周期批次 v4 | `scripts/pi05_m1_completion_v4.py`、`m1_completion_core_v4.py`、`m1_completion_launch_v4.py` | 已验收的有限周期回放；2P 刷新义务、固定旧 v0 绑定 |
| 固定访存干扰 v4 | `scripts/m1_memcpy_interference_v4.py` | CPU11、两个等容量 32MiB 缓冲及退出限制；旧 worker 保留为历史文件，不应误用 |
| 限定 Encoder 正常配对 v7 | `scripts/pi05_m1_pair_scoped_v7.py`、`pi05_encoder_pair_v6.py`、`m1_scoped_gate_v7.py` | Vision 前缀顺序；四模式正常样本与采集分开 |
| 补齐诊断时间线 v9 | `scripts/pi05_m1_root_trace_v9.py`、`pi05_encoder_pair_root_trace_v9.py`、`m1_root_trace_core_v9.py` | 一次获授权的 root 诊断例外，仅四个诊断配对，不是正常性能样本 |
| 延后活动采集 | `scripts/delayed_activity_v6.py`、`m1_activity_adapter_v6.cpp` | 已有 CUPTI ABI，CONCURRENT_KERNEL、correlation、缓冲和丢失记录检查 |
| v9 执行链 | `scripts/m1_execution_v9.py`、`m1_submit_service_v9.py`、`m1_service_scope_v9.py`、`m1_service_launch_v9.py` | 唯一 Run ID、冻结预检、临时服务、进程额度与五节点恢复；不是无人值守的新实验授权 |
| 数值与周期统计 | `scripts/m1_dual_gate.py`、`period_obligation_stats.py`、`b1_event_observer.py`、`pair_observation_v5.py` | 原始字节检查、独立绝对阈值、Host 完成保守区间、作业代次与义务账本 |
| v9 离线核验与图 | `scripts/analyze_root_trace_v9.py`、`analyze_activity_v6.py`、`analyze_pair_trace_v5.py`、`plot_m1_close_v9.py` | 各任务 Kernel 区间先求并集再求交集；需要独立保存的原始数据，仓库不附带 |
| 锁频配额曲线 v10 | `scripts/pi05_quota_sweep_v10.py`、`quota_runtime_resource_v10.py`、`validate_quota_sweep_cpu_v10.py` | 2–14+16SM 隔离 Context/Expert 响应；1模型/72样本/454检查；不替代 v7 配对或 v9 trace |
| 第一周收口增补 v10 | `scripts/analyze_week1_closure_v10.py`、`plot_quota_sweep_v10.py`、`plot_m1_close_v10.py` | p99/刷新/W(D)/成本离线表；配额曲线与首图 v2 的重绘；脚本本身不新增模型 |

上表中的短文件名同样位于 `scripts/`。完整阶段事实、失败与适用范围以 [PROJECT_STATUS.md](PROJECT_STATUS.md) 为准。

v10 的协议、运行命令、原始结果与首图在 `reports/m1_acceptance/week1_closure_20261018/quota_sweep/` 与同目录 `QUOTA_SWEEP_RESULTS.md`；它们属于本地实验归档，不在公开源码上传范围。

## 隔离资源查询补丁

`patches/GEMM_RESOURCE_INFO.patch` 保存本项目提出的只读资源 getter/绑定差异；实际隔离诊断扩展使用 `scripts/gemm_resource_diag_bindings.cpp`。它不代表已覆盖生产 FlashRT，也不是自动修改第三方源码的命令。适配时须核对目标版本的成员定义和分配容量。

## 版本与复现

- `v4`、`v7`、`v9`、`v10` 是不同用途的冻结实验版本；v10 是隔离配额测量与首图 v2，不替代 v7 的配对或 v9 的 trace；不能把后缀更大简单理解为所有旧入口的替换版本。
- 旧 Graph、Vision 并发、权限和超时失败脚本保留用于追溯，不能把它们标作已修复或重新启动来替代原始记录。
- 一些部署器要求 `APPROVED_CONFIG.json`、`DEPLOY_SHA256.txt`、`unified_reference/`、既有二进制扩展和原始证据。这些由具体实验的冻结部署生成，不在本次公开源码上传范围内。
- 固定 checkpoint 与 FlashRT 不是本仓库的一部分。依赖版本、输入和参考必须与具体实验协议一致，不应为了跑通而更换精度、减少层数或去噪步骤。
- 本仓库不包含机器人闭环验收或最终论文完整评测框架。M2 v3单流版本生命周期已有有限GPU PASS；干净留存/阶段公平串行性能已有本批有限GPU证据；长跑/通用恢复未验收，stage观察字段限制保留，未自动进入M3。
