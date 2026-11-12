# CoOverlap

CoOverlap 是面向具身智能体的嵌入式 GPU 执行与资源调度研究。本仓库已有 VLM 分块、Expert 执行、版本化 KV、串行/双流适配和资源探针等实验源码；它不是已安装模型的一键运行环境。

本次最小公开增量提供**可在 CPU 独立运行的检查入口，以及来自实际项目的 Trace 记账分析和测试**。不新增来源待核实的模型改写工具、GPU 冻结快照或原始实验数据。

## 可运行检查

本轮验证环境为 Python 3.9.6，仅使用标准库，不安装 CUDA、PyTorch或模型：

```bash
python3 -B tools/check_cpu.py --help
python3 -B tools/check_cpu.py --list
python3 -B tools/check_cpu.py
```

入口运行三组检查：既有版本化 KV/有限回放合约、期限与完整分母记账，以及新增的合成 Trace 区间检查。也可单独运行新增测试：

```bash
python3 -B scripts/day1_pm_cpu_trace_repair_20261111/test_gap_accounting.py
```

测试不依赖私有数据，不访问 GPU 或真实时钟控制节点。通过不能解释为 CUDA 数值、物理重叠或性能通过。不要对所有历史 `test_*.py` 自动发现并执行：部分入口需要数据或会写结果。

## 本次代码范围

| 路径 | 实际用途 |
| --- | --- |
| `tools/check_cpu.py` | 有限清单、逐项超时、失败返回非零的CPU检查入口 |
| `scripts/day1_pm_cpu_trace_repair_20261111/analyze_trace.py` | 读取已有Nsight SQLite与Host记录，建立API/内核对应关系，计算区间并集、交集和时间线 |
| `scripts/day1_pm_cpu_trace_repair_20261111/analyze_cpu_gaps.py` | 对同一Trace划分API未启动、进行中、已返回待执行及缺少映射的区间，并用独立算法复核 |
| `scripts/day1_pm_cpu_trace_repair_20261111/test_gap_accounting.py` | 合成区间测试，检验重叠去重、Graph父级API范围及未知映射处理 |
| `scripts/m2_executor.py`、`scripts/period_obligation_stats.py` | 沿用Week2版本的KV生命周期与期限记账，不引入新版K8接口 |

分析器处理真实Trace时依赖匹配的SQLite schema、NVTX和关联记录；会在输入目录的 `analysis/` 写派生文件。原始数据本次未发布，不把真实分析命令列为开箱即用入口。分析前应使用工作副本，避免覆盖旧结果。

[资产导航](docs/ASSET_GUIDE.md)说明代码—数据关系；[公开范围](docs/PUBLICATION_SCOPE.md)说明选择与排除；[来源指纹](docs/PUBLICATION_SOURCE_INDEX.json)只覆盖本次三个原样选入的分析/测试文件。

## Relevance to Agent Operating Systems

CoOverlap 研究智能体推理任务落到嵌入式GPU后的执行组织。潜在关系是：上层智能体系统给出任务和时限，下层执行代码管理模型子块、资源配额、完成事件和版本生命周期。已有周期回放、记账及Trace分析用于解释响应和完整刷新代价。

目前没有统一的外部操作系统服务接口、任务接入协议或资源协商接口，没有接入灵玑OS，也未实现操作系统级跨智能体服务调度。本次新增的是分析与CPU测试能力。

## 历史源码与边界

Week2及更早的源码和记录仍保留。`PROJECT_STATUS`、`PROJECT_BRIEF`、`CODE_MAP`和Week2交接文档均已标记为截至2026-10-27的归档，其中“当前”不代表最新状态。

真实GPU入口依赖板端FlashRT/Pi0.5、PyTorch/CUDA、自定义扩展、权重、固定输入与参考数据。它们未随本次增量新增分发；未验证在新机器可部署，也不提供猜测的安装清单或未经本次核验的加速声明。

本次排除个人目录路径和权利来源待核实的新增文件；这**不消除基线及远端历史已有的路径和许可风险**。未自动补LICENSE，历史第三方材料的分发依据仍需另行核实。大数据、Trace、论文、模型和内部资料保留原存储。
