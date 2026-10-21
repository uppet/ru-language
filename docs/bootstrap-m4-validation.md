# M4：自举固定点与逐代一致性验收

2026-10-21，`bs`，上游基线 `649d98c399f74f1cf0a6bb89a1989bd44c8a8f4d`。**M4 验收已完成。** 按 [自编译指南](bootstrap.md) 声明的原生前端范围验收；不把首次自编译等同于完整 Python 前端／包系统替换。固定 C 运行时和本机 LLVM 仍是工具链依赖，宿主构建驱动仍为 Python；后续源码处理由如言原生编译器完成。

## 验收要求与实际结果

两平台分别实际执行：

```sh
python3 tools/bootstrap.py verify
```

该命令重新从 stage0 构建 stage1→stage2→stage3，再执行逐代回归，不复用此前保存的成功报告。Windows 使用真实 Git Bash 登录、读取原启动文件，并清除 `PYTHONUTF8`／`PYTHONIOENCODING` 后调用 Windows Python；WSL 使用其自身的 Linux Python 和 LLVM。两平台源码编译器 SHA-256 均为 `02d276dc6e1eee732a8141fdc458226e96aab9ffcaa9a222dd7aaf4520076d73`。

| 要求 | WSL / Linux | Windows host |
| --- | --- | --- |
| 真实三代本机编译 | ELF，Clang/LLVM 14.0.0 | PE x64，Clang/LLVM 14.0.6，MSVC ABI |
| 同份源码的自身前端 IR／ABI 描述 | stage2／stage3 逐字节相同 | stage2／stage3 逐字节相同 |
| stage1 同套回归 | 33 通过、无跳过 | 33 通过、无跳过 |
| stage2 同套回归 | 33 通过、无跳过 | 33 通过、无跳过 |
| stage3 同套回归 | 33 通过、无跳过 | 33 通过、无跳过 |
| 二进制固定点 | 原始文件逐字节相同 | 仅归一 PE 时间戳后逐字节相同 |
| 输入及产物在验收中未改变 | 通过 | 通过 |
| 结构化结果 | `m4_complete: true`，8 项门限全部通过 | `m4_complete: true`，8 项门限全部通过 |

两平台的 51 份构建／验收输入内容相同，33 个用例名称集合也完全相同。每平台共 **99 项通过，0 失败、0 错误、0 跳过**。完整逐项状态、源码／产物校验值和门限结果见 [Linux 原始报告](bootstrap-m4-2026-10-21/linux-verification.json)、[Windows 原始报告](bootstrap-m4-2026-10-21/windows-verification.json)。当前保留的可执行编译器位于 `bin/bootstrap/linux/` 和 `bin/bootstrap/win32/`，机器相关文件均不提交。

## 同套回归与独立性

三代共用 `tests/test_bootstrap.py` 的同一组 33 个方法，不为某代删减用例；它们包括：

- binary64 舍入／溢出／下溢、Unicode、事实与容器、函数与过程、递归及闭包、具名实参求值次序、继承与覆写、显式作用域、循环／破／完、卒恢复、接收者及赋值的求值次序。
- 普通相对外言、导入方相对路径、词法路径别名、菱形依赖和转导出、惰性初始化与失败缓存、所属模块作用域、不可达导入的错误、循环依赖及来源诊断。
- Unicode 文件读写／追加／删除、失败成果和无效 UTF-8、标准输入、非可恢复运行错误及副作用、GC 压力下的 `live=0`。
- 既有 `tests/test_practical.py` 的 15 组独立预期输出，原样保存到 `bootstrap/validation/practical.json`：文本、定点与数学边界、容器身份与别名、对象协议、循环、回调卒、PCG 固定序列及随机状态等。
- 源／依赖输出别名、源码错误和工具失败保留旧产物；删除源码后运行、独立 IR 复编；只复制原生前端和独立测试源到空目录、PATH 为空时生成 IR，再由真实 assembler 验证。

每代的普通构建测试均把 Python parser、模块加载器、C 和 LLVM 前端生成入口替换为抛错函数，原生构建仍成功；空目录测试也对每代单独执行。编译器的 AST 遍历在编译时生成 LLVM 函数正文，程序运行不依赖源码解释器。Python 宿主仅负责固定运行时、LLVM 调用和产物发布。

首次扩展测试发现一个新用例误把显式块内绑定当成外部模块变量更新，三代均返回规范要求的块内结果。测试改用共享阵保存计数后通过；未修改语言语义或编译器源码。正式报告来自修订后的完整 99 项重跑，首轮失败日志保留在本地。

## 二进制比较与验收器保护

`tools/bootstrap_compare.py` 对 ELF 不做归一；对 PE 只识别并记录 `IMAGE_FILE_HEADER.TimeDateStamp` 与各 `IMAGE_DEBUG_DIRECTORY.TimeDateStamp` 的偏移、原值，在内存中将四字节字段归零后比较。机器码、数据、校验和、GUID 和其他元数据均不掩盖，原始二进制不修改。字段定义见 [Microsoft PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)。

本次 Windows stage2／stage3 仅有上述时间戳不同；归一后 SHA-256 均为 `fe6228eeed63d87a750adc876d58dc33950ea8ce488fd3cf49477fcc8e2455bd`。Linux 原始二进制 SHA-256 均为 `3351eb1a1046116e2b7c492d3666b19e4d3c89d797b7d0fc77d97c1ec2c601ad`。不要求不同平台二进制相同，默认 Windows 链接仍记录时间。

验收器另外有 7 项负向控制，在 Windows 和 WSL 均通过：仅时间戳变化允许归一；机器码／其他元数据变化、坏 PE、空集合、漏跑／重复／不同代用例不同，以及失败、错误、跳过或未完成，均拒绝通过。新验收一开始即写入 `m4_complete: false`，运行失败不能继续沿用旧成功报告。

## 完整回归与交付边界

正式验收对应的完整仓库回归：

| 宿主 | 运行 | 通过 | 显式跳过 | 失败／错误 |
| --- | ---: | ---: | ---: | ---: |
| WSL，三个不重叠分片 | 1846 | 1799 | 47 | 0／0 |
| Windows host，完整发现 | 1804 | 1612 | 192 | 0／0 |

Linux 分片为 616／615／615 项，完整集合 SHA-256 为 `4a02a5a6c41c011bc580282367afd4a587dd35fe3cdbe48fbf1a536069f8fe31`。全量的跳过来自平台／工具前置条件；其中 Windows 旧 C 测试仍可能因 PATH 无全局编译器而跳过，LLVM ASan 缺少运行库。M4 的 99 项专项在两平台均无跳过，不将这些旧测试的跳过当作对应原生能力验收。

运行前后冻结的 **325 份源码、夹具与 CI 文件校验值全部一致**，两平台专项报告所用 51 份输入也与当前文件及该集合吻合。完整计数、耗时、日志校验值、验收器负向控制见 [测试摘要](bootstrap-m4-2026-10-21/test-summary.json)，文件集合见 [源码校验值](bootstrap-m4-2026-10-21/source-checksums.json)。未修改原 M3 全量、示例和基准历史数据。

CI 已接入 `verify`，并包含带冲突 MSYS 搜索变量的 Windows Git Bash 三代验收；验收时尚未在远端触发，不宣称远端 CI 已通过。原始数据与 M3 历史快照分别保存；上述验收完成时，新增实现尚未提交或推送。

M4 在此验收自举固定点和各代在已声明语言范围内的一致性。具名模块／完整包锁与远端包解析、全部路径身份与边界诊断、如书 AOT／如观、独立如言构建驱动及 Dart 性能对齐仍属于后续工作，不能由本报告推定完成。
