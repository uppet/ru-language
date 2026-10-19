# 开发、构建与验证

本页面向准备阅读实现、修改语言或验证工具链的人。普通使用先看[入门小路](first-steps.md)；安装要求与平台范围见[安装与更新](stable-entry.md)，构建具体程序见[命令行指南](command-line.md)。

## 实现方式与边界

**本版不是自举编译器。** 编译器和 REPL 使用 Python；原生输出经过 C 编译器编译，执行时不需要 Python、`ru`、原始 `.ru` 文件或生成的 `.c` 文件。JavaScript 输出只需要 Node.js 内置标准库，不需要 Python、项目文件、原 `.ru` 文件或 npm 包。两种生成程序都没有如词法分析器、语法分析器或源码 / AST 解释器。

## 项目结构

```text
ru / ru.cmd               命令行入口
rulang/frontend.py        Unicode 词法分析、AST、Pratt 表达式解析、结构检查
rulang/interpreter.py     REPL / run 的参考解释器
rulang/compiler.py        AST → C99 直接代码生成
rulang/js_compiler.py     AST → JavaScript 直接代码生成，共用语义准备
rulang/runtime.js        内联的 Node.js 动态值、闭包、对象、I/O 与竞赛运行时
rulang/runtime.h          动态值、集合 / 对象 / 模块、内存管理、作用域、panic
rulang/io_runtime.py       解释器的受检查文件、目录与标准流
rulang/io_runtime.h        内联到独立 C 输出的受检查 I/O
rulang/stdlib/如竞.ru      普通如函数组成的如竞标准外言
rulang/stdlib/密.ru         如:密标准库入口（普通如源码）
rulang/native_runtime.py    Windows x64 Python 原生能力与受管理值
rulang/native_c.py          C 原生有限签名分析与有类型调用／回调跳板
rulang/native_c_runtime.py  仅原生程序启用的 C 运行时整合
rulang/native_runtime.h    C 原生值、内存、调用与回调错误边界
rulang/native_types.h      C 原生值与资源表示
rulang/native_platform_win64.h Windows x64 系统适配边界
rulang/thirdparty/如见/     独立随附三方 Win32 库，不属于语言标准
docs/native-library.md      如:密接口、生命周期、权限与目标边界
rulang/contest_runtime.py  解释器的读写游标、拆分及稳定排序桥接
rulang/contest_runtime.h   内联到独立 C 输出的竞赛原语
rulang/generation.py       Responses 协议、配置与安全生成输出
rulang/language-spec.md    唯一权威语言规范；每次生成读取并发送实际全文
rulang/cli.py              CLI、REPL、编译器调用、意图入口
rulang/modules.py          本地相对路径加载、规范化缓存与循环检测
examples/                 基础、算法、对象、入口、模块示例和意图文档
docs/contest-library.md    四道原创题目、输入输出样例、解法及复制 C 提交指南
tests/test_ru.py           0.1 兼容性与 CLI 回归测试
tests/test_extensions.py   0.2 双后端数据结构、对象、模块、入口回归
tests/test_modules_cli.py  模块加载、错误来源与 CLI 安全检查
tests/test_closures.py     词法闭包、函数值、捕获状态与双后端回归
tests/test_contest.py      竞赛导入、读写、排序、错误与独立 C 回归
tests/test_io.py           临时文件与标准流双后端测试
tests/test_panic.py        panic / rescue、控制流与回收测试
tests/test_generation.py   本地模拟 Responses 与配置 / 输出保护
tests/test_javascript.py   JavaScript 语义 / 运行时与独立产物回归
tests/test_js_cli.py       JavaScript CLI、生成目标与安全输出回归
.github/workflows/ci.yml   Linux 上多版本 Python 回归测试与示例构建
bin/                      本机构建的样例程序（不纳入 Git）
dist/hello.c               构建生成的独立 Hello World C 输出（不纳入 Git）
dist/factorial.c           构建生成的独立递归阶乘 C 输出（不纳入 Git）
dist/square.c              构建生成的独立 9.9 平方 C 输出（不纳入 Git）
CHANGELOG.md               版本变化与调用语法兼容说明
VALIDATION.md              各次实际验证记录
```

0.21.0 的 C 原生支持只在显式启用且依赖图使用如:密时加入；普通 C／OJ 程序继续走原有裁剪路径。原生 ABI 由有限静态签名生成有类型 C 跳板，不引入 Python、libffi 或运行时机器码生成。平台适配层当前仅实现 Windows x64；如见的 Win32 名称和消息循环留在三方库，后续跨平台驱动不能依赖“所有平台都等于 Win32”的假设。接口与限制见[原生指南](native-library.md)。

两个编译后端把表达式和控制流直接翻译成 C 或 JavaScript 语句 / 函数；每个值的类型仍在运行时表示和检查，这是动态值模型，不是静态类型推断。集合、对象和模块使用统一的运行时值表示，赋值 / 调用 / 返回保留引用语义。

JavaScript 后端会保守扫描完整已解析的模块依赖图 AST：只有整图未引用相应内置名称 / 类型时，才省略受检查 I/O 或竞赛辅助运行时区段。经别名访问或外言依赖所需的区段仍保留，包括尚未执行的分支与函数。这是通用运行时裁剪，不做压缩混淆或针对某道题重写源码。

目前没有箭头函数、通用用户代码优化器或自举。包依赖支持显式 Git／HTTPS 目录获取及本地静态目录原型，没有默认公共包目录、账号或网络发布服务；见[包指南](packages.md)。`check` 不是完整静态类型分析：例如未绑定变量、数值转换、实际参数类型仍可能在运行时报错。编译过程检查整个程序，因此即使某个分支不执行，其中无效的显式函数调用也会阻止编译。

Python 解释器由 Python 的追踪式 GC 管理引用图；C 运行时使用根引用与追踪回收，能回收阵／对象之间的不可达循环。可用 `RU_GC_THRESHOLD=1 RU_GC_STATS=1 ./bin/objects` 压测频繁回收并查看退出统计；统计不是完整内存安全审计。

## 运行验证

```sh
make test          # Python、C、JavaScript 与 CLI 回归
make test-emacs    # Emacs 字节编译与 ERT，需已安装 Emacs
make test-notebook # 如书 Python 和 Node 前端测试
make examples      # 构建 C 示例
make examples-js   # 构建并由 Node 检查 JavaScript 示例语法
```

完整 Python 命令也可直接运行：

```sh
python3 -m unittest discover -s tests -v
```

测试命令和实际通过记录分开看。定向测试、模拟服务、平台跳过和真实浏览器检查不能互相代替；各批实测见 [VALIDATION.md](../VALIDATION.md) 及[分项报告](index.md#实现与验证)。CI 的实际矩阵以 [ci.yml](../.github/workflows/ci.yml) 为准，不能从配置推定某个提交已经通过。0.21.0 的真实 DLL／Windows x64 ABI／回调与如见窗口须在 Windows 上单独验证；便携 C 夹具、静态签名检查及平台跳过都不能替代。

回归覆盖语言求值、持久会话、模块、输入输出、错误位置、闭包和回收；独立产物另检查不依赖原源码的运行。生成服务测试使用本地协议模拟，不代表真实提供方、账号或模型兼容性已验证。

独立运行不表示安全沙箱：普通 CLI 程序没有时间／内存配额，无限循环和大字符串可能占用资源。如书与 browser-js 的保护范围另见各自指南。不要未经审阅就运行陌生源码。

Git 忽略构建产物、Python 缓存、虚拟环境、编辑器备份和本地凭据。原交付包的 `SHA256SUMS.txt` 是打包产物，不纳入源码仓库；修改源码后应在制作新交付包时重新生成。

## 变更语言时的同步清单

语法、类型、求值、标准库或错误行为有变化时，同一变更需要一起检查：

1. 前端、参考解释器、独立 C99 和 JavaScript 后端的实现保持一致
2. 更新 `rulang/language-spec.md` 的当前实现契约、版本和例子；尚未实现的设计明确留在未来边界，不写成可用功能
3. 同步 `ru-lang-mode` 的关键词 / 名称高亮、缩进、块与定义导航，以及 ERT 回归
4. 补充 Python / 原生 / JavaScript 语义、错误路径、生成规范注入与必要的 GC / I/O 回归，更新教程、示例和变化记录
5. 运行 `make test`、`make test-emacs`、`make examples`、`make examples-js`；检查生成请求确实携带当前完整规范，再核对本次提交的 CI

规范与生成器版本一致性、实际全文注入由测试检查；语义和编辑器同步仍需审阅，不能仅凭版本号或测试数量宣称规范正确。发布当前源码目录时应保留包内的 `language-spec.md`、`stdlib/` 内的全部 `.ru`、`runtime.js` 及运行时头文件；将来新增 wheel / 其他打包方式时，也必须把该资源纳入发行物并验证安装后的读取。

[返回文档导航](index.md)
