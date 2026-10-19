# 如是我言：可选的代码生成

普通编辑、运行、如书与离线练习都不需要账号或 API key。只有你明确选择在线生成时，才会把意图发给配置的提供方，并可能产生费用。先阅读生成的代码，再决定运行。

本页对应 `main` 上的如 0.22.0；输出 token 预算选项自 0.18.2 加入，当前工具链组合见[版本说明](stable-entry.md)。如书里的操作流程、发送范围与历史恢复见[学习模式](../rushu/README.md#学习模式如是我言)。

`examples/wish.md` 示范自由 Markdown 文档；Org 或其他 UTF-8 文本也可使用。最后一个非空行必须单独写 `如是我言`，且不能位于如的字符串内部。前面的文本作为生成意图，不要求预先符合如语法。为避免把多行源码字符串误当文档，引号需成对；两侧紧邻 ASCII 字母的单引号按英文词内撇号处理（如 `Don't`）。ASCII 函数名后直接贴字符串起始引号可能有歧义，源码应在两者之间加空格。

仅显式执行 `ru generate` 会联网，将这份意图和当前语言规则发给配置的提供方。每次请求都会重新读取包内 [完整语言规范](../rulang/language-spec.md)，明确要求按该规范生成，并把实际全文、规范版本和 SHA-256 放入模型上下文；不会仅发送仓库链接，也不依赖模型已经知道如。缺失、无效或版本不一致的规范会在联网前报错。`run`、`check`、`build` 与 REPL 遇到意图文档会提示先生成，始终不会代为联网。生成后默认不执行；仅显式追加 `--run` 才会在检查、保存成功后运行本次生成的程序。生成流程不自动授予原生权限，不能用 `generate --run` 执行如:密／如见程序。

## 配置与间接密钥文件

默认读取 `~/.ru-lang.json`，可用 `RU_LANG_CONFIG` 指向另一份 JSON 文件：

```json
{
  "base-url": "https://open.bigmodel.cn/api/v1",
  "model": "glm-5.3-flash",
  "api-key": {"file": "~/.config/ru/api-key"}
}
```

请由使用者通过安全方式把凭据配置到仓库外的密钥文件；文件只包含密钥本身，可带末尾换行。不要将真实密钥写进 `.ru`、意图文档、提交记录、错误截图或公开聊天。此仓库不含可用凭据。

- `api-key` 普通字符串是字面密钥；以 `@file:` 开头则读取文件内容，例如 `"api-key": "@file:~/.config/ru/api-key"`
- `{"file":"路径"}` 也是文件引用，仅支持 `file` 一个成员。文件引用支持 `~`，相对路径以配置文件所在目录为基准
- JSON 也接受 `api_key` / `base_url` 别名；可选 `max-output-tokens`（别名 `max_output_tokens`）必须是正整数，同一字段不能同时写两种拼法
- 环境变量优先于 JSON：`RU_LLM_API_KEY`（始终为字面值）优先于 `RU_LLM_API_KEY_FILE`（始终为文件路径）；另有 `RU_LLM_BASE_URL`、`RU_LLM_MODEL`、`RU_LLM_MAX_OUTPUT_TOKENS`
- 环境的密钥文件相对路径也以配置文件目录为基准；`RU_LANG_CONFIG` 的相对路径以工作目录为基准
- 未配置提供方 / 模型时，当前默认是上例指定的 BigModel API 根地址和 `glm-5.3-flash`。密钥没有默认值，缺失时不联网

也可只配置环境变量：

```sh
export RU_LLM_BASE_URL='https://open.bigmodel.cn/api/v1'
export RU_LLM_MODEL='glm-5.3-flash'
export RU_LLM_API_KEY_FILE="$HOME/.config/ru/api-key"
python3 ru generate examples/wish.md -o examples/wish.generated.ru
```

`base-url` 是 API 根地址，不要附加 `/responses`；实现会请求 `POST /responses`。不自动改成 Chat Completions，不自动替换提供方地址或模型。普通远程地址必须 HTTPS，禁止含 URL 用户信息、查询参数或片段；重定向会停止，不会把认证头转发到另一地址。

## 输出 token 预算与超时

默认不发送 `max_output_tokens`，由提供方／模型采用自己的默认值；省略不表示无限，实际默认上限可能未知。需要显式预算时可任选以下入口（数字仅作配置示例，不保证提供方支持该值）：

- JSON：在配置对象中加 `"max-output-tokens": 32768`，或使用 `"max_output_tokens": 32768`，不要同时写两种拼法
- 环境变量：`export RU_LLM_MAX_OUTPUT_TOKENS=32768`
- 单次 CLI：`python3 ru generate intent.md -o draft.ru --max-output-tokens 32768 --verbose`
- 如书启动：`python3 -m rushu --max-output-tokens 32768`

预算优先级为 CLI／如书启动参数 > 环境变量 > JSON > 省略。显式值须为 1 至 2147483647 的整数；环境变量／CLI 参数仅接受最多 10 位 ASCII 十进制数字，不接受空格、正负号或科学计数法。0、负数、小数和布尔值不是有效预算。JSON 使用整数数值，不使用字符串或 `null` 代表省略；不想设置时删除该字段。提供方仍可能拒绝超出模型能力的值。

`--timeout`／如书 `--generation-timeout` 只控制等待秒数，不控制 token。增加等待时间不会解决已返回的 `incomplete`／`max_output_tokens`；应参考诊断中的预算与提供方用量，再决定是否调整预算或缩小需求、手动重新生成。重新生成可能再次计费，不会自动重试。

## 保存、审阅与运行

```sh
python3 ru generate intent.md                  # 默认 intent.generated.ru
python3 ru generate intent.md -o draft.ru --timeout 3600
# 直接保存编译后的 JavaScript；不会另存中间 .ru：
python3 ru generate intent.md --target js -o fresh.js
# 只将验证完成的源码写入 stdout，诊断走 stderr；不会创建默认输出文件：
python3 ru generate intent.md --stdout --verbose > stdout-draft.ru
python3 ru generate intent.md --target js --stdout > stdout-fresh.js
# 明确授权生成后立即运行，仅用于你愿意信任生成结果的场景：
python3 ru generate intent.md -o run-fresh.ru --run
# 明确替换已有产物；生成或验证失败时保留旧文件：
python3 ru generate intent.md -o run-fresh.ru --force --run
python3 ru generate intent.md --target js -o run-fresh.cjs --run
python3 ru check draft.ru
# 先阅读 draft.ru，确认其行为，再决定执行：
python3 ru run draft.ru
python3 ru build draft.ru -o bin/draft
python3 ru build draft.ru --target js -o dist/draft.js
node dist/draft.js
```

- `--verbose` 在 stderr 汇报读取、发送、等待、检查等真实阶段及累计耗时，等待时定期更新；还说明本次是否发送输出预算、提供方实际返回的数值 usage（包括返回时的 `reasoning_tokens`）、`output` 项类型摘要及是否存在可见助手文本。缺失的用量不编造为零；非流式请求无法报告模型 token 进度或百分比。与 `--stdout` 同用时，标准输出仍只含检查后的源码；与 `--run` 同用时，标准输出为程序输出。通讯失败区分 TLS 证书、TLS 连接、HTTP 状态、超时、连接失败和响应中断；不会记录密钥、认证头或原始请求／响应正文。
- 单次非流式 Responses 请求，无自动重试。默认连接／读取超时 1800 秒（半小时），可用 `--timeout 秒数` 覆盖（如 3600）；接受有限正数，无固定 300 秒上限；超时或取消后服务端可能已计费
- 不启用模型工具，忽略 reasoning 正文，只提取完成的 assistant 文本；工具调用、拒绝、错误、空输出、未完成 / 取消响应都不会执行或保存。`incomplete` 的 `max_output_tokens` 与 `content_filter` 分别给出预算耗尽和内容过滤诊断，不一律归因于权限或额度；如书可保留已经返回的可见部分文本供诊断，不把它加入源码草稿或模型版本。数值 `reasoning_tokens` 不是隐藏推理内容
- 接受纯源码，或恰好一段完整的 Markdown / Org 如代码围栏；混合说明、多段或残缺围栏拒绝
- 输出先通过 lexer / parser、结构及显式调用检查，包括已有本地外言依赖。检查阶段不会执行源码或导入模块的顶层语句；这不是静态证明或安全审计
- 默认 `--target ru` 保存新的 `.ru`，默认 `原名.generated.ru`；`--target js` 保存新的 `.js` / `.cjs`，默认 `原名.generated.js`。父目录须已存在；默认拒绝覆盖已有输出。`--force` 仅允许替换普通输出文件，仍拒绝意图本身、与意图或依赖同 inode 的文件、符号链接、目录与特殊文件。完整内容验证并同步后原子发布，不自动创建目录
- JavaScript 目标仍只向模型索取如源码，再由本地编译器降为 JavaScript；不增加第二次模型请求，也不保存中间 `.ru`；默认不调用 Node 或执行，只有 `--run` 才通过 Node 运行已保存的 JavaScript。需要审阅和保留如源码时使用上面的两步生成 / 编译流程
- `--stdout` 与 `-o` / `--output`、`--run`、`--force` 互斥，冲突会在读取配置、联网前拒绝。输出完整验证后才写入 stdout，失败不会输出部分源码。重定向由 shell 管理，可能提前创建或截断目标文件，请自行选择新路径；生成命令本身不执行源码，管道另一端的行为由用户选择。
- `--force` 可与 `-o`、`--run` 组合；旧产物直到新结果完整验证并写入临时文件、同步成功后才原子替换。请求、验证或编译失败保留旧文件；显式运行只运行本次成功发布的文件，失败生成不会退回运行旧产物。
- `--run` 明确选择跳过人工审阅：验证、保存成功后运行本次文件，Ru 使用正常 `ru run` 语义，JS 使用 Node（缺少 Node 时在联网前拒绝），标准输入／输出／错误保持交互可用，退出码反映运行结果；生成提示写 stderr。运行失败仍保留生成文件，不自动重试模型。源码检查不是安全审计或沙箱，执行具有当前用户权限；如书仍只在手动点击运行后执行。
- `--stdout` 的外言相对意图文档所在目录解析，与 shell 的重定向位置无关；文件模式的外言相对最终输出路径所在目录解析；JavaScript 将已检查的静态依赖内联。编译失败不留下半份输出
- 响应上限 2 MiB，意图 / 生成源码上限 1 MiB；配置和密钥文件也有读取上限
- 不回显密钥、请求认证头、提供方原始错误正文或无效生成源码；发现意图、返回源码或输出路径含当前密钥也会拒绝处理
- 生成源码可能调用文件写入 / 删除等真实操作，建议先审阅，仅在愿意承担这些风险时使用 `--run`；生成成功不代表程序正确或安全

提供方依据：[BigModel OpenAI 兼容说明](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)、[Responses 指南](https://docs.bigmodel.cn/cn/guide/develop/responses/introduction)、[GLM-5.3-Flash](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash)。本实现不强制关闭该模型的 thinking。**协议模拟通过不等于真实 GLM 端点、账号权限或模型兼容性已验证**；本轮未使用真实提供方凭据，也未发出真实 GLM 请求。

需要排查空输出、未完成或预算耗尽时，见[生成诊断](generation-diagnostics.md)。只想把规范交给其他 LLM，可用[离线提示词导出](prompt-export.md)。

[返回文档导航](index.md)
