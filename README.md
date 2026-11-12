# CoOverlap: Deadline-Aware GPU Execution Runtime for Embodied AI Agents

## Project Overview

CoOverlap 研究具身智能体推理底层的嵌入式 GPU 执行、资源管理和周期时限调度。仓库包含 VLM 分块、Action Expert、版本化 KV、CUDA 适配、资源探针、回放和离线分析的多版本科研实现，尚不是可直接部署的统一 Runtime 产品。

本次按功能增加导航和可执行入口，保留原始模型计算、冻结脚本和实验路径。没有新增 GPU 算法或性能结果，也未重新引入此前排除的模型改写工具和数据。

## Architecture

```text
模型/Expert回调 → 执行后端与CUDA事件 → VersionedKV发布/读者/回收
                          ↑
               固定释放与合法边界执行计划
                          ↓
                  周期、刷新和期限记账
                          ↓
              Trace / Host记录 → 离线分析与CPU检查
```

实际目录分层如下；Runtime/Scheduler/Benchmark 暂保留原源码位置，以功能索引连接，不创建空目录或把历史代码包装成新产品：

```text
profiling/    可运行的分析导航与合成检查入口
tests/        CPU检查运行器与入口回归测试
tools/       旧命令兼容入口
scripts/     既有执行器、调度、探针、回放及分析源码，路径保持
reports/     Git已跟踪的冻结源码快照；数据不随新增代码发布
docs/        功能映射、分支迁移与公开范围
```

[核心功能映射](docs/FUNCTION_MAP.md)列出实际依赖、验证状态及A/B/C处理分类。

## Runtime Components

- [VersionedKV与合法工作序列](scripts/m2_executor.py)：输入快照、完成事件、版本发布、读者绑定和安全回收。
- [模型调用适配](scripts/m2_pi05_ops.py) → [执行后端](scripts/m2_clean_backend.py) → [CUDA设备适配](scripts/m2_clean_cuda.py)：保留模型回调、状态留存和事件记录边界。
- [真实模型执行入口](scripts/pi05_m2_clean.py)：依赖外部模型、参考输入和目标设备，不能当作本机Smoke Test运行。
- [CUDA Graph历史实现](reports/m3_b2/20261023/graph_prototype_v1_r1/deployment/graph_backend.py)及 [Green Context探针](scripts/green_context_graph_probe.cu)：只作代码定位，本轮没有编译或GPU验证，也没有统一安装接口。

## Scheduling Components

- [期限与完整分母](scripts/period_obligation_stats.py)区分按时、确定违约、不确定和未完成。
- [有限回放](scripts/m2_replay_driver.py)使用固定周期释放与版本轨迹。
- [边界调度](scripts/m3_b2_core.py)与[合法切分计划](scripts/m3_b3_plan.py)分别组织派发和声明状态边界，不是任意版本可混用的通用调度器。

这些代码保留在原位置；迁移需连同导入、组装和匹配快照单独验证。

## Profiling and Benchmarking

```bash
python3 -B -m profiling --help
python3 -B -m profiling --list
python3 -B -m profiling check
```

[功能入口](profiling/__main__.py)列出真实Trace分析器并运行6项合成检查，不加载模型、不读取未公开Trace。

实际分析器仍是[内核/API时间线](scripts/day1_pm_cpu_trace_repair_20261111/analyze_trace.py)和[CPU提交间隙](scripts/day1_pm_cpu_trace_repair_20261111/analyze_cpu_gaps.py)。它们处理真实记录时依赖匹配的SQLite/NVTX/Host结构，并写入输入目录的analysis；不要为整理而在原始结果目录重跑。

SM响应测量定位到[配额扫描](scripts/pi05_quota_sweep_v10.py)及[曲线脚本](scripts/plot_quota_sweep_v10.py)；Serial/回放定位到[m2_replay_driver](scripts/m2_replay_driver.py)。这些实验入口需要实际设备和冻结配置。本轮不宣称已重新验证Serial、双流或Green性能。

## Testing and Reproducibility

使用Python3.9.6及标准库验证，未安装依赖。规范入口：

```bash
python3 -B -m tests --help
python3 -B -m tests --list
python3 -B -m tests
```

原命令继续兼容：

```bash
python3 -B tools/check_cpu.py
```

检查包括23项KV/回放合约测试、7项期限检查、6项Trace测试和5项新入口回归测试。测试使用假Event和合成区间，不访问GPU或真实硬件控制节点。不要对全部历史脚本自动发现并执行。

[资产指南](docs/ASSET_GUIDE.md)、[公开范围](docs/PUBLICATION_SCOPE.md)、[原样分析源码指纹](docs/PUBLICATION_SOURCE_INDEX.json)保留来源与数据边界。模型、真实Trace和权重未新增分发；CPU通过不代替GPU数值或性能验收。

## Current Limitations

- 同名模块和接口随实验批次变化，仍需匹配冻结运行目录；没有统一依赖锁或一键GPU部署。
- Runtime、Scheduler与Benchmark尚未物理迁移，不能把功能导航理解为正式包接口。历史路径、源码SHA和数据位置保持。
- 历史状态和代码地图标为归档，最新导航使用此README与功能映射；不据旧进度补造新结果。
- 既有公开历史中的个人路径、第三方来源与许可问题仍需另行处理。未新增未审源码或LICENSE，也不声称全部历史已获分发许可。
- [分支规范与迁移方案](docs/BRANCH_NAMING.md)只完成本地准备；远端改名、默认分支切换和PR合并均待单独批准。

## Relevance to Agent Operating Systems

上层智能体系统可提出任务与时限，下层GPU执行组织管理模型子块、资源和完成事件。CoOverlap现有生命周期、周期记账和分析代码支持这一层面的系统研究。

目前没有统一外部OS服务、任务接入或资源协商接口，没有接入灵玑OS，也没有OS级跨智能体服务调度集成。
