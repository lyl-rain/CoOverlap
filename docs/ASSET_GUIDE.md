# 公开代码与证据导航

当前功能索引见 [FUNCTION_MAP](FUNCTION_MAP.md)。CPU运行器已移至 `tests/runner.py`，`python -m tests` 为规范入口；`tools/check_cpu.py` 兼容旧命令。`python -m profiling` 提供原分析器导航与合成检查。原始分析器位置和来源SHA保持不变。

| 功能 | 源码/入口 | 数据与验证边界 |
| --- | --- | --- |
| KV版本发布、读者与回收 | 基线 `scripts/m2_executor.py`；`validate_m2_cpu.py` | 使用假Event和有限回放，无权重或GPU依赖 |
| 期限、完整分母与不确定性 | 基线 `scripts/period_obligation_stats.py`；`validate_period_obligations_cpu.py` | 固定时钟和上下界合成输入；不是实测违约率 |
| 内核区间并集/交集与双算法核对 | 新增 `scripts/day1_pm_cpu_trace_repair_20261111/analyze_trace.py` | 可调用merge/length/intersect/sweep；实际分析需要Nsight SQLite、NVTX、API关联和Host记录，未随此增量公开 |
| API提交空隙记账 | 同目录 `analyze_cpu_gaps.py` | 使用同一Trace的kernel_records与API时间；缺映射仍记未知，API已返回不证明GPU已就绪 |
| 无外部数据的分析回归检查 | 同目录 `test_gap_accounting.py` | 6项合成测试；不当作真实硬件实验 |
| 统一入口 | `tools/check_cpu.py` | 只运行上述3组CPU检查，逐组超时，不启动模型或硬件控制 |

分析器输出路径依赖提供的实验目录，会生成/覆盖其analysis派生文件，不能为了检查而对原始结果直接重跑。本次不提供假造数据填补缺失Trace，不再引用排除的K8快照或全套原始实验包。

来源指纹见 `PUBLICATION_SOURCE_INDEX.json`。三份分析/测试源码从完整本地审阅版本原样选入，无FlashRT导入、外部源码读取改写或厂商内核实现；仅使用标准库。其他GPU适配、编译器及冻结快照未新增发布。以上是来源检查结论，不是给整个历史仓库授予许可证。
