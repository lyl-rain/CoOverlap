# CoOverlap

**Predictable Chunked VLA Execution on Embedded GPUs**

CoOverlap 研究固定模型计算和周期预算下，真实 VLM/Context 与 Action Expert 的 GPU 执行组织。主实验平台为 Jetson AGX Orin 64GB，当前候选负载为 FlashRT / Pi0.5。

本仓库保存 M1 第一周的独立适配层、正确性检查、profiling、周期回放、Green Context 功能探针和离线分析源码。不同版本对应不同阶段的实际实验；历史失败路径保留，不表示所有脚本均已通过或适合直接运行。

## 当前研究状态

- 固定工作量：BF16、双视角 224×224 图像、49 个语言 token、Encoder 长度 561、18 层 Encoder、动作长度 50、完整 10 步 Expert 去噪。
- 已完成两档预算的有限周期回放、独立重复和固定 CPU 访存干扰验证。
- 限定 Encoder 路径已有串行、普通双流、固定 8+8 SM 和合法边界归还的数值检查及真实 Kernel 时间线。
- 边界归还缓解了固定分区的尾段损失，但未取得相对串行的完整窗口优势；当前双块周期计划也未显示稳定改善。
- M1 有限测量已提交收口审核。B1/B2 路线尚未由用户确认，未进入 M2。

详细状态见 [项目状态](docs/PROJECT_STATUS.md) 和 [项目简报](docs/PROJECT_BRIEF.md)。历史 FAIL、INCOMPLETE 和 UNKNOWN 均保留；有限样本不代表可靠 p99.9、最优 k 或稳定性能收益。

## 目录

```text
scripts/                 本项目编写的验证、执行、采集和分析源码
patches/                 隔离诊断资源查询的最小差异
docs/PROJECT_BRIEF.md     研究目标、边界与验收标准
docs/PROJECT_STATUS.md    各阶段事实、负面结果与当前状态
docs/CODE_MAP.md          代码入口与版本说明
AGENTS.md                项目协作与实验规则
```

## 使用前提

本仓库是已测实验的源码归档，不包含一键部署所需的全部外部资源：

1. GPU 脚本依赖板端已验收的 FlashRT 源码、PyTorch/CUDA 环境及隔离诊断扩展。
2. 真实 checkpoint、固定输入与统一数值参考、编译产物、部署清单和原始 trace 保存在独立实验存储中，未上传到 GitHub。
3. 部分历史入口固定了板端路径、资源 SHA 和单次运行协议；直接复制到另一台机器不能视为复现成功。
4. 涉及频率节点、systemd 或采集权限的脚本须先审查其白名单、资源归属和恢复路径。不要从历史命令直接启动新的模型批次。

所有阶段版本和限制见 [代码入口说明](docs/CODE_MAP.md)。FlashRT、CUDA、PyTorch 等第三方组件遵循其各自许可；模型权重不在本仓库中分发。

## CPU 检查示例

以下检查使用假资源与静态代码断言，不加载 checkpoint、不执行 GPU 模型、不写真实频率节点：

```bash
python3 scripts/validate_root_trace_cpu_v9.py
```

它验证 v9 权限例外、账本、身份限制和既有数学路径的静态一致性，不能代替板端数值或性能验收。

## 数据管理

GitHub 仅保存源码和必要的小型说明文档。`.gitignore` 排除了模型、输入快照、大型原始实验数据、原始 trace、编译扩展、凭据、环境、演示文稿和内部任务书。完整实验结果与 SHA 清单保留在项目本地及板端存储；代码中的相关路径不意味着这些数据已包含在仓库。

本次 GitHub 归档没有启动新的模型进程，也没有修改设备状态。
