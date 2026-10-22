# LLVM AOT 实验目标

`bs` 工作线的如 0.23.0 增加直接 LLVM AOT 编译。当前目标为 **Linux 和 Windows x86-64、LLVM 14**，使用该版本的有类型指针 IR；不混用其他主版本的 bitcode 或工具。M1 的验收快照只包含 Linux，随后补充 Windows 原生目标。

## 安装与运行

需要 Python 3.10+ 作为构建前端，以及 LLVM 14 的 clang、llvm-as、llvm-link、opt、llvm-dis、llc。Ubuntu 22.04 可安装：

```sh
sudo apt-get update
sudo apt-get install clang-14 llvm-14
python3 ru check examples/factorial.ru --target llvm
python3 ru build examples/factorial.ru --target llvm -o bin/factorial-llvm --emit-llvm dist/factorial.ll
./bin/factorial-llvm
```

Windows x64 可选择准备项目内工具。在 PowerShell 中，从仓库根运行：

```powershell
python3 tools/prepare_workspace.py             # 查看环境，不下载
python3 tools/prepare_workspace.py --with-llvm # 下载并检查项目本地 LLVM 14
python3 ru build examples/factorial.ru --target llvm -o bin/factorial-llvm.exe --emit-llvm dist/factorial-windows.ll
./bin/factorial-llvm.exe
```

预备工具取自 [conda-forge LLVM 工具包](https://anaconda.org/conda-forge/llvm-tools)，固定 LLVM 14.0.6；完整下载地址、大小、SHA-256 和许可证记录在 [包清单](../tools/llvm-windows-packages.json)。约 447 MiB 的压缩包缓存于 `.build_tools/downloads`，所需程序、DLL、Clang 资源和许可证保存至 `.build_tools/llvm-14`。该目录由 Git 忽略；重复运行复用经过校验的缓存和安装。脚本不修改全局 PATH 或注册表，构建不自动下载。

Windows 链接需要已安装的 Visual Studio C++ Build Tools 和 Windows SDK。预备脚本检查六个工具的版本，并真实经过 bitcode、验证、优化、目标文件、链接和执行；SDK 缺失时报告具体错误，保留已下载工具。当前 Windows 目标为 x86-64 MSVC ABI；不推定 MinGW 或 ARM 支持。

Git Bash 可以使用相同的 Windows Python 命令。若 `~/.bashrc` 为 MSYS/GCC 设置了冒号分隔的 `INCLUDE`／`LIB`（例如 `c:/msys64/usr/include/:c:/other/include/`），Clang 会把它当作 Windows 的分号列表，导致 `math.h file not found` 或链接找不到 CRT。LLVM 驱动与预备脚本只在子进程中忽略这类 POSIX 列表及 `/c/...`、`/usr/...` 等路径；保留有效 Windows 列表、VS 环境与 PATH。无需修改全局配置。路径规则参考 [Clang 环境变量说明](https://clang.llvm.org/docs/CommandGuide/clang.html#environment) 和 [LLVM 14 MSVC 工具链实现](https://github.com/llvm/llvm-project/blob/llvmorg-14.0.6/clang/lib/Driver/ToolChains/MSVC.cpp)。

也可以从 PowerShell 调用 Ubuntu WSL，使用其独立的 Linux Python、Clang/LLVM 14，生成 Linux 产物。将 `/mnt/c/path/to/ru-language` 换成实际 WSL 路径，其他发行版也需替换 `Ubuntu`：

```powershell
wsl -d Ubuntu --cd /mnt/c/path/to/ru-language python3 ru build examples/factorial.ru --target llvm -o bin/factorial-llvm --emit-llvm dist/factorial.ll
wsl -d Ubuntu --cd /mnt/c/path/to/ru-language ./bin/factorial-llvm
```

Windows 原生构建生成 PE `.exe`；WSL/Linux 构建生成 ELF，两者分别在对应环境运行。不支持的宿主在查找 Clang 前报告平台限制。

`check --target llvm` 检查整个静态依赖图并生成 IR，不执行用户顶层、调用外部 LLVM 工具或检查本机工具安装。构建先做源码/风格检查，接着检查工具版本和目标平台；不执行生成程序，不获取依赖。

Clang 选择顺序为 `--llvm-clang COMMAND`、`RU_LLVM_CLANG`、Windows 项目内 `.build_tools/llvm-14/bin/clang.exe`、PATH 中的 clang-14/clang。同目录下优先寻找匹配工具，其次找 PATH 中带 `-14` 的工具；每个工具都检查主版本。`CC` 继续属于 C 后端，不影响 LLVM。C 后端在 PATH 没有编译器时也可复用 Windows 本地 LLVM。路径中的空格和中文按 argv 传递，不经过 shell。

```sh
python3 ru build examples/hello.ru --target llvm --llvm-clang /usr/lib/llvm-14/bin/clang -o bin/hello-llvm
```

## 编译路径与私有 ABI

```text
如源码及静态依赖 → 共享解析/语义准备 → 直接 LLVM IR → llvm-as
动态值 C 运行时与 ABI 桥接 → clang-14 → runtime bitcode
两者 → llvm-link → opt 验证 → 优化 → 再次验证 → llc 目标文件 → clang-14 链接 → 原生程序
```

如程序的表达式、函数正文、分支、短路和循环由 `llvm_compiler.py` 直接发射 LLVM 指令；不调用 C 后端的程序代码生成。`Compiler` 构造阶段的导出/类型/继承/调用准备仍被复用，尚未抽成独立语义 IR。

只有一份运行时翻译单元维护 GC、环境、模块缓存和卒状态。LLVM 使用私有 ABI v1：指针、i32、i64 和 double；C 的 Val/Env 布局及聚合传参/返回留在 C 内部。每个如函数有小型 C 调用桥，适配现有 RuCode 签名；描述符与模块初始化状态也是 C 数据/桥接，不承载如程序正文。

临时值位于已初始化的帧槽中，每个值遵守现有根所有权。正常语句、卒传播和函数退出清理根；返回值先复制到调用者槽。闭包保留可达环境，阵/典/对象的循环由追踪 GC 回收。当前帧清理和动态值表示以正确性为先，优化空间需通过测量确定。构建使用目标 Clang 探测到的 triple/data layout，不在 LLVM 中猜测 C 结构布局；不启用 fast-math。

## 能力与边界

首版直接降低现有核心 AST：有限 binary64、事实/空、Unicode 句、对/阵/典、算/作、词法闭包、命名参数、控制流、作用域、对象/继承、显式卒/救、静态外言及包。受检查文件/标准流、如竞、文本/数学/随机沿用现有运行时。未知 AST 节点在编译期按位置拒绝，包含不可达分支；实际测试覆盖见 [验证记录](llvm-aot-validation.md)，不从节点支持推定所有程序均正确。

| 项目 | 当前状态 |
| --- | --- |
| Linux x86-64 + LLVM 14 本机原生程序 | 支持并实测 |
| Windows x86-64 + LLVM 14、MSVC ABI 本机程序 | 支持；项目本地工具预备及真实 PE 构建、运行已核验 |
| Python/C/JS 的既有源码语义 | 共享语义准备与运行时，增加直接 LLVM 差分回归 |
| 独立 `.ll` 与独立可执行程序 | 支持；测试移除源码、换工作目录、清空 PATH 后执行并复编 IR |
| macOS/ARM、MinGW、跨目标构建 | 尚未支持/验收，构建明确拒绝 |
| 如:密、如见、DLL 回调 | 默认拒绝原生导入；Windows 显式密清单 + --allow-native 可用[实验 owner 桥](mi-llvm.md)，完整 DLL／如见／回调未验收 |
| 如观、如书 AOT 持久会话 | 不支持；现有 Python/browser-js 代码格继续使用原执行方式 |
| 首次自编译 | 独立如言前端与三代构建见 [自编译指南](bootstrap.md)；常规 build 前端仍是 Python |
| Dart AOT 性能对齐 | 长期验收目标；本阶段只建立原始测量基线 |

`--cc`、`--emit-c`、`--source-prefix-map` 不适用于 LLVM；`--allow-native` 仅在显式 `--experimental-mi-manifest` 实验入口可用。`--full-runtime` 保留完整随附声明和运行时公共适配入口供对照；仍进行合法的 LLVM 优化，不改变语义。函数调用深度、文件访问权限等继续沿用现有运行时边界。

## 保留与复编独立 IR

`--emit-llvm` 保存的是链接运行时、验证并优化后的单一 `.ll`。运行原生程序不需要这个文件；复编它也不需要 Python、如源码、头文件或项目目录：

```sh
clang-14 dist/factorial.ll -O2 -o bin/factorial-rebuilt -lm
./bin/factorial-rebuilt
```

Windows 使用本地 Clang 复编对应的 Windows IR；CRT 提供数学函数，不添加 `-lm`：

```powershell
./.build_tools/llvm-14/bin/clang.exe dist/factorial-windows.ll -O2 -o bin/factorial-rebuilt.exe
./bin/factorial-rebuilt.exe
```

二进制仍依赖目标系统的加载器、C/数学运行库，不承诺完全静态链接。IR 包含源码标识与用户字符串，不承诺去除路径信息或隐藏源码常量。

输出路径不得覆盖源文件、外言依赖或彼此。源码、严格书写、工具与 IR 验证失败时不替换旧二进制或旧 IR。每个文件以同文件系统临时文件原子替换；两个不同输出文件的发布不构成单个事务，中途文件系统错误可能只发布其中一个。

## 验证与性能对照

```sh
python3 -m unittest discover -s tests -p test_llvm.py -v
python3 tools/benchmark_aot.py --dart /path/to/dart --iterations 1000000 --repeats 7 --output dist/aot.json
```

测试覆盖直接生成（禁止调用 C 程序生成器）、真实 IR/链接执行、闭包/GC/求值顺序/错误路径、输入/入口/模块、源码与产物路径保护，以及工具故障不覆盖旧产物。LLVM 执行测试需要完整 LLVM 14 和对应的 Linux/Windows x86-64 宿主；缺失时明确跳过。专项 CI 安装匹配版本后运行，不能把跳过当作通过。

性能工具对数值循环、闭包调用、数组分配运行等价的如 C、如 LLVM、Dart 原生 AOT 程序。用相同规模和输入，先与独立校验值核对输出，预热并交错重复执行，记录每次时间/RSS、编译耗时、产物体积/校验值和工具版本。Dart SDK 仅用于对照，不成为如产物的依赖。

当前时间指标是**整个进程的墙钟时间**，包含创建进程、运行时启动、计算和输出；n=1 仅表示启动占比较大的工作负载，不是独立测得的初始化耗时。大规模结果也不能直接等同于纯计算吞吐。首批微基准不覆盖编译器、完整应用、图形、全部 GC 模式或其他平台；需扩大工作负载后评估长期性能目标。原始样本和限制见 [本批验证报告](llvm-aot-validation.md)。

LLVM 版本边界参考 [LLVM opaque pointer 文档](https://llvm.org/docs/OpaquePointers.html#version-support)；IR 语法参考 [LLVM 14 LangRef](https://releases.llvm.org/14.0.0/docs/LangRef.html)。Dart 对照使用官方 [dart compile exe](https://dart.dev/tools/dart-compile#exe) 的原生产物。
