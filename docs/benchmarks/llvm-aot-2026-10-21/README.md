# 如 LLVM AOT M1 原始测量

2026-10-21，bs 如 0.23.0，Ubuntu 22.04 / Linux x86-64，AMD Ryzen 7 7800X3D。Clang/LLVM 14.0.0；Dart SDK 3.13.6。完整环境、工具版本和 SDK 下载摘要在 [environment.json](environment.json)。

- [raw.json](raw.json)：如/Dart 完整负载源码、实际构建命令、各自产物摘要和体积、编译耗时，以及 n=1 / n=1000000 的全部样本、RSS 和中位数/最小/最大值。
- [source-checksums.json](source-checksums.json)：最终验证使用的 155 份生产/测试/工具文件 SHA-256；其余来源以 `e485b56a503908ad23c20bc23854769d1867b7c8` 为基线。
- [test-summary.json](test-summary.json)：1728 项完整集合的三个确定性不重叠分片，collection SHA 一致；1682 通过、46 平台跳过。
- [prompt-checksums.json](prompt-checksums.json)：四种当前规范完整提示词的真实导出摘要。

raw.json SHA-256：`41a6f171368b9c3bd5f038c042dd496d99097f482aa1ad857c2630ce5a836594`。

## 重复执行

准备 LLVM 14 和 Dart SDK 后，在仓库根运行：

```sh
python3 tools/benchmark_aot.py --dart /path/to/dart --iterations 1000000 --repeats 7 --output dist/aot.json
```

程序和源码生成至忽略的 `bin/aot-benchmark/`。每个可执行程序先核对独立计算的预期输出，再预热两次；七次正式测量按固定随机种子交错后端顺序。C 和 LLVM 均用 clang-14，LLVM 自己的工具匹配版本；Dart 使用原生 `compile exe`。源码中的算术负载在选定规模下具有相同的有限 binary64 数值结果，保留各语言自身必要的类型/有限性和运行时检查。

测量值是经 GNU time 启动原生程序后的**整个进程墙钟时间**，包括创建进程、运行时启动、计算与输出；峰值 RSS 来自同一个子进程，单位 KiB。n=1 仅是启动占比较大的负载，不是隔离后的初始化耗时；大规模值也不是纯计算内核耗时。编译耗时另计，不混入执行时间。

正式测量前本会话的回归任务已结束；未固定 CPU 频率/亲和度，文件位于 WSL 挂载盘，系统缓存与调度会影响结果。源码和算法等价不等于实现方式相同：Dart 和如采用不同的值表示、优化及 GC。三个微基准不覆盖完整编译器、如书应用、图形或全部集合/GC行为，不能外推为整体语言性能排名。

百万次的如 LLVM 中位数分别为 156.304 / 279.675 / 426.433 ms，Dart 为 43.109 / 40.429 / 48.964 ms；**尚未性能对齐**。小规模结果不可用于掩盖这项差距。完整 M1 验收和限制见 [验证报告](../../llvm-aot-validation.md)。
