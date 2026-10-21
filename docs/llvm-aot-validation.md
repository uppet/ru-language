# LLVM AOT M1 验证

日期：2026-10-21。工作线：`bs`，基于 `origin/wip` 的 `e485b56a503908ad23c20bc23854769d1867b7c8`；如 0.23.0／如书 0.8.8。本文记录本地验证，不能代替远端 CI 或其他平台结果。

实现和验收覆盖直接 LLVM AOT、独立原生产物与 IR、CLI 保护和首批性能对照；使用方式见 [LLVM AOT 指南](llvm-aot.md)。验收时实现尚未提交，生产/测试/工具文件按 [155 份源码校验值](benchmarks/llvm-aot-2026-10-21/source-checksums.json) 标识，不把上游基线 SHA 当作新实现提交。

本报告的完整回归、源码校验和性能样本对应 M1 的历史冻结快照。后续 Windows 工具预备/原生支持和 ASan 测试宿主配置修订已继续推进，不更新历史校验值来冒充后续工作树的全量验收；当前功能范围见指南。

## 最终完整回归

冻结实现之后执行三份确定性、不重叠的完整分片：

```sh
python3 tools/run_test_shard.py --shard 0 --count 3
python3 tools/run_test_shard.py --shard 1 --count 3
python3 tools/run_test_shard.py --shard 2 --count 3
```

每片 576 项，共 **1728 项：1682 通过、46 项真实 Windows 平台限定检查跳过、0 失败、0 错误**。三片 collection SHA-256 均为 `b68578ad283a945903cbf3295eb48b26b608ba2b67001b3477178031fae2fa19`，与整个测试集合一致；分片前后 155 份代码校验值未变。每片耗时/跳过数见 [原始结果摘要](benchmarks/llvm-aot-2026-10-21/test-summary.json)。首轮单进程 1727 项也通过，但发生在 llc 修订和新增插桩回归前，不作为最终冻结实现的验收计数。

其他本地检查：

- LLVM 专项最终 23 项全部通过，包含真实 ASan/UBSan；全部纳入上述完整集合。
- 如书 Node 342 项：329 通过、13 项显式可选真实浏览器测试跳过；0 失败。
- Emacs 30.2 严格字节编译通过；ERT 138 项全部通过。
- 四份真实 CLI 提示导出（如书/如观 × Python/browser-js）均包含当前规范全文；规范 SHA-256 为 `59103ae63f27b0bb36bd6e0d57d836f56a97fcfb71f81c466f3e1fa70f2ae2c2`，各导出摘要见 [校验值](benchmarks/llvm-aot-2026-10-21/prompt-checksums.json)。未发出模型请求。
- Python 编译检查、`git diff --check` 通过；`--full-runtime` 的 LLVM CLI 构建、Unicode 入口参数和退出码 7 另行实测通过。
- 首轮还做过十个代表性示例的 Python/LLVM 对照和 42 个扩展案例的独立预期输出对照，均通过；最终主要验收依据是冻结集合与当前 LLVM 专项。

本机为 Ubuntu 22.04 / Linux x86-64、AMD Ryzen 7 7800X3D，Python 3.10.12、Clang/LLVM 14.0.0、Node v24.4.0；工具完整版本与 CPU 记录见 [环境](benchmarks/llvm-aot-2026-10-21/environment.json)。新增 LLVM 专项 CI 配置已写入工作流，**尚未触发或取得远端 CI 结果**。

## M1 验收对应的证据

| 要求 | 实现及实测 |
| --- | --- |
| 直接如 AST → LLVM IR | 测试禁止调用 `Compiler.compile` 或外部工具，仍能生成函数/表达式/控制流 IR；真实构建也在禁止 C 程序生成器的条件下成功 |
| 明确工具链/平台/ABI | Linux x86-64 本机、LLVM 14 typed pointer；Clang 与五个 LLVM 工具检查主版本，triple/data layout 来自 Clang；Val/Env 布局与聚合 ABI 留在 C 内 |
| 验证、优化、链接、机器码 | 真实 llvm-as、llvm-link、两次 opt verify、O2、llc PIC object、Clang 链接；真实错误 IR被 assembler 拒绝 |
| 独立原生程序/独立 `.ll` | 删除根源码和依赖、换至空目录、PATH 为空时 ELF 正确输出；单独 clang-14 复编保存的含运行时 `.ll`，新程序同样正确运行 |
| 核心语义差分 | 有限数/负零/事实/短路、Unicode、参数求值次序、递归、共享闭包、作用域、对象/典/排序回调、循环引用、模块惰性初始化/失败缓存、卒/救及提前退出 |
| 来源和能力拒绝 | 导入模块错误保持文件/行列/原始片段；未知节点和不可达无效调用编译拒绝；如观/如:密、错误平台/主版本与不适用 CLI 选项拒绝 |
| 原始产物保护 | 源/依赖/符号链接与产物路径冲突拒绝；源码、严格风格、工具、验证、llc 及链接失败均不覆盖旧程序/IR，临时目录清理 |
| 首批 C/LLVM/Dart 对照 | 三种等价负载、两个规模、预热/七次交错样本、独立输出校验、时间/RSS/编译耗时/产物体积与原始数据均保存，见下节 |

## 插桩问题的复现与修复

附加压力检查发现：把已经插桩的 runtime bitcode 链接/优化后再次交给带 sanitizer 选项的 Clang 做 IR→机器码，会重复处理插桩并发生 shadow memory 访问崩溃。一个纯 C 辅助函数加 LLVM main 即可独立复现，不依赖如解析器或 Val 布局。

最终路径改为 **opt 后由 llc 生成 PIC 目标文件，Clang 只链接**。新增自动回归验证插桩的如程序在频繁 GC、共享闭包、循环引用和卒恢复下正常执行。额外 1000 轮压力程序输出全部正确，`RU_GC_THRESHOLD=1 RU_GC_STATS=1` 退出为 `live=0 freed=9014 collections=9014`。独立负向控制的真实越界访问同时触发 UBSan runtime error 和 ASan stack-buffer-overflow，确认修复保留了检查能力。初始失败、最小复现及修复日志保存在本地 `.git/bs-local/m1-sanitizer/`。

## 首批性能结果

最终冻结实现完成回归后，另行执行：

```sh
python3 tools/benchmark_aot.py --dart .git/bs-local/toolchains/dart-sdk/bin/dart --iterations 1000000 --repeats 7 --output dist/m1-aot-baseline-final.json
```

对照使用 SHA-256 校验过的 Dart SDK 3.13.6 和 `dart compile exe`；Dart SDK 仅留在本地工作目录，不进入产品。测量开始前，本会话的回归任务均已结束。每个原生程序在相同目录/硬件上运行，两次预热后交错测七次，先校验输出；未固定 CPU 频率/亲和度。下表为百万次工作负载的**整进程墙钟中位数（毫秒，包含启动和输出）**：

| 工作负载 | 如 C | 如 LLVM | Dart AOT |
| --- | ---: | ---: | ---: |
| 数值循环 | 109.544 | 156.304 | 43.109 |
| 闭包调用 | 206.106 | 279.675 | 40.429 |
| 阵分配 | 255.074 | 426.433 | 48.964 |

当前 LLVM 路径在这三项大规模样本上慢于现有 C 后端和 Dart；**M1 完成的是直接 AOT 功能与测量闭环，Dart 性能对齐尚未完成**。n=1 的数据主要反映含少量计算的启动负载，不能据小样本宣布更高计算吞吐。完整源码、逐次样本、离散范围、RSS、编译耗时与产物大小见 [原始数据和方法](benchmarks/llvm-aot-2026-10-21/README.md)。

目标为 Linux x86-64／LLVM 14，不支持如观、如:密、如见或如书 AOT 内核，尚未自举，也不作 Dart 性能达标声明。
