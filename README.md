# CoOverlap: Deadline-Aware GPU Execution Runtime for Embodied AI Agents

## Project Overview

CoOverlap 研究具身智能体推理底层的 GPU 执行组织、资源管理和周期时限。当前主线集成候选提供可独立运行的 **CPU 生命周期与回放合约、期限记账和离线 Profiling 工具**；它不是已完成 GPU 部署的统一 Runtime。

此候选从现有 main 选择性引入已审代码，不合并整个归档。main 原有源码和历史说明保留；新功能与历史 GPU 实验的验证范围分别说明。

## Architecture

```text
固定输入快照 / 合法块计划
          ↓
VersionedKV：构建 → 完成事件 → 发布 → 读者绑定 → 安全回收
          ↓
有限回放驱动：固定释放时刻 + 显式回调 + 完整作业分母
          ↓
期限记账：按时 / 确定违约 / 不确定 / 未完成

保存的 SQLite / Host 记录 → 离线区间并集、交集与 API 间隙分析
```

[功能映射](docs/FUNCTION_MAP.md)列出实际依赖与检查边界。代码保持现有路径，没有制造空 Runtime 目录。

## Runtime Components

- [m2_executor.py](scripts/m2_executor.py)：双槽 KV 状态机、输入哈希、完成事件、版本发布、读者固定和安全回收。它管理合约，不分配 GPU 内存或执行模型数学。
- [m2_replay_driver.py](scripts/m2_replay_driver.py)：使用同一组调用回调运行相邻／恢复两种有限顺序；失败也保留完整义务账本。CPU 测试使用符号后端，没有假造模型适配器。

## Scheduling Components

[period_obligation_stats.py](scripts/period_obligation_stats.py)和执行器中的统计保留固定释放时刻、完整分母、不确定完成区间、积压与刷新记录。这里有可测试的回放组织和记账能力，没有新接入实际 GPU 优先级调度器。

## Profiling and Benchmarking

在仓库根目录运行：

```bash
python3 -B -m profiling --help
python3 -B -m profiling --list
python3 -B -m profiling check
```

[Profiling 入口](profiling/__main__.py)指向实际[Trace 分析](scripts/day1_pm_cpu_trace_repair_20261111/analyze_trace.py)和[CPU 提交间隙分析](scripts/day1_pm_cpu_trace_repair_20261111/analyze_cpu_gaps.py)。合成检查验证区间并集／交集和 API 状态记账，不需要 Nsight、CUDA、模型或原始 Trace。

真实记录分析依赖匹配的 SQLite 表、NVTX 标签和 Host 文件；这些记录未附带。分析器会写入输入目录下的 analysis，因此不要直接在冻结原始目录重跑。本轮没有执行完整真实 Trace 分析，也不汇报新的耗时或违约率收益。

## Testing and Reproducibility

仅需 Python 3.9.6 或兼容版本及标准库；本轮没有安装依赖。

```bash
python3 -B -m tests --help
python3 -B -m tests --list
python3 -B -m tests
python3 -B tools/check_cpu.py
```

测试包含 **20项原有 KV／回放测试、7类期限检查、6项 Trace 合成测试、5项入口回归测试**。原 M2 套件另有3项模型适配／GPU 入口检查未纳入；它们不是通过或跳过后冒充完整23项通过。保留的20项断言未改写，详见[集成范围](docs/MAINLINE_INTEGRATION.md)。

[源码指纹](docs/PUBLICATION_SOURCE_INDEX.json)记录已选文件与公开归档的对应关系。CPU 通过不能替代 GPU 数值、性能、空间配额或 CUDA Graph 验收。

## Current Limitations

- 尚未引入 Pi0.5 数学适配器、GPU 模型执行入口、FlashRT 源码或冻结实验快照；未核实的来源／许可文件保持在归档及原研究版本中。候选没有完整 GPU 推理部署入口。
- 原 main 已跟踪的 M1 GPU 及采集脚本继续保留，不能自动视为本轮检查通过；它们需要外部模型、设备和匹配配置。历史[代码说明](docs/CODE_MAP.md)、[项目简报](docs/PROJECT_BRIEF.md)及[状态记录](docs/PROJECT_STATUS.md)不是最新性能结论。
- 本次不消除 main 旧历史中的个人路径或未完成的来源审查，也不新增统一 LICENSE 或声称整个历史已获得分发许可。新增范围及剩余风险见[公开范围](docs/PUBLICATION_SCOPE.md)。
- 当前只准备本地候选；默认分支仍为 main。推送、主线合并和 main → vla-runtime 官方更名需要后续明确批准。

## Relevance to Agent Operating Systems

上层智能体系统可提出任务与时限，下层执行器管理模型子块、状态归属和完成事件。现有生命周期、固定释放回放和记账工具支持这一层面的系统研究。当前没有统一 OS 服务接口、任务接入或资源协商协议，没有接入灵玑OS，也没有跨智能体的 OS 级服务调度集成。

[资产指南](docs/ASSET_GUIDE.md)区分此候选、原 main 内容和完整历史归档。
