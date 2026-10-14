# 如书／如观系统提示词导出

这两个子命令把当前安装版本随附的生成知识导出为 UTF-8 纯文本，供其他 LLM 使用。导出完全离线：不读取 `~/.ru-lang.json`、提供方环境变量或密钥文件，不配置提供方，不发送请求，不运行生成代码。

## 命令

在仓库根目录运行（已安装 `ru` 时可直接用 `ru` 代替 `python3 ru`；Windows 可用 `py -3 ru`）：

```sh
python3 ru rushu-prompt
python3 ru ruguan-prompt
python3 ru rushu-prompt --target python
python3 ru ruguan-prompt --target browser-js -o ruguan-browser-system.txt
python3 ru rushu-prompt -o rushu-system.txt
python3 ru ruguan-prompt --output ruguan-system.txt
python3 ru ruguan-prompt -o -
python3 ru ruguan-prompt -o ruguan-system.txt --force
```

- `--target python|browser-js`：选择如书执行宿主，默认 `python`。两个导出命令都支持；这不是 CLI 构建／生成的 Node.js `--target js`。
- 省略 `-o` 或指定 `-o -`：只向 stdout 写提示词，不夹带成功说明或进度，适合重定向与管道。诊断写 stderr。
- `-o PATH` / `--output PATH`：写 UTF-8 文件，不限扩展名；父目录须已存在。成功时 stdout、stderr 均为空。
- 默认拒绝任何已存在的输出路径。`--force` 明确允许替换已有普通文件，也可写新文件；不能用于 stdout。
- 写入先在同一目录准备完整临时文件，再原子发布。写入失败不会截断旧文件；默认模式下另一进程抢先创建目标也不会被覆盖。
- 即使用 `--force`，也不覆盖符号链接（包括失效链接）、目录、特殊文件、随附语言规范自身及其硬链接。不同进程仍应避免同时强制写同一输出路径。
- shell 的 `>` 重定向由 shell 自己控制，可能提前截断已有文件；需要上述保护时请用 `-o PATH`。

## 两种内容的区别

`rushu-prompt` 与如书对应执行方式调用生成提供方时的 system 消息逐字相同：包括生成约束、所选 Python 或 browser-js 代码格宿主说明，以及唯一一份完整语言规范。它适合普通如书代码、文本、算法和图形任务。

`ruguan-prompt` 使用同一组装逻辑、同一完整规范与如书宿主说明，只追加一段如观聚焦指导：重点阅读图形接口、回调生命周期、数学与随机标准库，区分初始化与逐帧更新。完整如观签名、数学函数、随机源规则都直接来自规范，不维护另一套接口表，也不重复嵌入全文。它生成的图形代码仍应在如书中运行；普通 CLI、C 或 Node.js JavaScript 后端不提供如观画布宿主；如书显式 browser-js 是单独的浏览器目标。默认导出仍以 Python 为目标；`--target browser-js` 明确选择独立浏览器 Worker 的宿主说明，并保留如观聚焦指导。

当前如 0.19.5 的四种组合均携带同一完整折线合同：`图 其 折线 点阵` 的必需参数、2～256 个二维有限数点、开放路径一次描边、深复制与原有预算；如观聚焦提示另外提醒用原生折线绘数据曲线，不逐段模拟。

两者都会在每次导出时重新读取随包发布的规范，标明语言版本、规范版本及原始规范 UTF-8 字节的 SHA-256。缺失、损坏或版本不一致会失败，不退回旧提示词。因此升级工具链后应重新导出；导出文件本身不会自动更新。

## 如何交给其他 LLM

1. 把导出的全文原样放进 LLM 的 `system` 消息，或支持系统指令的客户端对应字段。不要只复制规范链接或摘要。
2. 把具体程序需求放进独立的 `user` 消息。这里无需末尾的「如是我言」标记；该标记是如书／`ru generate` 的入口，不是源码。
3. 要求返回纯如源码；提示词已经包含这项要求。先人工审阅，再复制到与导出目标一致的如书代码格运行。Python 格共享本书会话；browser-js 格每次独立，须把导入、数据初始化、画布与回调放在同一格。导出提示词不会自动切换代码格执行方式。

若客户端只有单一聊天输入框，可以把全文放在需求之前作为上下文，但它不等同于独立的 system 消息。需使用能容纳整份规范的上下文窗口，避免客户端截断。导出命令不会为外部模型配置工具、输出 token 上限或隐私选项，也不能保证外部模型遵守规范。

导出内容不包含你的书本、草稿或需求。你向其他提供方提交的个人需求及代码会离开本机，请自行确认发送范围。静态检查不是执行验证；如观宿主能力也不能用 `ru check` 成功来替代。

## Python 公共接口

```python
from rulang.generation import generation_system_prompt
from rulang.prompts import export_prompt

text = generation_system_prompt("rushu")  # 与如书生成请求相同
text = export_prompt("ruguan")           # 返回文本，默认不写文件
text = export_prompt("ruguan", runtime_target="browser-js")
path = export_prompt("ruguan", "ruguan-system.txt", force=True)
```

`generation_system_prompt` 接受 `cli`、`rushu`、`ruguan`、`rushu-browser-js`、`ruguan-browser-js`；后两项用于显式浏览器 JS 目标（后者追加如观聚焦指导），说明独立状态、1～60 FPS 请求及没有 Worker 64 MiB 硬内存配额。`cli` 保持普通命令行生成的运行环境限制。`export_prompt` 的首个参数只接受 `rushu`／`ruguan`，`runtime_target` 接受 `python`／`browser-js`（默认 `python`）；`output=None` 或 `"-"` 返回字符串，实际文件路径返回发布后的 `Path`。出错抛出 `RuError`（随附规范错误可能是其 `GenerationError` 子类）。这些接口也无需提供方配置。

## 标准模块名

导出与真实请求使用同一份当前规范：如观导入 `如:观`，如竞导入 `如:竞`。旧导入名仅用于解释迁移错误，不是可用别名。已有书本不会自动改写或执行；请参见 [标准模块导入迁移](standard-module-imports-migration.md)。导出默认面向如书 Python；用于 browser-js 时给导出命令加 `--target browser-js`，并在代码格中显式勾选「JS 加速」。如书的 browser-js 生成结果会经过浏览器能力／编译检查，Python 生成只做语法／结构检查；两者均不自动运行，外部 LLM 的返回也不会被导出命令自动检查。

## 0.19.1 透明度契约

两种命令、两种目标都从当前完整规范取得 `#RRGGBB`／`#RRGGBBAA`、`观 其 颜色 红 绿 蓝 不透明度` 的四个必需整数参数，以及背景清除与逐帧重绘规则。`AA` 为不透明度，0 全透明、255 不透明；不应让生成器猜测 0～1 比例、可选参数、钳位／舍入、HSB 或 p5 拖尾。升级后按上面的离线命令重新导出；无需另行维护或拼接一份图形规范。

## 0.19.2 文字对齐契约

四个导出组合均携带同一完整规范及实际 SHA-256，包含 `文字对齐 横向 纵向` 的严格枚举、默认左上、跨回调样式、保存恢复和旧历史缺省语义。让文字居中应设置锚点，不用字符数猜测宽度。文字宽度测量仍未提供，真实秒数接口见后续 0.19.3 契约；离线导出与模拟请求验证不调用付费模型。

## 0.19.3 真实时间契约

四种导出均包含完整唯一规范与实际 SHA-256，以及零参 `经过秒`／`间隔秒`、回调内冻结、暂停／隐藏页／初帧规则与原有一参每帧回调。图形生成指导采用真实秒数，明确区分原始间隔和应用自行限制的积分步长；不把帧数除以目标 FPS 当作真实时间，也不生成读取快照等待的忙循环。文字测量仍未提供。

## 0.19.4 弧与扇形契约

`rushu-prompt`／`ruguan-prompt` 的 Python／browser-js 四种组合都嵌入同一份当前完整规范及其实际 SHA-256。公开弧／扇形均以外接框、始角和带符号转角表达，角度为弧度；弧只描边，部分扇形闭合到中心，零转角保留命令，绝对转角至少一周为无辐条的整椭圆。图形聚焦指导优先使用原生接口，不用折线近似原生弧，不虚构弦形、贝塞尔曲线或路径构造器。导出仍离线且不执行，不调用付费模型。
