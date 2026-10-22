# 如书原生解释内核验收 · 2026-10-22

本记录对应 `bs` 的未提交解释内核实现，基线提交为 `0a200bd85e84d2f907163c07fb3a1b86cc068855`，如言 0.23.0／如书 0.9.0。它验证用如言编写、LLVM AOT 编译的 AST 解释进程，不代表代码格本身已经 AOT 编译，也不代表完整 M5 或 HTTP 服务端自托管已完成。使用与边界见[原生解释内核指南](../rushu-native-interpreter.md)。

## 功能与平台

| 检查 | 本机结果 |
| --- | --- |
| WSL 全部如书相关测试 | 148 通过，0 失败／跳过；含原生内核 39 项 |
| Windows Git Bash 原生内核测试 | 39 通过，0 失败／跳过 |
| 独立临时帧所有权检查 | WSL、Windows 各 1 项通过 |
| Windows Chrome 真实浏览器 | 6 场景、10 次执行请求，0 页面错误；未调用模型 |
| Linux ASan／UBSan／LSan | 退出 0，无 sanitizer 错误；GC 阈值 1，退出 `live=0` |

原生测试独立构建 stage1→stage2→stage3，再用原生前端构建解释器；构建解释器和执行代码格时禁止 Python 解析／解释回退。Windows 本轮显式使用真实 Windows 构建的 `.exe`。39 项原生测试中的一项包含 15 组标准库 golden 子测试，不能把它们再加到顶层测试数量。

临时帧检查覆盖标量／字符串覆盖、同槽重复写入、嵌套返回到调用者与 C 栈、重复清理、空帧、移除非顶层帧及最终无存活堆对象。Sanitizer 运行覆盖闭包与容器环、普通错误后继续、Unicode 输入、来源含 NUL 的坏帧不得执行及后续正常执行。

浏览器检查共享状态、闭包、错误后继续及可导航诊断、Unicode 输入、停止无限循环与清空状态、保存重开不自动执行。HTTP 宿主仍为 Python；浏览器检查也明确禁用 Python 代码格执行。

WSL：Linux x86-64、Python 3.10.12、Clang/LLVM 14.0.0；Windows：Python 3.12.4、LLVM 14.0.6、Git Bash、Chrome 155.0.8059.80。这些是本机结果，未据此宣称远端 CI 已运行或通过。

## 实测格延迟

同机持久会话、每例预热一次、两个内核交错运行各 7 次，取完整格延迟的中位数。包含解析、校验、执行、GC、IPC 与 0.5 毫秒轮询，排除启动；没有固定 CPU 亲和性。这不是纯计算吞吐、首次冷启动或 Dart 比较。短格数字接近轮询精度，不作速度排名。

| 工作负载 | WSL Python（ms） | WSL 如言解释器（ms） | Windows Python（ms） | Windows 如言解释器（ms） |
| --- | ---: | ---: | ---: | ---: |
| 输出 42 | 0.651 | 1.230 | 1.015 | 1.006 |
| 简单循环 10,000 次 | 16.284 | 606.161 | 12.118 | 453.163 |
| 闭包调用 1,000 次 | 7.076 | 166.780 | 6.032 | 139.125 |
| 创建阵 2,000 次 | 3.004 | 105.918 | 2.998 | 75.997 |

本版短格响应可以支撑交互验证，密集循环／调用明显慢于 Python 内核，尚未达到性能目标。解释器自身的 AOT 编译没有消除动态值、查名、AST 分派及 GC 开销；后续应基于这些数据优化，而不是宣称已对齐 Dart AOT。

重测入口：

```sh
python3 tools/benchmark_rushu_interpreters.py --native-kernel bin/rushu/native-kernel -o NEW-REPORT.json
```

Windows 使用 `bin/rushu/native-kernel.exe`。输出文件必须不存在，避免覆盖既有测量。

## 数据与范围

- [摘要与产物校验值](summary.json)、[283 份源码／测试／资源校验值](source-checksums.json)。产物、工具包与本地记忆不入库。
- [WSL 原始计时](benchmark-linux.json)、[Windows 原始计时](benchmark-windows.json)，保留各次样本与输出校验。
- [浏览器结果](browser-windows.json)、[sanitizer 结果](sanitizers-linux.json)。Sanitizer 仅对 C 运行时 bitcode 与最终 Clang 链接加入 address/undefined、frame-pointer、非 PIE 参数；LLVM 源码前端及生成的客体 LLVM 函数本身未被 C sanitizer 插桩。

HTTP 服务端、进程适配与构建驱动仍需 Python；如观、原生 DLL、具名模块／包锁、形典键尚未接入。2026-10-22 收尾时成功获取的 `origin/wip` 为 `ae1a9947e1b1b1785499967fea93c7e3ca09b37b`，新增 `另若` 和版本同步；本工作树尚未整合，不能声称原生前端支持这一上游新增语法。M4 的历史验收记录保持原样。
