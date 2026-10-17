# M1 源码入口与版本说明

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

上表中的短文件名同样位于 `scripts/`。完整阶段事实、失败与适用范围以 [PROJECT_STATUS.md](PROJECT_STATUS.md) 为准。

## 隔离资源查询补丁

`patches/GEMM_RESOURCE_INFO.patch` 保存本项目提出的只读资源 getter/绑定差异；实际隔离诊断扩展使用 `scripts/gemm_resource_diag_bindings.cpp`。它不代表已覆盖生产 FlashRT，也不是自动修改第三方源码的命令。适配时须核对目标版本的成员定义和分配容量。

## 版本与复现

- `v4`、`v7`、`v9` 是不同用途的冻结实验版本；不能把后缀更大简单理解为所有旧入口的替换版本。
- 旧 Graph、Vision 并发、权限和超时失败脚本保留用于追溯，不能把它们标作已修复或重新启动来替代原始记录。
- 一些部署器要求 `APPROVED_CONFIG.json`、`DEPLOY_SHA256.txt`、`unified_reference/`、既有二进制扩展和原始证据。这些由具体实验的冻结部署生成，不在本次公开源码上传范围内。
- 固定 checkpoint 与 FlashRT 不是本仓库的一部分。依赖版本、输入和参考必须与具体实验协议一致，不应为了跑通而更换精度、减少层数或去噪步骤。
- 本仓库不包含机器人闭环验收、通用 M2 版本回收器或最终论文的完整评测框架。
