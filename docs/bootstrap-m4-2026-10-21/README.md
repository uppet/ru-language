# M4 原始验收摘要

2026-10-21，`bs`，上游基线 `649d98c399f74f1cf0a6bb89a1989bd44c8a8f4d`。范围、方法和边界见 [M4 验证报告](../bootstrap-m4-validation.md)。

- [Linux 逐代验收](linux-verification.json)、[Windows 逐代验收](windows-verification.json)：各自从 Python 引导重新构建三代，stage1／stage2／stage3 各跑同套 33 项，记录全部 99 项状态、8 个门限、51 份输入和产物 SHA-256。两平台输入内容及用例名称集合相同；Windows 原生核验由 Git Bash 启动 Windows Python 执行。
- [测试摘要](test-summary.json)：两平台完整集合、分片／跳过计数、日志 SHA-256、验收器 7 项负向控制，以及各平台专项统计。
- [325 份源码／夹具／CI 校验值](source-checksums.json)：全量运行前后保持相同的文件集合。机器相关工具、编译器及临时输入位于 ignored 目录，不收录二进制。

PE 只在内存中归一文件头及调试目录的四字节时间戳；原始文件和默认链接参数不修改。ELF 直接逐字节比较。后续源处理不使用 Python parser／模块加载器／代码生成器；宿主驱动仍为 Python，C 运行时和 LLVM 仍是构建依赖。归一不掩盖机器码或其他元数据差异。

这里是 M4 的新快照，不覆盖 [M3 历史快照](../bootstrap-2026-10-21/README.md)。测试期间有并发工作，记录的耗时不作为 Dart 性能对标数据。新增 CI 尚未在远端触发。
