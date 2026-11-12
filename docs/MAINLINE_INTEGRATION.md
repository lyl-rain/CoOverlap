# 主线集成与阶段交接（2026-11-12）

## 来源与边界

集成起点 main：`1370ec89dd67c0cc6bf1c9fdcf9eb47dee9b7127`。选取来源：公开归档 `archive/legacy-runtime` 的 `9408bf9283bc72d534651273cef1dce69652580f`。集成分支：`integration/vla-runtime`，已推送至 GitHub 并建立 [PR #3](https://github.com/lyl-rain/CoOverlap/pull/3)。本轮授权为文档状态修订、CPU 复验及通过后使用普通 Merge Commit 合入 main；不切换默认分支、不删除归档。

## 已形成的真实能力

版本化 KV 的构建／发布／读者固定／安全回收、固定时钟有限回放及失败完整账本、期限记账、离线 Trace 区间和 CPU API 提交间隙分析。前两份源码原样引入；模型计算与真实 GPU 执行不在候选验证范围。分析源码保留原路径与字节，入口导航不重写分析算法。

## 测试范围调整

原 `scripts/validate_m2_cpu.py` 有23项测试。当前版本保留20项原方法，方法 AST 与归档一致。仅移除以下3项及其专用未使用导入，没有修改剩余断言，也没有伪造模型代码：

| 未纳入测试 | 原因 |
|---|---|
| `test_model_math_ast_equals_frozen_v4` | 读取未选入的 m2_pi05_ops.py，来源链尚未解决 |
| `test_call_observer_rejects_actual_missing_model_work` | 导入同一未选入适配器中的 CallLedger |
| `test_gpu_entry_dry_run_and_no_approval_gate` | 调用未选入的 pi05_m2_correctness.py 及模型执行依赖 |

GPU 数学等价、实际模型调用完整性及该 GPU 入口的拒绝/授权行为均未由候选证明。没有将这3项算作通过，当前规范套件是20项合约测试 + 7类期限检查 + 6项 Trace 合成测试 + 5项入口回归测试。

## 依赖与排除

运行入口仅使用 Python 标准库与仓库内选定的模块；两个期限源码沿用 main，和归档字节一致。选中源码指纹见 [PUBLICATION_SOURCE_INDEX](PUBLICATION_SOURCE_INDEX.json)。

原9个个人路径文件、FlashRT 上游/根许可不明源码与 m2_pi05_ops 关联适配器均未选入。没有复制 reports 下的冻结副本。完整代码和原始实验仍在原归档/本地研究版本，没有因为排除而丢弃。

## 剩余限制与下一阶段

- 原 main 历史保留，本轮不能清除其中已有个人路径和既有第三方关联源码风险。
- 没有新增 GPU 数值/性能验证，CPU 合约不能证明真实模型正确、SM 限制生效或违约率改善。
- 真实 Trace 分析需要未附带且结构匹配的输入，当前只运行合成检查。
- 本地旧 vla-runtime 引用保持原位置；main 合并已有通过复验后的明确授权，官方更名及分支删除仍不在本轮范围，不能强制覆盖本地引用或工作树。
- 此集成通过 PR #3 审查与追溯；最终合并状态和 Merge Commit 以 PR 记录为准。文档修订不扩大功能或公开范围，不引入整个归档历史。
