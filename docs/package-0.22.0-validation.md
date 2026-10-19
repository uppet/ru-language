# 0.22.0 包系统首版验证（2026-10-19）

## 冻结范围与版本

本批基于公开 `wip` 提交 `0fd73a7a1d32c3627d12e9e28a46d50984d0c7d7`、树 `0e7bd2f0d664e25cb95936d8feed495662cf4e25`，在独立候选目录实现。语言与随附规范升级为 **0.22.0**；如书仍为 **0.8.8**，本批没有书本格式或画布协议变化。没有修改 `main`，没有部署公共服务或创建账号／凭据。

完整回归使用 `git archive` 导出的不可变快照，生产和测试提交为 `83a40c3daec110f651570e88a61c8c80ce596176`，树 `2439d94cd6c1eb03f9e410539079337daceaa397`。随后验证报告提交不改变该生产／测试内容；发布后远端 CI 须按真实发布 commit 另行确认，不把本地结果写成远端通过。

先提交设计与失败回归，再分阶段实现语言／清单、本地依赖、显式获取和静态目录。初次安全冻结 `d209d58a` 的问题已经修复，不能以其早期绿色套件作为最终验收证据。最终全量还暴露一个旧提示词测试硬编码“外言 字符串”的断言；更新为同时验证字符串与静态模块名的完整 EBNF 后，重新冻结并重跑全量，未删除旧 `尽取` 连写／停用拼法约束。

发布前读审另发现 format 1 保存本机绝对位置、每次 sync 重选版本，不能满足搬迁后按同一锁恢复。该未发布版本保留在独立冻结历史 `be2cb3d`，第二候选先加失败回归再实施 [format 2 设计](package-system-design.md#发布前锁恢复修订format-2)。新冻结 `d1b6566` 虽有 1676 项全量绿色，独立故障注入仍发现两项缓存恢复问题；本报告仅以两项修复后 `83a40c3` 的新全量和新安全复审为最终本地证据。

## 本地完整结果

环境为 Linux、Python 3.12.14、Node.js 24.19.0、GCC 14.2.0、Git 2.52.0。

- Python／C／JavaScript 全量：1678 项，四个不重叠分片为 420／420／419／419 项；1632 通过、46 项真实 Windows 平台限定测试跳过，无失败。测试集合 SHA-256：`d82952961a54a53199bb0943a95acd0581e20dae54a690690c410608dd085fb1`。
- 如书 Node：341 项，328 通过、13 项显式可选浏览器测试跳过，无失败。
- `make examples examples-js`、`python3 -m compileall -q rulang rushu tools`、`git diff --check` 通过。
- 随附“工程／应用”示例实际在 Python、独立 C、Node.js 输出相同的 `6`、`1`、`20` 三行。
- 新包专项 127 项通过并由独立审查再次运行；覆盖语法、静态清单、边界、图身份、来源／版本、锁缓存、协议和三端整合。registry → 校验缓存 → 离线模块图使用真实协议与注入读取器；删除原包后继续解释／构建，删除源码与缓存后运行 C／JS 产品，均得到预期结果。
- 搬迁整棵应用＋相对本地依赖、清空旧缓存后，真实 registry 协议按旧锁恢复原版本；目录已有新版也不重选，锁字节不变。恢复后 Python／C／JS 图一致，删除源码与新缓存后独立 C／JS 产品仍输出原值。
- `.21.7` 句点风格资产／诊断与 `.21.8` 原生分析相关全量回归仍通过。`native_c.py`、`native_runtime.py`、`native_c_runtime.py` 与基线字节不变，没有放宽预算或删掉原生检查。

主要复现命令：四次 `python3 tools/run_test_shard.py --shard N --count 4`（N 为 0～3）；`node --test rushu/tests/*.mjs`；`make examples examples-js`；两种 `*-prompt` 命令各导出 Python 与 browser-js。不得把更窄的 `*.test.mjs` glob 当完整 Node 套件。

## 文件影响

- 核心：`frontend.py`、`modules.py`、`interpreter.py`、`compiler.py`、`js_compiler.py`、新增 `packages.py`／`package_sources.py`／`package_registry.py`、`cli.py`、`generation.py`、版本与唯一规范。
- 工具：如书 editor 与 Node 回归；Emacs 模式／ERT／README；静态资产检查工具；Makefile 的包示例构建；没有改原生运行时或增加外部 Python 依赖。
- 回归与示例：六个包测试文件（含 32 项 format 2 专项）、既有尽取提示词合同与版本检查；工程／应用共五个源码或清单文件。
- 文档：包设计、使用、目录协议、编辑器影响四份新增指南，README／CHANGELOG／CLI／索引／语言指南／原生指南／提示词／稳定入口同步，以及本报告和验证索引。

## 已验语言与包合同

- `吾 言 工程 其 力学.` 可选、只允许顶层一次；吾／言仍是普通名称。完整声明上下文才特殊识别。已有恰好写作 `吾 言 工程.` 的三名称调用会被识别为声明；保留调用可改写为 `吾 (言) 工程.`，此极窄语法兼容影响已写入指南和规范。
- 具名外言的完整其链是静态名字，不读取变量；字符串外言、固定标准库、赋值别名和尽取继续可用。
- 清单是静态单典，只接受字面量和容器，拒绝执行；重复字段、未知字段、类型错误与非法名字按位置诊断。清单文件不是普通可执行源码。
- 作者使用唯一正式根名；依赖 alias 只选择实例，不成为作者声明。公开列表的相对层级映射源码根，显式 map 的路径相对包根。未声明模块按唯一正式路径推导身份，不能由私有 fallback 产生第二个正式名。
- 包内私有路径可用，跨包必须是已声明依赖的公开入口；真实路径与符号链接边界一起核查。清单文件本身不接受 symlink，包目录别名正规化。无清单旧脚本兼容原有文件导入。
- 具名／路径／不同依赖 alias 同一文件共享模块实例、状态和形身份；成功和失败初始化在同一次运行缓存，下一次新运行重新初始化；循环仍明确拒绝。Python、C、JS 的默认裁剪和完整运行时都覆盖。
- `ru deps sync` 才获取依赖；普通 run／check／build 与未使用但进入静态图的依赖检查均不自动联网。缺锁／缓存给出显式同步命令。
- Git／HTTPS registry／本地路径每项只选一个来源，无 fallback；同一真实来源一图单版本，冲突拒绝。三段 exact 与比较区间支持，`^`、`~`、通配、预发行等未支持语法明确拒绝。

## 锁恢复合同（format 2）

- 默认 `ru deps sync` 有锁即精确恢复；`--locked` 另要求锁存在，`--update` 才重选范围／分支。默认与 locked 成功均不改锁字节或 mtime，命中完整缓存不传输。
- owners／packages／edges 互相绑定；本地包经声明 owner＋alias 定位，远程及其内嵌包用来源派生 cache key 与安全包内位置。锁不保存自动展开的工程／缓存绝对位置，运行时取当前 `RU_PACKAGE_CACHE`。
- 显式本机绝对 path 仍可用，不为了搬迁改成 relpath；标为不可搬迁并传递到后代。Windows drive／UNC 词法有专项；真实跨盘文件系统行为仍待 Windows 验证。
- 缺失／损坏缓存只获取锁定完整 Git commit 或 registry exact version，并核原摘要、树、清单身份、依赖及约束。旧内容无法取回时拒绝，不跟随移动分支、重新选择版本或切换来源。
- format 1、损坏、schema／清单不符和 symlink 锁均明确拒绝；未发布的 format 1 仅显式 `--update` 重建。path 包清单要保持不变，普通本地源码仍可变。

## 独立安全复审

初次冻结有可复现缺陷，修复后无未关闭的已知阻断项：

1. 锁记录曾能替换 cache key／tree 摘要而指向不相符的包，或只修改 edge identity。现按 canonical 来源与 Git commit 或 registry version／archive 摘要派生并核验 cache key，绑定记录类型、URL、subdir、正式名、版本、mutable、边身份，以及缓存清单和版本约束。
2. Registry dot segment 与 Git percent alias 曾将相同实际请求分裂为多个来源身份。现拒绝易混淆的等效路径写法，并统一支持的非 ASCII UTF-8 URL；独立完整包图及真实 Git argv 反例已关闭。
3. 显式 public map 的作者名旁路和清单 symlink 所有者混淆已修复；带源码位置的直接解释器、C／JS 编译 API 也检查声明身份。

首轮原始独立 8 组反例在 `d209` 产生 17 个失败断言；修复后 8 组全部通过。另 13 组安全／离线合同通过，覆盖静态解析、嵌套重复 key、JSON 重复 key、tar／zip 路径／链接／特殊文件／大小与 header 限额、URL／ref／subdir、重定向与凭据边界、离线 CLI、本地不可变发布。首轮独立 93 项包套件通过；这些首轮结果仅作历史证据，不能替代本次 format 2 复审。

真实本地 Git 仓库配合 SSH stub 完成 fetch／archive，验证完整 commit、未执行 ambient config 指定的外部命令、hooks、filters、install 脚本或 submodule；没有访问外网。归档临时验证后原子缓存，不运行安装钩子。

format 2 在 `83a40c3` 另行独立复审，不沿用旧锁的通过结论。最终 127 项包测试、14 组新锁攻击／恢复检查和 13 组旧安全合同均通过，无未关闭的已知阻断项。新检查包括 owner 物理身份、别名 symlink 改指、不可搬迁传播、缓存 symlink、取回中断、默认不写锁／不传输、搬迁后具名与路径共享实例等。

本轮发现并关闭两项故障：普通文件损坏 cache key 时清理误用 `rmtree`，现区分真实目录与非目录；发布及回滚两次 rename 都失败时原 `finally` 会删除唯一旧备份，现仅成功提交后清理，回滚失败保留原字节并明确诊断备份位置。两项有先红后绿回归，成功恢复无 stage／damaged 残余，失败不改锁。

真实本地 Git 配合安全 SSH stub 再验证：分支从 A 推进到 B，搬迁工程、删缓存后 `--locked` 仍取回完整 A 与原 subdir，锁字节不变；默认命中缓存没有传输，只有 `--update` 才选择 B。该验证实际调用 Git init／fetch／rev-parse／archive，不是替换 `_fetch_git` 的模拟。

受审生产文件 SHA-256：

- `rulang/package_sources.py`：`d8d7048bd454ad456d3041d4a3c7d01d8225709523cf14eb433272634b219613`
- `rulang/package_registry.py`：`138c86a32aeddb82b453ce2e6468bb12aa3b85cad149aef48b5473615354fc44`
- `rulang/packages.py`：`d0ed091cad8d0fe0a03200ca4b447ca2507ede0bc8038e68cb576103bc3401af`
- `rulang/cli.py`：`0d38da96bbe9a1d6b2d57e9e54c60b52ed56168ce3ef3ca48f5055222d34e203`

SHA-256 验证内容与受信元数据／锁一致，不提供发布者认证，也不能把恶意 registry 或整体伪造的锁变成可信来源。运行包源码仍是使用者显式执行，不是沙箱。

## 两种提示词、如书与编辑器

两种命令 × Python／browser-js 四份提示词在冻结快照实际离线导出。都完整包含唯一 0.22.0 规范、包边界和声明／静态 chain 语法；不把集录混作源码，不虚构依赖，不自动获取／发布。browser-js 仍只允许固定标准库，不因新增包系统获得本机文件访问。

- 规范：`fb433f3022dbb33c642063199a6cbd904a7b280418e3e76bc45d7817ae5b62ac`
- 如书 Python：`f328e26c07b5262d8c8124090818d531943c19d3f029fe2f2ac7f57463d39bd2`
- 如书 browser-js：`008ff50c6a22056a68a798f6b5f02a775f5df47c9dc0a0b9732002efeda0007a`
- 如观 Python：`2caac5a7d9354ae1eb0d496caa657353dfcd4f802e8dccb2a46c59ac684850eb`
- 如观 browser-js：`72f447f81c00b8c4c73545010e437b9ac5a96f83533c82b8427eaa7f2f765c5e`

如书编辑器和 Emacs 源码配套 contextual 声明、静态模块段着色和清单／离线说明，不全局新增吾／言关键字、不新增缩进块。同时纠正基线外言 hover 对 C 原生能力的过时描述，明确 Windows x64 与显式授权边界并增加 ERT 断言。Node 编辑器回归通过；本机没有 Emacs，只做静态定界检查，**没有声称 ERT 或字节编译通过**，必须由对应发布提交的 CI 验证。

独立 VSCode 仓库不在本核心提交中修改或发布；完整影响项、正反例与验收边界见 [工具影响清单](package-tooling.md)。须按独立扩展实际 commit、测试、VSIX 与集成结果判断配套完成，不能用核心绿色替代。

## 首版明确边界

- 公共目录仅客户端协议与静态只读本地原型：搜索、介绍、版本、依赖、下载和本地不可变发布；没有公网服务、账户、发布认证或网络写 API。未来线上发布授权必须缺省拒绝。
- 本地发布有单文件原子提交与普通失败回滚，不宣称跨文件数据库事务或进程崩溃恢复；遗留发布锁需要人工检查后处理。依赖图中已校验的缓存可供重试复用，不承诺整图缓存事务回滚；单包不会暴露半写内容，双重 rename 失败保留旧备份供检查。
- path 依赖可变，锁不冻结本地普通源码；显式绝对路径保留原声明、标为不可搬迁。相对路径需保持声明所指的工作树布局。远程依赖可按 format 2 精确恢复；源服务移除旧 commit／归档时明确失败，不回退或升级。没有多版本求解器。
- 未实测公网 TLS／SSH 服务、第三方托管、Windows 路径与进程树终止、真实浏览器 UI／保存打开流程及 Emacs；平台专属跳过不算通过。fixture 与 SSH stub 不代替这些实机验收。
- 完整文件影响与新语法使用分别见 [设计](package-system-design.md)、[包指南](packages.md)、[目录协议](package-registry.md)、[工具影响](package-tooling.md)。
