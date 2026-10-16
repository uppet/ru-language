# 稳定版入口、更新与执行目标

## 取得同一套工具链

当前稳定组合为 **如 0.18.1、语言规范 0.18.1、如书 0.7.0**，均来自语言仓库的 `main`。本工作树为 **如 0.20.0、语言规范 0.20.0、如书 0.8.8**，属于 `wip` 开发版本，尚未发布到 `main`；本文的安装与更新命令不会承诺取得该开发版本。`wip` 用于后续开发，可能先于稳定版变化；学习与普通使用从 `main` 开始。`main` 是经过验证的稳定使用入口，语言本身仍处于原型阶段，不表示永久冻结语法。

需要已安装 Python 3.10+ 和 Git。仓库现已公开，可直接获取源码。全新安装：

```sh
git clone --branch main https://github.com/uppet/ru-language.git
cd ru-language
python3 ru --version
python3 -c "import rushu; print(rushu.__version__)"
python3 -m rushu
```

Windows 可把 `python3` 换成 `py -3`。打开终端打印的完整本机地址，保留其中的启动令牌。如书启动、离线编辑及 Python／浏览器 JS 执行均不需要 npm；只有 CLI JavaScript 产物执行需要 Node.js 18+。

独立的[如言 VS Code 扩展](https://github.com/uppet/ru-vscode) **0.7.0** 已支持 0.18.0 的语言接口，也适用于 0.18.1；本次补丁没有新增语法或编辑器接口，不要求重装扩展。扩展与语言仓库分别发布，扩展不内置解释器。其“运行当前文件”走普通 CLI，不是如书画布入口。把扩展的 `ru.cliPath` 指向本机语言仓库的 `ru` 文件，解释器路径指向已安装的 Python；普通文本编辑加终端命令同样可用。

启动后继续[入门小路](first-steps.md)。只想运行 `.ru` 文件时，可用 `python3 ru run examples/hello.ru`；交互输入用 `python3 ru repl`。

开发版 0.20.0 的全量导入统一为 `尽取 外言`，旧 `尽 取` 会报迁移错误；稳定版 0.18.1 仍使用当时语法。请按所用工具链版本阅读[迁移说明](import-all-migration.md)，不要把开发版代码直接套用到稳定版。

## 已有仓库安全更新

先在如书中点击“保存”，把自己的 `.rushu.json` 下载到安全位置，再关闭本机服务。网页没有自动保存；Git 更新不能保存尚未下载的书本。

在仓库根目录先查看：

```sh
git status --short
git branch --show-current
git fetch origin
```

如果有本地修改、未跟踪的源码／书本，或当前分支有自己的提交，先备份并处理自己的工作；不确定时另建一个目录按上面的全新安装步骤获取稳定版，旧目录保持原样。不要为更新而强制重置、清理文件或覆盖自己的书本。

仅当工作区干净、没有需要保留的分支工作时，切到稳定分支并只接受快进更新：

```sh
git switch main
git pull --ff-only origin main
python3 ru --version
python3 -c "import rushu; print(rushu.__version__)"
```

若本地尚无 `main`，在确认没有同名本地分支后用 `git switch --track origin/main` 创建，再检查版本。若切换或快进失败，请停止并检查分支差异，不要强行覆盖。重新启动 `python3 -m rushu`，用新的完整地址打开页面，并重新打开保存的书本；历史输出不等于本次会话已运行。

从较旧版本升级时，按 [标准模块导入迁移](standard-module-imports-migration.md) 改用 `如:观`、`如:竞`，并查看 [阵与典遍历](array-sort-map.md)。保存书本不会自动迁移源码，也不打包外部模块。需要可重复结果时重启 Python 会话并按顺序运行；本次补丁不改变会话重定义规则。

## 执行与生成检查对照

| 入口 | 状态与宿主 | 生成结果检查 |
| --- | --- | --- |
| 如书默认 Python | 同一本书共享持久会话；提供如观画布，帧率请求 1～30 | 语法／结构检查；不读取外言依赖，不执行源码 |
| 如书显式 JS 加速（browser-js） | 每次新 Worker，不共享前格或 Python 变量；提供如观画布，帧率请求 1～60 | 同一浏览器编译器的能力／模块检查，只允许随附标准库；编译后丢弃产物，不执行源码 |
| CLI `run`／REPL | Python；REPL 可保留状态；不提供如观画布 | `generate` 默认 `--target ru`，检查源码及本地依赖，默认保存后不执行 |
| CLI `build --target js`／`generate --target js` | Node.js 18+ 独立 CommonJS 程序；不是浏览器，不提供如观画布 | 生成时先检查如源码再本地编译为 Node.js 产物，默认不执行 |
| CLI `build`（默认 C） | C99 编译器生成的独立程序；不提供如观画布 | 构建不运行；在线生成如源码后可另行构建 |

如书生成从不自动运行；已收到的完整源码即使目标检查未通过，仍保留用于审阅与修改。请求失败不替换当前草稿。Python 检查通过不表示 browser-js 可用，browser-js 检查通过也不保证运行正确、安全或达到请求帧率。不支持的浏览器能力不会悄悄回退到 Python。普通 `ru check` 不是如书图形目标检查器。

离线提示词导出也应匹配目标：

```sh
python3 ru rushu-prompt --target python
python3 ru ruguan-prompt --target browser-js -o ruguan-browser-system.txt
```

这两个命令的目标只有 `python`／`browser-js`，默认 `python`；不同于 CLI 构建／生成的 `--target js`。导出不请求模型、不读取凭据、不运行代码。把全文交给其他 LLM 后，仍应先审阅返回源码再放到对应代码格运行。细节见 [提示词导出](prompt-export.md)、[如书说明](../rushu/README.md) 与 [浏览器保护边界](browser-js.md)。

## 环境与已验证范围

- 编译器 / REPL：Python **3.10+**，只用标准库，无 pip 依赖
- 原生编译：Clang、GCC 或兼容的 C99 编译器；依次自动查找 `clang`、`gcc`、`cc`
- JavaScript 执行：Node.js **18+**，使用内置标准库，无 npm 依赖；不是浏览器 / DOM 目标
- 可通过 `--cc gcc` 或 `CC=gcc` 指定编译器；参数通过 argv 传递，不经过 shell
- 仓库初始化验证：Linux x86-64、Python 3.12.3、GCC 13.3.0；位置调用更新验证：Linux x86-64、Python 3.12.14、GCC 14.2.0。各次记录见 `VALIDATION.md`
- 仓库只保存源码；`bin/`、`dist/` 由 `make examples` 或 `ru build` 在本机生成。原生程序依赖构建时的目标架构和系统库，应在目标系统重新构建
- Windows：可在已有 WSL 中按上述命令使用。也提供 `ru.cmd`，可通过 `py -3 ru repl` 运行 Python 前端；Python 解释器对 Windows 控制台使用 Unicode 输出（含 `add.ru` 中文输入提示），重定向输出保持 UTF-8，无需修改系统代码页。Windows 原生 Clang/GCC 编译以及 `.exe` **未实测**，不承诺即开即用
- macOS、其他架构和 Python 3.10/3.11 未在本次环境实测

如需研究静态输出，工具链支持时可使用 `--cc "gcc -static"`；静态库、目标平台兼容性及第三方库再分发义务由该工具链决定。默认构建使用动态链接。

### 编辑器

普通文本编辑器保存 UTF-8 `.ru` 文件即可。VS Code 配置见上文；Emacs 使用仓库随附的 [ru-lang-mode](../emacs/README.md)，支持高亮、缩进、导航与 `C-c C-r` 运行。完整安装与快捷键以各编辑器说明为准。

独立程序、编译器选择、CommonJS 和输出保护见[命令行与独立程序](command-line.md)。语言仍在原型阶段；当前变化见[变更记录](../CHANGELOG.md)，实测范围见[验证记录](../VALIDATION.md)。

[返回文档导航](index.md)
