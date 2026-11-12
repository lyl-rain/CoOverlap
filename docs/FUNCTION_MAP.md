# 主线集成候选功能映射

| 文件 | 实际功能与依赖 | 验证与限制 |
|---|---|---|
| [m2_executor](../scripts/m2_executor.py) | 标准库 + period_obligation_stats；KV 生命周期、合法工作、版本与读者、回放统计 | CPU 假 Event 合约，不执行模型或 GPU |
| [m2_replay_driver](../scripts/m2_replay_driver.py) | m2_executor；有限回放及失败账本 | 通过原有符号后端测试；真实模型回调未集成 |
| [period_obligation_stats](../scripts/period_obligation_stats.py) | 原 main 的标准库期限记账 | 7类原有检查；不改分母或迟到定义 |
| [validate_m2_cpu](../scripts/validate_m2_cpu.py) | 上述合约与回放 | 保留20项原断言；3项适配器相关测试未纳入 |
| [Trace 分析](../scripts/day1_pm_cpu_trace_repair_20261111/analyze_trace.py) | 标准库 SQLite/CSV；区间并集与交集 | 合成区间测试；真实记录结构需匹配 |
| [CPU 间隙](../scripts/day1_pm_cpu_trace_repair_20261111/analyze_cpu_gaps.py) | Trace 分析；API 已开始／在途／已返回待执行记账 | 合成检查不证明设备就绪或全 GPU 空闲 |
| [profiling](../profiling/__main__.py) | 实际分析器导航与合成检查 | 无模型或原始数据依赖 |
| [tests](../tests/runner.py) / [兼容入口](../tools/check_cpu.py) | 四组显式 CPU 命令 | 不自动发现历史 GPU 测试 |

所有运行入口见 [README](../README.md)。原 main 的 CUDA/Green Context/模型脚本继续位于 scripts，属于历史保留范围；本轮没有验证它们的部署依赖、数值或性能，不将其包装成统一 GPU Runtime。
