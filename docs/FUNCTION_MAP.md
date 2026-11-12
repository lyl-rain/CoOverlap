# 核心功能映射与迁移边界

仅覆盖已读的Git源码与实际调用，不把目录名、阶段总结或文件存在当验收。A=独立工具可迁移；B=依赖联动需验证；C=冻结/历史或板端环境专用，留原位。

| 现有文件路径 | 主要功能 | 调用依赖 | 本轮验证状态 | 建议处理 |
| --- | --- | --- | --- | --- |
| `tools/check_cpu.py` → `tests/runner.py` | 显式CPU检查清单与超时 | 标准库subprocess；原3组脚本＋入口回归 | 新旧CLI与干净目录验证 | A：运行器迁至tests，旧路径兼容 |
| `tests/test_entrypoints.py` | 路径、入口与冻结指纹回归 | tests/profiling CLI、原来源索引 | 5项CPU测试 | A：集中tests，避免误发现GPU脚本 |
| `scripts/m2_executor.py` | Runtime KV与合法块契约 | period_obligation_stats；后端Event | 23项既有CPU合约 | B：保持原位；移动须修改所有平铺导入及部署组装 |
| `scripts/m2_pi05_ops.py` | VLM/Expert数学回调与调用账本 | m2_executor；注入的模型对象 | 既有CPU套件覆盖工作序列/AST，非GPU | B/C：不合并不同批次数学实现，不改SHA |
| `scripts/m2_clean_backend.py`、`m2_clean_cuda.py` | Runtime提交、状态留存、事件与CUDA适配 | m2_executor、m2_clean_core；运行时注入Torch/设备 | 静态依赖核对；GPU未运行 | C：目标设备/参数绑定，保留路径 |
| `scripts/pi05_m2_clean.py` | 实际模型与周期执行入口 | prepare、CleanBackend、CudaDevice及外部模型/参考 | 只读源码，未启动 | C：不能包装成无依赖Runtime命令 |
| `reports/m3_b2/20261023/graph_prototype_v1_r1/deployment/graph_backend.py` | Graph历史真实API适配 | 同快照执行器、CUDA对象及配置 | 本轮未执行Graph | C：历史快照留原位，功能链接不等于验收 |
| `scripts/green_runtime_resource.py`、`green_context_*probe.cu` | GPU Context/资源与执行探针 | ctypes ABI、Driver/Runtime CUDA接口 | 静态核对，未编译/运行 | C：不混入新统一GPU包 |
| `scripts/period_obligation_stats.py` | Scheduler期限/完整义务记账 | 标准库；回放提交完成区间 | 7项期限检查 | B：可迁移但必须同步所有导入与冻结引用，本轮不动 |
| `scripts/m2_replay_driver.py`、`m3_b2_core.py`、`m3_b3_plan.py` | 固定释放、合法边界派发及块状态计划 | VersionedKV、后端回调、retention_layout | 基线回放CPU覆盖部分；不升级调度/性能验收 | B/C：按批次导航，不重排执行 |
| `scripts/day1_pm_cpu_trace_repair_20261111/analyze_trace.py`、`analyze_cpu_gaps.py` | Profiling API关联、区间重叠及提交空隙 | 标准库SQLite、NVTX/Host记录；后者导入前者 | 合成区间6项；实际Trace本轮未重算 | C/B：原样保存来源SHA，新增profiling导航/检查入口 |
| `scripts/pi05_quota_sweep_v10.py`、`plot_quota_sweep_v10.py` | Benchmark配额响应采集与已有数据绘图 | 板端执行、配额ABI、固定输入/参考 | 只读入口；采集脚本顶层有写出 | C：必须配置和审批；不为help直接执行 |
| `scripts/plot_b2_replay_svg.py` | 保存回放的Host时序绘图 | 固定报告JSON；顶层读/写 | 源码核对，无实际数据重算 | C：保留负面/未完成数据，未提供通用CLI |

## 组织原则

物理迁移仅发生于CPU运行器，原工具路径仍可用；新增profiling和tests目录都含实际可执行代码。Runtime、Scheduler、Benchmark作为功能层链接旧入口，暂不创建对应空目录。所有已有scripts与reports源码、冻结指纹、原始数据保持。

模块调用关系见README；不要通过更高版本文件名自动选择后端。原代码地图保留归档内容，新功能导航应先读本表。
