# 分支规范与迁移准备

分支表示整棵代码树的版本和开发工作，不是模块目录。功能最终通过PR进入主线，不给各模块永久保留独立项目。

## 本轮实际核对

GitHub默认分支仍为main。只读分支查询结果：

| 原分支 | 当前SHA | 新功能名称（仅本地引用） |
| --- | --- | --- |
| main | 1370ec89dd67c0cc6bf1c9fdcf9eb47dee9b7127 | vla-runtime |
| codex/week2 | f68c4dd05b35104dbf3d112431f7dec51daf7782 | runtime/chunked-execution |
| codex/publication-safe-20261112 | 57dc65fb650b172f6ff80b7e4a3d427f3fe5739b | analysis/trace-validation |
| codex/local-audit-20261111（未公开） | e9ed47a01d3efc1c4eff7ae8cdd3d539564623fb | maintenance/source-inventory（仅本地） |

4个新名称在创建前无冲突，均指向原提交，旧分支保留，没有模拟远端更名。它们未绑定旧远端名作为上游，以免误推。

本轮改动在独立worktree的maintenance/runtime-structure；原安全发布和完整整理worktree仍占用旧分支，桌面研究工作区仍占用codex/week2，未切换或覆盖未提交工作。不同克隆有独立的worktree注册，不应根据同名分支假定共享工作区。

当前vla-runtime只是旧main的本地名称准备，内容仍较旧，不代表最新代码已合入或稳定性验收。

## 远端阻断条件

开放的 [PR #1](https://github.com/lyl-rain/CoOverlap/pull/1) 以codex/publication-safe-20261112为head、codex/week2为base，目前draft=false。不能继续沿用此前“没有PR”的旧状态。

分支列表报告protected=false，rulesets返回空数组；详细main保护接口返回403，因此不能完整确认保护设置或管理权限，不能把接口拒绝当作没有保护。

[GitHub官方说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/renaming-a-branch)：改名会更新保护策略和开放PR的base，但若改的是开放PR的head，该PR会关闭。raw URL和git pull旧分支名也不会自动跳转。

因此本轮停止所有远端改名、默认分支切换和PR操作，仅准备本地引用与方案。

## 旧名称引用核对

已跟踪树没有.github工作流。旧分支名主要出现于忽略规则说明、历史Week2交接和WEEK2_SOURCE_INDEX.json。忽略规则说明已改为功能中立；历史文档与来源索引保留原分支名以便追溯，不伪改原指纹。工作tree的上游/分支引用记录在本地Git配置中，改名时需逐个核对。

## 经单独批准后的安全顺序（本轮未执行）

1. 先处理PR #1并核实最新base/head/保护规则；优先完成现有审查，避免因head改名关闭PR。不替用户合并。
2. 将获准的Week2与分析工作正常合入稳定主线，再审查maintenance/runtime-structure的功能组织增量；不把source-inventory推送，其含未公开研究源码。
3. 有管理权限时使用GitHub官方Rename功能处理默认分支main→vla-runtime，随后独立核验default_branch、保护/ruleset、PR目标和页面链接。与“新建分支再切默认”区别记录。
4. 其余功能分支待没有受影响开放PR、worktree已确认后，按需官方更名。开发结束可仅保留历史，不要求永久存在所有功能分支。
5. 每个克隆分别核验旧/新SHA后更新本地名称和上游；不强制改名，不覆盖已存在的新名称，不prune/delete未确认引用。源码中的raw分支URL、外部引用和CI引用另行更新验证。
6. 如果官方Rename不可用，只能另行批准“创建同SHA新远端分支、旧分支保留”的迁移；先明确PR与默认分支安排，不能创建后删除旧分支假称已改名。

长期前缀采用runtime/*、scheduler/*、analysis/*、tests/*、maintenance/*；vla-runtime作为经确认的稳定主线名称。本地准备不是远端命名已完成。
