# 命令行与独立程序

先按[安装与更新](stable-entry.md)准备工具链。以下命令在仓库根目录执行；Windows 可把 `python3` 换成 `py -3`。如书画布的入口见[如书说明](../rushu/README.md)，它与下面的 C／Node.js 程序目标不同。

本页对应 `main` 上的如 0.20.0。`--allow-native` 和 `check --target python` 已随本版提供；原生执行仍仅限 Windows x64 本地 Python，C 原生库后端尚未提供。具体组合见[版本说明](stable-entry.md)。

## 常用命令

```sh
python3 ru                         # 等同 repl
python3 ru repl                    # 交互模式
python3 ru run source.ru           # 解释执行
python3 ru check source.ru         # 默认 C 目标，检查结构和显式函数调用
python3 ru check --target python source.ru # 解析、校验源码与导入，不执行 DLL
python3 ru run --allow-native source.ru    # 仅 Windows x64 本地 Python，先审阅
python3 ru build source.ru -o app  # 原生编译
python3 ru build source.ru -o app --emit-c app.c
python3 ru build source.ru -o app-full --emit-c app-full.c --full-runtime
python3 ru build source.ru -o app --cc clang
python3 ru build source.ru --target js -o app.js
python3 ru build source.ru --target js -o app-full.js --full-runtime
node app.js 参数一 参数二         # 传给元初；脚本路径不计入外参
python3 ru generate intent.md      # 明确请求在线生成；先配置提供方和凭据
python3 ru generate intent.md --target js -o draft.js
python3 -m rulang --help           # 模块入口也可用
```

## 原生调用的单独授权

`如:密` 与随附三方库 `如见` 首版只支持 Windows x64 本地 Python。原生调用具有当前进程权限，错误 ABI 可崩溃或破坏内存，不是沙箱；先读[原生指南](native-library.md)。

`run` 默认不允许原生调用，`--allow-native` 只对文件执行生效且必须写在文件名前；放在文件后是程序外参。如书和 REPL 不能启用此能力。`check --target python` 只解析、校验源码与静态导入图，不执行模块顶层、不加载 DLL；默认 `check` 仍为 C。C、Node.js 和 browser-js 会拒绝 `如:密`／`如见` 原生依赖。检查通过不能证明原生 ABI 或资源生命周期安全。

## 构建与输出保护

`build` 不会自动运行程序。默认 `--target c`，输出为去掉扩展名的源文件路径（Windows 加 `.exe`）；`--target js` 默认为同名 `.js`。两种目标都在完整编译成功后才原子替换既有输出，不能覆盖源文件或静态外言依赖。JavaScript 构建不调用 Node / C 编译器、不使用 `CC`，也不接受 `--cc` / `--emit-c`。

JavaScript 产物采用 CommonJS。在 `package.json` 含 `"type":"module"` 的目录树中，使用 `-o app.cjs` 并执行 `node app.cjs`；不要把输出作为 `.mjs`、ES module 或浏览器脚本加载。文件 I/O 路径相对运行时工作目录；打包的静态外言不需要源文件。Node 的最大递归深度、垃圾回收及资源限制与 Python / C 不相同；栈溢出报告运行错误。Node 在 Windows / macOS 上尚未实测。

C 目标的 `--emit-c` 会额外保存一个可独立编译的 C 文件；该路径也不得覆盖源文件、依赖或程序输出。运行它不需要这个项目的头文件：

```sh
cc -std=c99 -O2 dist/my-hello.c -lm -o another-hello
```

默认 C 输出保留生成代码所需的运行时函数及其传递依赖，也按整个模块图中出现的成员名称保留动态分派分支。 若依赖闭包中没有对／阵构造器，会省去不可达的容器遍历；没有用户形或受检查 I/O 时省去用户字段／方法查找；全模块图没有「卒」或「试」时省去异常传播状态。随附的 `如竞` 只在能安全证明时移除未引用声明；别名、函数引用、闭包和转导出都参与分析，模块值逃逸或无法确定时保守保留。用户源码和用户模块的函数、初始化副作用不会因此删除；裁剪前仍检查完整依赖图。

`build --full-runtime` 对 C / JavaScript 都有效：关闭随附标准库声明裁剪，C 保留完整动态运行时，JavaScript 保留完整 I/O / 竞赛 / 实用库运行时区段。它不会额外导入未使用的标准库，也不改变语言语义、错误检查或执行方式。两种输出都可用于排查差异，正常构建无需此选项。源码长度取决于程序所用功能；请按目标平台限制检查最终文件的字节数，而非假定所有程序都能通过同一源码长度上限。

## 错误与退出码

常规错误退出码为 `1`，命令行参数错误为 `2`，取消文件执行为 `130`。错误通常包含文件名、行号；前端和解释器还提供列号。原生运行错误只提供行号。

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
