# 首次自编译的原始验证摘要

2026-10-21，`bs`，基线 `649d98c399f74f1cf0a6bb89a1989bd44c8a8f4d`。本目录只保存可审阅的结果与校验值，不包含下载的工具或二进制。完整方法和边界见 [验证报告](../bootstrap-validation.md) 与 [运行指南](../bootstrap.md)。

- [Linux 三代构建](linux-stages.json)、[Windows 三代构建](windows-stages.json)：相同如言源码，经各自真实本机 LLVM 14 构建 stage1→stage2→stage3，保存前端 IR／描述符／二进制校验值。阶段记录来自最终保留在 `bin/bootstrap/` 的编译器。
- [Linux 环境](linux-environment.json)、[Windows 环境](windows-environment.json)：Python／Unicode、目标 triple／layout、六工具版本。Windows 还真实通过 HTTPS 下载一个固定小包并核对 SHA，以验证预备脚本的原生下载路径；完整工具包已经真实执行／链接验收。
- [Linux 示例](linux-examples.json)、[Windows 示例](windows-examples.json)：全部 30 个受 Git 跟踪的顶层 `.ru` 示例，用各自 stage3 构建，再与该宿主的参考解释器对照。每例保存明确的输入、参数、退出码和输出校验值；全部正常退出。加法、会话、三项竞赛程序另核对独立预期输出。
- [265 份代码及夹具校验值](source-checksums.json)：最终生产、如源码编译器、测试、工具、如书静态资源及 CI 的 SHA-256。验收时新增实现尚未提交，基线 SHA 不代表这些新增实现的提交。
- [提示词校验值](prompt-checksums.json)：四种实际 CLI 导出均含本轮完整规范，未发送模型请求。
- [ASan 测试重跑范围](sanitizer-retest-scope.json)：完整回归遇到既有 C 压力测试的 PIE 启动问题后，只改变该测试的 Linux 映像选项；AST 检查确认没有修改其他函数，其余 264 份文件未变，重跑受影响的 Linux 分片及 Windows 的对应测试文件。

构建时间采样与回归任务并发，包含前端进程启动／文件读写和宿主工具开销；未隔离 CPU、缓存或调度，不能据此作性能排名或 Dart AOT 对齐声明。Windows 二进制 SHA 不相等；本轮固定点验收要求同平台的前端 IR 和描述符逐字节相等，不承诺跨平台或所有机器码构建的可复现性。
