# 命令行与独立程序

先按[安装与更新](stable-entry.md)准备工具链。以下命令在仓库根目录执行；Windows 可把 `python3` 换成 `py -3`。如书画布的入口见[如书说明](../rushu/README.md)，它与下面的 C／Node.js 程序目标不同。

本页对应 `main` 上的如 0.22.0，包含包依赖同步、Windows x64 C 原生后端、源码路径映射和句点书写检查。原生能力须显式启用，执行平台与实测范围见[版本说明](stable-entry.md)。

## 常用命令

```sh
python3 ru                         # 等同 repl
python3 ru repl                    # 交互模式
python3 ru run source.ru           # 解释执行
python3 ru check source.ru         # 默认 C 目标，检查结构和显式函数调用
python3 ru check --target python source.ru # 解析、校验源码与导入，不执行 DLL
python3 ru run --allow-native source.ru    # 仅 Windows x64 本地 Python，先审阅
python3 ru check --target c --allow-native source.ru # 0.21.0：静态原生签名检查
python3 ru build --allow-native source.ru -o app.exe # 0.21.0：须 Windows x64 C 工具链
python3 ru build source.ru -o app  # 普通 C 编译
python3 ru build source.ru -o app --emit-c app.c
python3 ru build source.ru -o app-full --emit-c app-full.c --full-runtime
python3 ru build source.ru -o app --cc clang
python3 ru build source.ru --target js -o app.js
python3 ru build source.ru --target js -o app-full.js --full-runtime
node app.js 参数一 参数二         # 传给元初；脚本路径不计入外参
python3 ru deps sync 项目目录      # 无锁初解，有锁只恢复精确选择
python3 ru deps sync --locked 项目目录 # 必须已有有效锁，不重选、不改锁
python3 ru deps sync --update 项目目录 # 显式重解分支/范围，可能更新版本
python3 ru generate intent.md      # 明确请求在线生成；先配置提供方和凭据
python3 ru generate intent.md --target js -o draft.js
python3 -m rulang --help           # 模块入口也可用
```

## 完整语句的书写检查

新代码统一在完整语句末尾写 `.` 或 `。`，包括命名算／作、形、若、循、试／救以及语句花括号块。匿名算／作、典和阵仍是表达式，只有外层语句需要句点；`形 名:`、`试:`、`救 原因:` 统一写出已有的可选冒号。

旧程序省略块末句点仍能解析运行。自 0.21.7 起，CLI `check`／`build` 在既有语法和编译检查通过后，将书写提示以 `文件:行:列: warning:` 格式写入标准错误；不改变成功退出码，也不混入程序输出或生成源码。需要把缺点作为失败时使用严格检查：

```sh
python3 ru check source.ru --strict-style
python3 ru check source.ru --target python --strict-style
python3 ru build source.ru -o app --strict-style
```

严格检查只针对缺少的语句结束句点，将同类提示标为 `error` 并返回退出码 `1`；失败时不写构建产物。它不把省略可选冒号当作错误，也不改变求值、作用域或类型规则。`run`、REPL、生成命令与如书执行本轮不新增书写提示；编译器 Python API 也不自动输出这些 CLI 诊断。

## 原生调用的单独授权

`如:密` 与随附三方库 `如见` 的运行平台目前仅为 Windows x64；0.20.0 提供本地 Python，0.21.0 增加不依赖 Python／libffi 的独立 C 程序。原生调用具有当前进程权限，错误 ABI 可崩溃或破坏内存，不是沙箱；先读[原生指南](native-library.md)。

`run` 默认不允许原生调用，`--allow-native` 只对文件执行生效且必须写在文件名前；放在文件后是程序外参。如书和 REPL 不能启用此能力。`check --target python` 只解析、校验源码与静态导入图，不执行模块顶层、不加载 DLL；默认 `check` 仍为 C。C 默认仍拒绝 `如:密`／`如见` 原生依赖，0.21.0 的 `check --target c --allow-native` 可显式检查静态签名，`build --allow-native` 可构建；这两个操作均不执行用户代码或加载 DLL。`check --target python` 不接受也不需要该开关。Node.js 与 browser-js 仍拒绝原生依赖，不能启用。检查通过不能证明原生 ABI 或资源生命周期安全。

C 原生后端只支持编译期能确定的有限机器标量／指针签名，无法确定的动态 ABI 会报编译错误；DLL 路径、导出名和实参值仍可在运行时决定。回调依赖须在首次原生调用前完成导入；不能在 C 原生回调内首次初始化新模块。完整边界见[静态签名子集](native-library.md#c-后端的静态签名子集0210)。

## 构建与输出保护

`build` 不会自动运行程序。默认 `--target c`，输出为去掉扩展名的源文件路径（Windows 加 `.exe`）；`--target js` 默认为同名 `.js`。两种目标都在完整编译成功后才原子替换既有输出，不能覆盖源文件或静态外言依赖。JavaScript 构建不调用 Node / C 编译器、不使用 `CC`，也不接受 `--cc` / `--emit-c`。

JavaScript 产物采用 CommonJS。在 `package.json` 含 `"type":"module"` 的目录树中，使用 `-o app.cjs` 并执行 `node app.cjs`；不要把输出作为 `.mjs`、ES module 或浏览器脚本加载。文件 I/O 路径相对运行时工作目录；打包的静态外言不需要源文件。Node 的最大递归深度、垃圾回收及资源限制与 Python / C 不相同；栈溢出报告运行错误。Node 在 Windows / macOS 上尚未实测。

C 目标的 `--emit-c` 会额外保存一个可独立编译的 C 文件；该路径也不得覆盖源文件、依赖或程序输出。它包含所需的运行时，不需要这个项目的头文件。普通 C 程序可用：

```sh
cc -std=c99 -O2 dist/my-hello.c -lm -o another-hello
```

包含原生依赖的 C 必须用真正面向 Windows x64 的编译器、头文件和系统库复编。编译宿主可以不同，产物运行平台仍为 Windows x64；Linux 本机 C 编译器不会因此得到原生执行能力。交叉编译时用 `--cc` 选择目标工具链并显式命名 `.exe`。产物运行不需要 Python／libffi，但仍需要 Windows 与被调用 DLL；没有自动运行或缺少平台时的隐式回退。

默认 C 输出保留生成代码所需的运行时函数及其传递依赖，也按整个模块图中出现的成员名称保留动态分派分支。 若依赖闭包中没有对／阵构造器，会省去不可达的容器遍历；没有用户形或受检查 I/O 时省去用户字段／方法查找；全模块图没有「卒」或「试」时省去异常传播状态。随附的 `如竞` 只在能安全证明时移除未引用声明；别名、函数引用、闭包和转导出都参与分析，模块值逃逸或无法确定时保守保留。用户源码和用户模块的函数、初始化副作用不会因此删除；裁剪前仍检查完整依赖图。

`build --full-runtime` 对 C / JavaScript 都有效：关闭随附标准库声明裁剪，C 保留完整动态运行时，JavaScript 保留完整 I/O / 竞赛 / 实用库运行时区段。它不会额外导入未使用的标准库，也不改变语言语义、错误检查或执行方式。两种输出都可用于排查差异，正常构建无需此选项。没有原生依赖的普通程序不会因 0.21.0 新能力而包含原生运行时／回调跳板，普通 OJ 用例的 64 KiB 预算仍单独检查。原生 GUI 输出可以更大。源码长度取决于程序所用功能；请按目标平台限制检查最终文件的字节数，而非假定所有程序都能通过同一源码长度上限。

仓库的可复现 C 体积回归使用固定入口及标准库源码标识（通过下述路径映射），只排除安装目录长度差异，仍计入全部运行时和诊断内容；这不保证任意安装路径下的最终产物大小。

## 错误与退出码

常规错误退出码为 `1`，命令行参数错误为 `2`，取消文件执行为 `130`。错误通常包含文件名、行号；前端和解释器还提供列号。原生运行错误只提供行号。

参数数量错误会注明调用名、期望与实收数量。多余位置实参的括号提示是条件性帮助：逗号也能分隔调用实参，`[表 其 查 '键', 值]` 会把两个实参交给 `查`；若本意是两个阵元素，应写 `[(表 其 查 '键'), 值]`。调用规则不因诊断而改变。

## 产物源码路径映射（0.21.2）

C 构建默认在产物中保存源码标识，用于运行错误、`卒` 和原生回调错误的位置。分发程序时，可显式映射构建机器的路径前缀：

```sh
python3 ru build source.ru -o app --source-prefix-map "$PWD=src" --emit-c app.c
python3 ru build source.ru -o app.exe --source-prefix-map "C:\build=src"
```

`--source-prefix-map OLD=NEW` 按首个 `=` 分隔，可重复；按完整路径分量匹配，最长前缀优先，同长使用最后一条，不把 `work` 误匹配为 `worker`。相对 `OLD` 按构建工作目录解析；宿主路径按模块解析方式规范化。完整 Windows 盘符／UNC 路径可跨宿主识别，按 `ntpath.normcase` 统一大小写及斜杠方向，不把 `ß` 扩展成 `ss`，不承诺完整卷级文件身份判断；POSIX 宿主路径区分大小写。新标识保留 `NEW` 的文字，剩余分量用 `/` 连接；空 `NEW` 删除前缀，完全匹配且结果为空时显示 `.`。空 `OLD`、NUL、换行及 Windows 盘符相对路径不接受。虚拟标识如 `<源码>` 保持不变。

它只适用于 `build --target c`，同时影响 `--emit-c` 与可执行产物；不是 `run`、`check`、JavaScript 或生成命令的选项。Python API 可向 `Compiler` 或 `build` 传入 `source_prefix_maps=["OLD=NEW", ...]`。导入查找、模块缓存身份、源码正文及编译期错误的原始路径／片段不变。

这不是通用脱敏器：未匹配的模块路径仍保留；用户字符串、DLL 路径和外部 C 编译器的调试信息不会被替换。工程目录和工具链／随附库目录可以分别映射，应审阅最终产物。此选项不创建 GUI 弹窗或日志出口。

## 从一个文件到独立程序

编译并运行独立程序：

```sh
python3 ru build examples/hello.ru -o bin/my-hello --emit-c dist/my-hello.c
./bin/my-hello

python3 ru build examples/add.ru -o bin/my-add
./bin/my-add
```

输出：`你好，世界`。加法示例会询问两个数并显示和。

编译为 JavaScript 并用 Node.js 运行：

```sh
python3 ru build examples/hello.ru --target js -o dist/hello.js
node dist/hello.js
```

构建 JavaScript 只需要 Python；执行产物才需要 Node.js。

`ru` 本身也是可执行脚本；可使用 `./ru repl`，或始终使用 `python3 ru`。

## REPL

变量、函数会跨提交保留。输入多行函数、条件、循环时，REPL 等待对应结束关键词；简单语句仍需句点。

```text
如> 算 平方 根 为 数:
… 得 根 * 根.
… 法
如> 平方 9.9.
98.01
如> 平方 根: 12.
144
```

单独的表达式在 REPL 会回显；文件模式丢弃表达式结果，应显式使用 `显`。`:reset` 清空变量 / 函数，`:help` 查看提示，`:退`、`:quit`、`:q`、`:exit` 退出。REPL 命令单独输入一行，不加句点；仅在没有待续源码时识别，字符串中的 `:退` 仍是普通文本。Ctrl-C 取消当前未结束的输入或执行。

提交发生运行错误时，会恢复提示符，但不会回滚之前已经执行的赋值或输入输出；这不是事务式 REPL。管道输入不显示提示符。`读` 使用同一个标准输入流，会消费下一行输入。

在线生成、凭据配置与保存保护另见[如是我言](generation.md)。用如解题并复制完整 C 提交，见[如竞指南](contest-library.md)。

[返回文档导航](index.md)

包依赖与目录命令：[包与具名模块](packages.md)、[目录本地原型](package-registry.md)、[工具影响清单](package-tooling.md)。
