# 如言编译器自编译与固定点验收

`bootstrap/compiler.ru` 以如言实现词法、递归下降／Pratt 解析、语义准备、依赖读取、直接 LLVM IR 发射和运行时描述符生成。它使用现有动态值／GC 运行时的私有 ABI v1，如程序正文直接生成 LLVM；生成的少量 C 只承载描述符、模块缓存与聚合调用桥。

这是独立的实验编译前端。常规 `ru build` 仍使用完整的 Python 前端；首次自编译范围与完整语言工具链的替换分开验收。LLVM 仍需外部工具，构建驱动 `tools/bootstrap.py` 仍用 Python 准备固定运行时、调用原生如言编译器和 LLVM、检查路径并发布产物。后续代的驱动不调用 Python 的如词法／语法分析器、模块加载器或代码生成器。

## 准备与运行

WSL/Linux x86-64 安装 `clang-14 llvm-14`。Windows x64 需要 Visual Studio C++ Build Tools／Windows SDK，并可显式下载项目本地 LLVM：

```powershell
python3 tools/prepare_workspace.py --with-llvm
python3 tools/bootstrap.py bootstrap
python3 tools/bootstrap.py build examples/factorial.ru -o bin/factorial-self.exe --emit-llvm dist/factorial-self.ll
./bin/factorial-self.exe
```

WSL/Linux 对应命令：

```sh
python3 tools/bootstrap.py bootstrap
python3 tools/bootstrap.py build examples/factorial.ru -o bin/factorial-self --emit-llvm dist/factorial-self.ll
./bin/factorial-self
```

预备脚本默认不下载，加 `--with-llvm` 才取工具；本地工具及缓存位于忽略的 `.build_tools`，不改全局 PATH。安装、校验和平台边界见 [LLVM 指南](llvm-aot.md)。Windows 原生构建生成 PE，WSL/Linux 生成 ELF；分别在各自宿主执行。

Windows Git Bash 也可运行上述 Windows 命令，使用 Windows Python，默认产物仍放在 `bin/bootstrap/win32/`。若 shell 启动文件为 GCC/MSYS 导出了以冒号分隔的 `INCLUDE`、`LIB` 或头文件搜索路径，驱动会在 LLVM 子进程中忽略这些不符合 Windows 格式的列表，让 Clang 查找本机 MSVC／Windows SDK；有效的 Windows 分号列表和 VS 开发环境设置继续保留。预备检查使用相同规则，不修改 shell 配置或父进程环境。

自编译过程使用同一份源码：

```text
Python 引导前端（stage0） → stage1 原生如言编译器
stage1 读取 compiler.ru  → LLVM / 描述符 → stage2
stage2 读取 compiler.ru  → LLVM / 描述符 → stage3
```

默认保存到 `bin/bootstrap/linux/` 或 `bin/bootstrap/win32/`。`report.json` 记录源码、前端 IR、描述符和二进制 SHA-256，以及前端进程／构建耗时。只有 stage1→stage2 与 stage2→stage3 的前端 IR、描述符逐字节一致，才报告固定点；源码在过程中改变会令验收失败。工具输出和二进制一致性另记录，不推定跨平台二进制相同。

`stage2.frontend.ll`／`stage3.frontend.ll` 是原生如言前端发射的正文 IR；对应 `.metadata.c` 是其描述符。`stage2.ll`／`stage3.ll` 链接了运行时，可用同平台 LLVM 14 独立复编。`build` 默认用该宿主的 stage3，也可显式传 `--compiler PATH`；全局 `--llvm-clang COMMAND` 放在子命令之前。

## M4 完整验收命令

```sh
python3 tools/bootstrap.py verify
```

`verify` 从 Python 引导开始重新构建三代，因此不需要先运行 `bootstrap`。它要求 stage2／stage3 的自身前端 IR 和 ABI 描述精确相同，并让 **stage1、stage2、stage3 各自运行相同的 35 项回归**；任何失败、错误、跳过、漏跑或用例集合不同均不能通过。覆盖核心语义、15 组标准库预期输出、模块与错误来源、受检查 I/O、GC、独立运行和源码／产物保护，并增加 `另若` 惰性条件／作用域／控制流及等价嵌套预算回归。后续源码处理禁用 Python 前端入口，原生前端还须在只有自身程序和独立输入、PATH 为空的目录中工作。历史 M4 的 33 项／代报告保持原样。

验收同时比较 stage2／stage3 的本机二进制：Linux ELF 必须逐字节相同；Windows PE 只将文件头和调试目录中的 `TimeDateStamp` 四字节字段归零后比较，不掩盖机器码、其他数据或元数据。报告列出每个被归一字段的偏移与原值；原始二进制不被改写，默认链接时间戳继续保留。PE 字段定义参见 [Microsoft PE 格式](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)。

结果保存到对应宿主目录的 `verification.json`，包含每代逐项状态、固定点门限、输入与产物 SHA-256。全部输入和产物必须在验收期间保持不变。启动新验收立即将该报告标为未完成，避免失败的新运行沿用旧的成功报告。`--directory DIR` 可指定独立目录。

M4 按下述已声明的原生前端范围验收，不代表具名模块／完整包工具链移植、M5 如书内核或 Dart 性能目标已经完成。Python 宿主驱动、固定 C 运行时与系统 LLVM 仍是构建依赖。

## 首轮语言范围

后续已同步上游 `另若`：完整保留字、一个 `然.` 收尾，降低为既有嵌套条件节点；旧 `另 若` 保持原嵌套层级，条件链与等价嵌套共享 128 层源码结构预算。表达式仍沿用原生前端原有的 100 层预算，两者不是同一个计数。编译器自身仍受原有原生调用深度限制，可能更早拒绝深层程序；源码预算不是可编译链长度的保证。

已经实现并以原生执行回归覆盖：有限 binary64／事实／空、Unicode 句、对／阵／典、函数与过程、具名／位置实参、匿名函数、共享闭包和递归、显式作用域、条件／循环／破、卒／救、顶层形及继承／方法、受检查 I/O、元初入口、字符串路径的静态外言及尽取。调用求值顺序、赋值先验证目标、帧根清理和模块惰性初始化／失败缓存沿用运行时合同。

边界需要继续保持明确：

- 名称和空白分类冻结为 Unicode **13.0.0**，由 WSL 引导环境的 Python 数据生成后写入如源码；运行时不调用 Python。`tools/generate_bootstrap_unicode.py` 可在对应 Unicode 版本的 Python 上原样重建。完整 Python 前端的 Unicode 数据仍随其 Python 版本变化。
- 如言前端支持常见相对 `.ru` 路径与如竞／文本／数学／随机标准外言；依赖按文本路径归一。具名模块导入、集录／集锁／远端包解析，以及符号链接、大小写等路径别名的完整身份合同尚未移植；跨模块类型身份和全部诊断也尚未完成一致性验收。对非字符串导入明确拒绝；完整功能继续使用 Python 前端。
- 词法／语法深度检查和编译器自身调用资源有限，尚未达到完整前端所有边界错误、恢复、书写规范与复杂模糊输入的兼容验收。首次自编译和核心差分通过不能替代完整语言一致性验证。
- 如观、如:密／DLL、如见、如书 AOT 会话、跨目标构建仍未支持。宿主程序不能把普通运行错误恢复为显式卒。

构建驱动检查源／依赖与输出别名，生成与 LLVM 失败不覆盖原有程序或独立 IR。程序与多个附加文件分别替换，不构成跨文件事务。原生前端的底层开发接口接收 `SOURCE PROGRAM.ll METADATA.c TRIPLE DATA_LAYOUT STDLIB [SOURCES.json]`；常规使用优先通过驱动，以获得宿主规范路径和最终产物保护。

## 验证

```sh
python3 -m unittest discover -s tests -p test_prepare_workspace.py -v
python3 -m unittest discover -s tests -p test_llvm.py -v
python3 -m unittest discover -s tests -p test_bootstrap_verifier.py -v
python3 -m unittest discover -s tests -p test_bootstrap.py -v
```

自编译回归实际生成三代机器码，三代各自运行同套 35 项检查（共 105 项），并验证核心语义、继承和方法闭包、作用域闭包、模块缓存、Unicode 路径／入口、二进制与独立 IR。测试明确禁用后续驱动调用 Python 前端；另只复制原生编译器与独立测试源到空目录，清空 PATH，在该目录发射 IR，并交给真实 assembler 验证。仅运行 unittest 不会持久保存完整验收报告；交付验收使用上面的 `verify`。

完整证据及平台结果见 [M4 逐代验收](bootstrap-m4-validation.md) 与 [M3 首次自编译历史记录](bootstrap-validation.md)。生成机器码和达到自身 IR 固定点不表示已经对齐 Dart AOT 性能；M1 的原始性能数据仍保留，未重新包装为本阶段的性能达标证据。
