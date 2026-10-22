# bs 整合 wip：2026-10-22

状态：整合与下述复验通过。完整结果和校验值见[摘要](bs-wip-rebase-2026-10-22/summary.json)。

用户要求先保存 M5 和如书去 Python 计划，再将整个 `bs` 工作线 rebase 到最新 `wip`，允许改写已分享的历史。

- rebase 前完整快照：`c24acde`，父提交 `0a200bd`。
- 本次成功 fetch 的上游：`ae1a9947e1b1b1785499967fea93c7e3ca09b37b`。
- 两份工作提交重放到上游之上；上游历史与 `另若`／编辑器／许可更新保留。
- 原生如言前端增加 `另若` 保留字、迭代条件链解析和嵌套条件降低；原生解释内核复用同一解析器。`另 若` 保留原嵌套语义。
- 条件链与等价嵌套共享 128 层结构预算；表达式保留原有 100 层预算。原生编译器自身的调用深度限制未放宽，可能更早拒绝深层程序；源码预算不是可编译链长度保证。测试覆盖两种写法的接受／拒绝、超长链及错误后恢复。
- 如言／规范为 0.23.0，如书为本工作线的 0.9.0 实验版；上游如书 0.8.9 的发布历史另行保留。

旧 M1—M5 验收文件和 JSON 保留为历史快照，不修改旧测量样本或冒充 rebase 后实测。当前原生语言范围、性能与完整服务端自托管的边界继续适用；后续迁移见[如书去python计划](如书去python计划.md)。

## 实际复验

| 检查 | 结果 |
| --- | --- |
| WSL 三代自举／固定点 | 105／105，通过全部 8 项门限 |
| Windows Git Bash 三代自举／固定点 | 105／105，通过全部 8 项门限 |
| WSL 完整如书回归 | 160／160，其中原生内核 51 项 |
| Windows Git Bash 原生内核 | 51／51 |
| LLVM 专项，含复用上游 6 项条件链合同 | 两平台各 30 通过／1 项明确的平台或工具前置跳过 |
| 上游 `另若` 解析与 Python／C／JS／browser-js 合同 | WSL 53／53 |
| 版本／文档／规范／提示词／固定点门限／临时帧合同 | 两平台各 57／57，包含真实 C 运行时帧检查 |
| Node 编辑器及前端回归 | 332 通过／13 可选浏览器检查跳过 |
| Emacs 严格字节编译与 ERT | 141／141 |
| Windows Chrome 155.0.8059.80 | 10 场景、12 次执行、0 页面错误、0 模型请求 |

两平台各代都执行同一份 35 项自举合同，包含新增条件链语义和结构／资源边界；[Linux 固定点结果](bs-wip-rebase-2026-10-22/bootstrap-linux.json)与 [Windows 固定点结果](bs-wip-rebase-2026-10-22/bootstrap-win32.json)记录精确 IR／描述符、二进制比较和逐例状态。Windows 二进制只按原有规则归一明确的 PE 时间戳字段，未放宽机器码比较。

如书首轮 WSL 回归独立构建三代编译器和内核，原生测试禁用 Python 源码回退；仅一处新增测试把参数位置的期望列号误写为 6，实际正确位置是 5。修正测试后，用本轮已重新构建的产品内核复跑全部 160 项通过。Windows 同样在修正后复跑 51 项通过。版本标题格式冲突也已修正，实际版本一致性检查继续保留。

[真实浏览器结果](bs-wip-rebase-2026-10-22/browser-windows.json)包含新增 `另若` 惰性执行、共享状态、闭包、Unicode 输入、缓存像素与鼠标／键盘、画布关闭、停止／重启和历史重放。QA 同时禁止 Python parse、Interpreter.execute 和 GraphicsHost 执行回退，并在结束时关闭服务与全部内核。

LLVM 跳过项分别为 WSL 的 Windows SDK 专项、Windows 缺少的 LLVM 14 ASan 运行库；不是自举或如书回归跳过。Linux LLVM 专项中的 sanitizer 回归实际通过。本轮没有重跑整个 M5 原生内核 sanitizer 压力或性能测量，也没有运行远端 CI。

本轮 [287 份输入校验值](bs-wip-rebase-2026-10-22/source-checksums.json)与已验证文件一致；产品内核 SHA-256 记录在摘要。现有 `runtime.h`、普通 `llvm_runtime.h`、解释器 C 宿主／帧实现、图形实现和 Python 会话宿主均与 rebase 前快照一致；原生解释器源码另清理了两处行尾空白。

复验命令：

```sh
python3 tools/bootstrap.py verify
python3 tools/build_rushu_kernel.py
python3 -m unittest discover -s tests -p 'test_rushu*.py' -v
python3 -m unittest discover -s tests -p test_llvm.py -v
python3 -m unittest discover -s tests -p test_elif.py -v
node --test rushu/tests/*.mjs
make test-emacs
```

Windows 使用真实 Windows Python／Git Bash 和 `.exe`，WSL 使用 Linux ELF。版本／规范等组合命令和浏览器入口见摘要所对应源码与[内核指南](rushu-native-interpreter.md)。本地备份保留原始提交；本次未强推远端 `bs`，`AGENTS.local.md`、二进制和工具目录均不提交。
