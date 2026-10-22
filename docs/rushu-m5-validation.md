# M5 验收：如书原生解释内核与如观

本报告与所链接 JSON 是 rebase 前的冻结验收，保留当时的基线、源码校验值和性能样本。当前工作线已整合上游 `wip` 并同步 `另若`；后续版本的实际复验另见[整合记录](bs-wip-rebase-2026-10-22.md)，不能用本报告的旧产物哈希证明新版本通过。

M5 的交付目标是将原生如言执行内核接入持久如书会话，保留共享状态、重定义、输入、停止、诊断与历史，并接入如观图形和回调。根据用户确定的“先解释执行”路线，解释器本身由如言实现、经 LLVM AOT 编译；代码格由它解释执行。HTTP 与进程管理仍由 Python 承载，整个服务端脱离 Python 和 Dart AOT 性能对齐仍是后续目标。

本轮对应 `bs`、如言 0.23.0／如书 0.9.0，基线为 `0a200bd85e84d2f907163c07fb3a1b86cc068855`，实现尚未提交。使用方法与语言范围见[原生解释内核指南](rushu-native-interpreter.md)，原始结果与校验值见[验收摘要](rushu-m5-2026-10-22/summary.json)。M4 的历史验收数据保持原样。

**M5 的上述功能验收通过。** 当前源码、两平台产物与测量校验值相互核对一致；全部必需检查无失败、无跳过。

| 检查 | 结果 |
| --- | --- |
| WSL 完整如书回归 | 158／158 通过，含 49 项原生内核测试 |
| Windows Git Bash 原生内核回归 | 49／49 通过 |
| 临时帧所有权专项 | 两平台各 1／1 通过 |
| Windows Chrome 155.0.8059.80 | 9 场景、11 次代码格执行，0 页面错误、0 模型请求 |
| Linux ASan／UBSan／LSan 与 GC 阈值 1 | 正常路径 live=0，回调错误／坏事件／尺寸错误路径 live=0；均退出 0 |

49 项原生测试中包含 15 组标准库 golden 与 12 份如观示例子测试，子测试不重复计入顶层数量。Linux 使用 Python 3.10.12／LLVM 14.0.0，Windows 使用 Python 3.12.4／LLVM 14.0.6。源码与测试等 [284 份输入校验值](rushu-m5-2026-10-22/source-checksums.json)、[浏览器结果](rushu-m5-2026-10-22/browser-windows.json)、[sanitizer 正常路径](rushu-m5-2026-10-22/sanitizers-linux.json)及[错误恢复路径](rushu-m5-2026-10-22/sanitizers-errors-linux.json)均已保存。

## 逐项核验

| M5 要求 | 实现与直接证据 |
| --- | --- |
| 原生如言内核与明确执行策略 | `interpreter.ru` 复用原生自举词法／解析，实现客体环境与 AST 求值；`compile_native` 用 stage3 构建内核。独立产物测试清空 PATH，在临时目录运行复制的二进制，禁止 Python 解析／解释回退；两平台独立解释 factorial 得到 720 |
| 版本化工作进程协议 | RU2 显式握手，E／I 定长 UTF-8 载荷、G 输入事件、R 拒绝帧后清理；NDJSON 输出。测试非法 NUL／来源不得执行、Unicode 输入与按键换行。Sanitizer 运行实际覆盖 R 清理 |
| 持久共享状态与重定义 | 同一会话保留变量、可变别名、共享词法闭包；重新定义保留旧函数／实例。原生会话测试与浏览器共享计数器、闭包及错误后恢复 |
| 输入、输出、停止与诊断 | 输入 request_id／EOF、粘贴多行、输出合批和限额、停止无限循环、重启、定义格来源及迟到执行拒绝均沿用现有会话合同并经原生测试核验 |
| 如观绘图 API | 如言 `graphics.ru` 实现基本图元、弧／扇形／贝塞尔／折线、透明色、文字对齐、变换与裁剪；完整场景与 Python 参考结果对照，含 `1/3` 等 binary64 坐标，避免通用 15 位显示格式造成传输精度损失 |
| 缓存、资源与历史 | 一次录制、状态与点阵快照、旧句柄失效、只读尺寸、每帧完整配方；12 份已有如观示例逐项初始化／动画／输入检查，缓存太阳系配方为 515 命令、动态帧为 28 命令；真实浏览器验证像素及存档静态重放 |
| 事件与闭包回调 | 帧、鼠标按下／移动／松开、按键／松键及关闭；同一个客体函数调用器执行回调，保留变更。对照测试包括换行 Unicode 按键、暂停／继续、单调经过／间隔时间、关闭竞争与新格解绑 |
| 限额与失败清理 | 原生测试实际触发画布尺寸、状态栈、裁剪、命令、缓存数量、像素、UTF-8 帧字节、配方字节、根命令与配方合计限制；软时间、64 MiB 动态堆超限与回调输入错误关闭画布，普通会话状态保留 |
| 阻塞与工作进程寿命 | 专用原生 C 传输夹具在接收回调后阻塞于 OS 输入，10 秒看门狗真实终止 Popen、清理管道并重建进程；两平台核验 generation／PID／上下文变化。该夹具只验证进程管理，客体求值另由真实如言内核测试验证 |
| 真实前端与内存所有权 | Windows Chrome 实际操作鼠标／键盘、关闭、停止、保存重开与移动视口；同时禁用 Python parse、Interpreter.execute、GraphicsHost.create/handle。Linux C 宿主 ASan／UBSan／LSan、GC 阈值 1，核验闭包环、缓存、正常关闭、回调错误与坏事件后继续，退出 live=0 |

## 复验入口

```sh
python3 tools/build_rushu_kernel.py
python3 -m unittest discover -s tests -p test_rushu_native.py -v
python3 -m unittest discover -s tests -p test_interpreter_host.py -v
python3 -m unittest discover -s tests -p 'test_rushu*.py' -v
```

Windows 本轮在真实 Windows Python／Git Bash 下构建与运行 `.exe`；Linux／WSL 运行独立 Linux 产物。正式 Linux 回归没有指定 `RU_TEST_NATIVE_KERNEL`，测试新建并清理自己的三代自举编译器，再编译解释器，不复用可能过期的其他测试夹具。Windows 原生回归显式指定本轮已构建的 `.exe`。

真实浏览器入口需提供 Playwright 与浏览器：

```sh
python3 tools/qa_native_kernel.py --kernel bin/rushu/native-kernel --browser /path/to/chromium
```

Windows 将内核替换为 `bin/rushu/native-kernel.exe`。QA 最后关闭服务和全部原生子进程，不调用外部模型。

## 性能与范围

性能数据由当前产物重新测量，包含解析、执行、GC、IPC 与轮询；各例预热一次，两个持久内核交错各运行七次。原始样本见 [WSL](rushu-m5-2026-10-22/benchmark-linux.json) 与 [Windows](rushu-m5-2026-10-22/benchmark-windows.json)。它不比较 Dart，也不等于纯计算吞吐或冷启动性能。短格接近轮询分辨率，不据此作速度排名；密集计算仍明显慢于 Python。

| 工作负载中位数 | WSL Python（ms） | WSL 如言解释器（ms） | Windows Python（ms） | Windows 如言解释器（ms） |
| --- | ---: | ---: | ---: | ---: |
| 输出 42 | 0.639 | 1.220 | 1.084 | 1.960 |
| 简单循环 10,000 次 | 15.794 | 449.617 | 12.218 | 469.736 |
| 闭包调用 1,000 次 | 7.056 | 138.537 | 6.156 | 150.199 |
| 创建阵 2,000 次 | 2.983 | 76.471 | 3.012 | 78.919 |

原生回调的 500,000 AST 步不是 Python 跟踪行；64 MiB 预算计入动态值堆与集合容量，不是进程 RSS 上限。Sanitizer 插桩的是 C 运行时与宿主，未对如言生成的 LLVM 函数执行 C sanitizer 插桩。完整说明见指南。

本轮未整合上游 `ae1a9947e1b1b1785499967fea93c7e3ca09b37b` 的 `另若`；具名模块／包锁、如:密／如见、形典键和普通 LLVM AOT 程序的图形运行时仍不在已声明的原生前端范围。没有 ORC JIT 或自动热点编译。新增本机检查不能代表远端 CI 已运行；二进制、工具包和 `AGENTS.local.md` 不入库。

首阶段 RU1 内核的[早期验收与性能快照](rushu-native-2026-10-22/README.md)只作历史记录，不能替代本轮 RU2 的结果。
