# 首次自编译验证

2026-10-21，`bs`，基于已快进整合的 `origin/wip` `649d98c399f74f1cf0a6bb89a1989bd44c8a8f4d`；如 0.23.0／如书 0.8.8。验收时实现保留在工作树，尚未提交／推送。本轮完成 M3 的首次如言编译器自编译，在 Windows host 与 Ubuntu WSL 中分别运行真实本机程序；Windows 结果不由 WSL 代替。

下述完整回归与 265 份源码校验值是 M3 首次交付的冻结快照。后续 Windows Git Bash 修复改变了宿主驱动与专项测试，补充核验见本文末节；不把旧的全量结果当成修复后完整集合已重跑。

后续 M4 已完成三代各自的同套回归，并重新运行两平台完整集合；当前验收与新产物校验值见 [M4 报告](bootstrap-m4-validation.md)。本页保留首次交付及后续差异定位的历史快照，不将旧阶段的二进制哈希替换为当前重建产物。

## 最终三代链路

两平台分别执行：

```sh
python3 tools/bootstrap.py bootstrap
```

同一份 `bootstrap/compiler.ru` 的 SHA-256 为 `02d276dc6e1eee732a8141fdc458226e96aab9ffcaa9a222dd7aaf4520076d73`。Python 引导前端生成 stage1；stage1 编译这份如源码生成 stage2；stage2 再编译相同源码生成 stage3。后续源文件处理全部发生在原生如言编译器中，宿主驱动只准备固定运行时、调用 LLVM 和发布文件。

| 宿主 | 本机工具链／目标 | 自身 IR／描述符 | stage2／stage3 二进制 |
| --- | --- | --- | --- |
| Ubuntu WSL，Python 3.10.12 | Clang/LLVM 14.0.0，x86_64-pc-linux-gnu | 各自逐字节相同 | SHA-256 也相同 |
| Windows host，Python 3.12.4 | Clang/LLVM 14.0.6，x86_64-pc-windows-msvc19.51.36260 | 各自逐字节相同 | PE SHA 不同；不据此宣称机器码可复现 |

源码、各代 IR／描述符／二进制校验值和实际环境分别保存在 [Linux 阶段](bootstrap-2026-10-21/linux-stages.json)、[Windows 阶段](bootstrap-2026-10-21/windows-stages.json)、[原始摘要目录](bootstrap-2026-10-21/README.md)。保留的编译器位于 `bin/bootstrap/linux/stage{1,2,3}`、`bin/bootstrap/win32/stage{1,2,3}.exe`，均为忽略的本地产物。构建时间与回归并发，不作为独立性能基准。

## 回归结果

| 宿主 | 发现／运行 | 通过 | 显式跳过 | 失败／错误 |
| --- | ---: | ---: | ---: | ---: |
| WSL，三个不重叠分片 | 1746 | 1700 | 46 | 0／0 |
| Windows host，完整发现 | 1704 | 1512 | 192 | 0／0 |

Linux 三片各 582 项，collection SHA-256 为 `f45b75978e57241dfc8fcc567cf783e68c829bbf52d45cf6f41bd41eac81b755`。Windows 的发现数量受平台／可用工具控制的用例生成影响，不假定与 Linux 是相同集合。分片结果、耗时、日志校验值及 Windows 跳过原因见 [结果摘要](bootstrap-2026-10-21/test-summary.json)。

两平台新增自编译专项 **10 项均真实通过**；Windows LLVM 专项 23 通过、1 项因没有 ASan 运行库跳过，预备脚本 5 项通过。Windows 的 192 项跳过还包含既有 PATH C 编译器前置及 POSIX 专项；项目内 LLVM 不改 PATH，因此旧测试的 PATH 探测仍可能跳过。不能把这些跳过写成 GCC／DLL／POSIX 能力验收。

最终 C 压力测试出现过 ASan PIE 无输出 SIGSEGV；同宿主的纯 C 空 main 也能复现，非 PIE 对照 30/30 正常。仅给 `test_panic.PanicTests.test_native_sanitizer_stress` 的 Linux 测试映像增加 `-fno-pie -no-pie`，保留 ASan／UBSan 与泄漏／精确 GC 检查。AST 校验确认测试文件其他函数未变，其余 264 份代码／夹具哈希不变；重跑包含该用例的 Linux 分片 0，582 项通过（14 跳过），并复跑 Windows 对应文件，12 项中 9 通过、3 跳过。上表使用分片 0 的修订后结果及未受影响的分片 1／2，未删改原始失败日志。[重跑范围](bootstrap-2026-10-21/sanitizer-retest-scope.json) 与 [最终 265 份校验值](bootstrap-2026-10-21/source-checksums.json) 留作接续依据。

## 独立性与示例

- 后续驱动在 Python 解析器、模块加载器、C／LLVM 代码生成入口全部设为报错的条件下，仍通过原生如言前端完成构建。
- 将原生编译器和独立测试源复制到空目录，清空 PATH，成功生成 LLVM／描述符／源文件清单，并由真实 assembler 验证；前端执行不调用 Python 或读取项目编译器源码。
- 删除目标程序源码、清空 PATH 后运行；保存的含运行时 IR 可独立复编，Unicode 入口和退出码验证通过。
- 函数／闭包／具名参数求值顺序、binary64 边界、Unicode、容器、继承与覆写、方法／块／救闭包、模块失败缓存、卒恢复及 `live=0` 验证通过。
- 30 个受 Git 跟踪的顶层示例，在 **两平台各 30/30 正常退出**，输出与该宿主的参考解释器一致。每例使用合适输入，保存输入／参数／退出码／输出 SHA；加法、会话和三项竞赛程序另有独立预期输出。见 [Linux 示例](bootstrap-2026-10-21/linux-examples.json)、[Windows 示例](bootstrap-2026-10-21/windows-examples.json)。
- 示例差分发现的覆写误拒绝已修复：参数阵按身份比较不适合签名验证，现逐项比较参数名与类型，并覆盖零参数、带参数、合法覆写及非法改名。最终阶段、示例与回归数据均对应修订后源码。
- 原生前端与驱动的源／依赖输出保护、工具失败不覆盖旧产物均通过；Windows 普通 `--target llvm` 与 stage3 构建的阶乘均输出 720。

四种真实提示导出均含当前完整规范，规范 SHA-256 为 `2735ecba1d58115b8699a95dc33004c5b59bc902dfcfc473fa70899cfd3d6a67`，见 [提示校验值](bootstrap-2026-10-21/prompt-checksums.json)。没有发送模型请求。新增 Windows／Linux LLVM 自编译 CI 矩阵尚未在远端触发，以上为本地实测。

## 交付边界

这是有明确语言范围的首次自编译，不是完整 Python 前端／包工具链的替换，也不是 M4 全语言一致性或跨平台机器码可复现性完成声明。Unicode 13 分类、具名模块／包锁、路径别名及跨模块类型身份等边界见 [运行指南](bootstrap.md)。构建驱动仍依赖 Python，原生前端的词法／解析／语义／LLVM 发射由如源码完成。未实现如书 AOT 内核／如观／如:密，也未达到或宣称 Dart AOT 性能对齐；M1 原始性能数据继续作为历史基线保留。

## Windows Git Bash 补充核验

2026-10-21，实际 Windows Git Bash 登录并读取用户启动文件后，复现 `math.h file not found`。该启动文件将 MSYS/GCC 的冒号路径列表写入 `INCLUDE`／`LIB`；仅移除 `INCLUDE` 会继续遇到链接错误，两者移除后同一 Clang 编译、链接、执行正常。Windows MSVC 目标期望分号列表，且这些环境变量会取代 SDK 自动搜索。驱动现仅在工具子进程中忽略 POSIX 格式的搜索列表，保留有效 Windows／VS 设置和父环境；预备检查还新增真实 CRT 与 Windows SDK 头文件及 API 链接检查。

修复后，在仍加载原启动文件、没有设置 `PYTHONUTF8`／`PYTHONIOENCODING` 的 Git Bash 中，工具预备、完整 stage0→1→2→3、原生前端与普通 LLVM 构建全部通过，自身 IR／描述符再次逐字节相同。用户已修改的阶乘示例输出 `3628800, 720, 5040, 40320`（逐行），与 cmd.exe 复验一致；没有改写该示例。中文诊断输出已明确使用 UTF-8。

环境保护、工具预备、LLVM、自举四组专项在 Git Bash 和 WSL **各运行 43 项，42 通过、1 显式跳过，0 失败／错误**；Windows 跳过缺少 ASan 运行库，WSL 跳过新增 Windows SDK 专项。另在 WSL 验证 C 构建发布与编译器参数 6 项通过。[补充摘要与阶段校验值](bootstrap-2026-10-21/git-bash-followup.json) 单独记录，不覆盖首次交付快照。CI 已添加带冲突变量的 Windows Git Bash 三代构建，尚未在远端触发。

## Windows 二进制差异定位

随后对当前保留的 `bin/bootstrap/win32/stage2.exe`／`stage3.exe` 逐字节比较，并以 `llvm-readobj-14` 复核 PE 结构：两份文件均为 1,423,872 字节，仅 2 个字节不同，分别在偏移 `0x100` 的 `IMAGE_FILE_HEADER.TimeDateStamp` 和 `0x151734` 的 `IMAGE_DEBUG_DIRECTORY[0].TimeDateStamp`。两个字段各占 4 字节，本次恰好各只有低 1 字节不同：均从北京时间 2026-10-21 20:28:48（`0x6AD8B000`）变为 20:29:03（`0x6AD8B00F`）。机器码 `.text`、数据和重定位等其余内容一致；`.rdata` 中的唯一差异正是上述调试目录时间戳。

仅在内存中把两个时间戳字段置零，整份文件逐字节相同，归一后的 SHA-256 均为 `54505b41982b85f5e0e3a380c09a98ecf55bd82c20c753b87cba69ab0a1fd91e`。原始二进制没有修改，链接参数也没有调整。Git Bash 验证目录的另一组产物也只差同样两个时间戳字段（其调试目录字段偏移为 `0x151824`）。因此当前已将二进制差异精确定位为链接时间元数据，并非机器码代际漂移；这不表示默认构建已开启可复现链接。

两组当前保留产物的自身前端 IR／描述符仍分别逐字节相同，含运行时 `.ll` 仅首行 `ModuleID` 注释中的临时目录名不同。这次检查的默认目录已使用 MSVC 14.44 重建，首次 M3 报告与 Git Bash 目录的 MSVC 14.51 快照仍独立保留，不混用文件大小或哈希。完整逐字段／分段校验值见 [PE 比较摘要](bootstrap-2026-10-21/windows-pe-comparison.json)，字段定义见 [Microsoft PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)。
