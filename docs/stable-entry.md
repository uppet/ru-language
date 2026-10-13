# 稳定版入口、更新与执行目标

## 取得同一套工具链

当前稳定组合为 **如 0.18.1、语言规范 0.18.1、如书 0.7.0**，均来自语言仓库的 `main`。本工作树为 **如 0.19.0、语言规范 0.19.0、如书 0.8.0**，属于 `wip` 开发版本，尚未发布到 `main`；本文的安装与更新命令不会承诺取得该开发版本。`wip` 用于后续开发，可能先于稳定版变化；学习与普通使用从 `main` 开始。`main` 是经过验证的稳定使用入口，语言本身仍处于原型阶段，不表示永久冻结语法。

需要 Python 3.10+ 和仓库访问权限。全新安装：

```sh
git clone --branch main https://github.com/uppet/ru-language.git
cd ru-language
python3 ru --version
python3 -c "import rushu; print(rushu.__version__)"
python3 -m rushu
```

Windows 可把 `python3` 换成 `py -3`。打开终端打印的完整本机地址，保留其中的启动令牌。如书启动、离线编辑及 Python／浏览器 JS 执行均不需要 npm；只有 CLI JavaScript 产物执行需要 Node.js 18+。

如言 VS Code 扩展 **0.7.0** 已支持 0.18.0 的语言接口，也适用于 0.18.1；本次补丁没有新增语法或编辑器接口，不要求重装扩展。扩展与语言仓库分别发布，扩展不内置解释器。其“运行当前文件”走普通 CLI，不是如书画布入口。把扩展的 `ru.cliPath` 指向本机语言仓库的 `ru` 文件，解释器路径指向已安装的 Python；普通文本编辑加终端命令同样可用。

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
