# 编辑器诊断格式

Ru CLI、解释器、C 和 JavaScript 生成程序使用 GCC 风格的错误标题：

```text
文件:行:列: error: 类别：说明
```

例如 `C:\项目 空间\示例.ru:51:5: error: 语法错误：此处需要名称`。
路径原样保留，包括盘符、空格与中文。解析器不能简单按冒号拆分路径，应从末端匹配数字行列和 severity。行、列从 1 开始；有列时列按 Unicode 码点计数，不是 UTF-8 字节、UTF-16 代码单元或屏幕宽度。编辑器若使用 UTF-16，需用对应源码转换含非 BMP 字符的列。

C 普通运行错误当前只有真实行号，使用 `文件:行: error: 类别：说明`，不伪造列。C 的未救之卒、JavaScript 与解释器保留已有精确列。未知的宿主错误不能据此猜测源码位置。编译器自身报告的 C 诊断可能引用生成文件，不能误认为 Ru 原始源码。

程序 stdout 与 stderr 的流内容互不改写。如果终端合并两流，程序自己输出的无换行提示可能与诊断相接，基于行首的文件匹配器不能保证解析；需要可靠定位时应独立消费 stderr 或如书的结构化事件。

程序输出仍走 stdout；CLI/生成程序错误走 stderr，退出码不变。Python／如书的可显示诊断标题与 CLI 源码附行将 C0/C1 控制字符、DEL 与 Unicode 双向控制符转义（例如 `\n`、`\r`、`\t`、`\u001b`、`\u202e`），防止路径或说明伪造多行诊断；结构化 source_name / message 保留原文用于可靠导航。C／JavaScript 的编译期来源路径同样转义显示控制字符；受独立产物体积约束，运行时动态错误说明尚不保证过滤所有此类字符。中文类别和说明不改为英文，只有标准 severity 为 `error`。

## 如书事件

如书错误继续通过独立 `type: "error"` 事件发送，不混进程序 stdout。顶层 `cell_id`、`execution_count`、`generation` 表示触发此次执行的身份，原有 `line`、`col`、`source_name`、`category`、`message` 字段保留。

新增 `diagnostic` 对象含：

- `source_name`、`line`、`col`、`severity`、`category`、`message`
- `formatted`：供复制的标准错误标题
- `source`：错误发生的源码身份

代码格来源是显式虚拟 URI：

```text
rushu://会话ID/内核代数/百分号编码格ID/执行次数.ru
```

这不是磁盘文件，不应交给普通文件打开匹配器。其 `source` 含 `kind: "cell"`、`cell_id`、`execution_count`、`generation`、`source_version`。版本是该次执行原始代码 UTF-8 字节的 SHA-256 十六进制值；execute 响应和 session snapshot 也返回最近的 `source_version`，重启后清空。真实文件来源为 `kind: "file"`。无法精确定位的宿主／生命周期错误在 `diagnostic` 中以 `line: null`、`col: null` 表示，标题省略坐标；顶层旧字段仍保留原有兼容默认值，前端不应据此定位。

旧格定义的函数、闭包和如观回调保留定义时的来源元数据，不保留整份代码文本。发生错误时，来源格与触发执行格可能不同。前端只有在格ID、内核代数、执行次数、版本摘要及未修改的执行快照均匹配时才定位；外部文件、已删除格或过期版本仅显示来源，不能错误标记当前格。
