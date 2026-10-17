# CoOverlap 项目状态

更新时间：2026-10-17
当前阶段：2026-10-17 v9获明确root诊断例外后实际1模型/1scope完成，193运行检查、64数值对照、四模式完整Kernel/correlation覆盖PASS；自动恢复及普通nvidia独立核验PASS。v4周期24格、v7正常12样本冻结，最后配对trace缺口已补齐。M1第一周有限测量与产物已交齐，提交收口审核；用户最终验收/路线待确认，M2未启动。
主研究路线：未选择；按用户最新决定，暂不选B1/B2、不进入M2。历史优先B2建议页保留为阶段文件，不构成当前路线批准。

## 最新交付入口：2026-10-17 M1有限测量收口（v9）

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
- 实际1模型51.420856秒退出1/1scope53.686207秒，无重试。准备3Context/3Expert、配对闸门1/1、正常12/12，共16/16；采集参考1/1与诊断4/4未执行。两个原runner Autotune和两个8SM探针另账，全部18层/10步工作完整。
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
- 三重复正式1536 Expert/768刷新；含诊断/校准1696/848，配对正式另12/12。进程内精确通过；跨进程绝对容差通过，非跨进程逐位一致；误差来源仍UNKNOWN。
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
- Codex 已通过授权 SSH 访问 `jyh-orin`，板端型号为 NVIDIA Jetson AGX Orin Developer Kit。CUDA 13.2 官方接口在当前设备视图中报告 16 个 SM；这不等于已确认 TPC 映射或分区生效。
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
| G6 可用于真实执行测量 | PARTIAL（当前限定路径测量子项PASS） | v4周期/刷新/k/积压及单Streamtrace、v7正常四模式公共Event/Host保守界与完整控制成本、v9完整Kernel/correlation覆盖和目标B2首次执行已交。支持当前有限公平回放/对照；不扩到任意Vision并发/Graph或可靠长尾保证，旧v4下界FAIL不追改。 |

## 当前限制与用户待决定（不再列已测项目为未运行）

- M1有限测量与产物已交齐，等待用户审核收口和确认主路线；未取得相对串行的配对净优势，双块周期亦无稳定改善。负面结果不等于实验未做。
- 任意Vision并发安全仍FAIL，历史Context/Graph失配根因UNKNOWN；本次限定Encoder数值及物理重叠通过不覆盖旧FAIL，不恢复旧调查。
- 仅合法8+8点与普通全GPU已测，全部闭源Kernel逐SM物理集合未穷尽；已取得探针、显式路由、真实context/stream活动，不再把该限制串成无限前置。
- 正式部署预算/SLO、全配额公平优化、可靠长尾/k_min、长期热稳定、最新版本切换/通用回收器、NX及论文六图均未全验收，属于后续范围，不扩为M1首周额外门槛。
- v4原始约18.698GB完整在AGX，本地大KV395文件未全量备份；v7/v8/v9各自可读原始范围完整本地SHA通过，root snapshot仅板端。

## 待验证问题

1. 候选 Pi0.5 是否适合作为最终论文主负载；其他真实负载的软件环境与正确性尚未验收。
2. AGX 的SM→TPC映射、libsmctrl新栈兼容性及全部真实算子限额归属仍未完整确认；Green Context合法8SM点、两组不同SM探针和短Kernel/单节点Graph已通过，不能继续列为从未验证。
3. S0/S1双槽单Stream分块恢复、发布Event和旧Context复用已通过；v4有限64周期独立回放已通过。长期热稳定、独立双图重复、并发版本发布/回收仍UNKNOWN。`state_cond=false`将状态编码进Context，旧S0动作不称S1即时响应。孤立8SM与v7/v9限定Encoder配对数值有限PASS，v9物理Kernel重叠及覆盖已测；历史v5/v6 Context FAIL和全部闭源Kernel物理SM集合未穷尽分别保留。
4. 限定Encoder配对干扰/物理重叠/固定分区与归还尾差已实测；全Context安全、优化全配额及稳定相对串行净优势仍未证明。
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

## 下一步（只等待验收与研究决定，不自动执行）

1. 审核`reports/m1_acceptance/M1_FINAL_REPORT.md`与最新矩阵：限定首周测量是否收口，负面结果原样接受。
2. 按任务书§2.3确认路线；主建议优先B2问题，不等于当前双块已有优势。未获用户确认前不选线、不进入M2。
3. 原始证据保留；不追加“最后一次”模型，不恢复历史Graph/Vision调查，不将尚未通过的全部G项扩为新首周前置。

## 阶段交接约定

每个阶段结束时，先更新本文件，再生成阶段交接报告。报告至少包含：阶段目标与完成状态、硬件软件配置、原始数据和代码位置、正确性与公平性检查、已证实结论及其适用范围、失败实验、未解决问题、重大决策依据、下一阶段前置条件。不得将理论算例、历史 NX 数字或挑战目标写入“已取得结果”。
