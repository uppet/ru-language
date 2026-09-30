# ru-lang-mode：Emacs 基础语言支持

`ru-lang-mode.el` 用于查看和编辑如语言 0.2.x 的 `.ru` 源码。只使用 Emacs 自带的库，不需要安装其他包、Python 进程、LSP 或 tree-sitter。

目标版本为 Emacs 28.1+；本次本地实测 GNU Emacs 30.1（Linux）。仓库 CI 另用 Ubuntu 24.04 提供的 `emacs-nox` 运行相同测试。macOS / Windows 的图形界面未实测。

## 加载

把下面两行加入 `~/.emacs.d/init.el`，将路径改成自己的仓库路径：

```elisp
(add-to-list 'load-path (expand-file-name "~/src/ru-language/emacs"))
(require 'ru-lang-mode)
```

重新打开 `.ru` 文件就会自动进入 `如` 模式。已经打开的文件可执行 `M-x ru-lang-mode`。

临时试用，无需修改配置：

```sh
emacs -Q -L ./emacs -l ru-lang-mode examples/objects.ru
```

## 常用操作

| 按键 / 命令 | 用途 |
| --- | --- |
| `TAB` | 缩进当前行 |
| `C-M-\` | 缩进选中的区域；整份文件可先按 `C-x h` |
| `C-M-a` / `C-M-e` | 跳到前一个定义开头 / 当前或下一个定义末尾，包括形与方法 |
| `C-M-h` | 使用 Emacs 标准的定义选区命令 |
| `C-c C-p` | 跳到前一个代码块开头 |
| `C-c C-n` | 跳过当前最内层代码块；在块外时跳过下一个块 |
| `C-c C-u` | 回到当前最内层块的开头；再次按可回到外层 |
| `M-{` / `M-}` | 按空行分隔的段落前后移动 |
| `C-M-b` / `C-M-f` | 使用标准括号 / 字符串移动 |
| `M-;` | 使用标准注释命令，新增注释采用 `#` |
| `M-x imenu` | 按名称选择形、算、作或方法，如 `算 人@姓名` |

`C-c C-p` / `C-c C-n` 接受数字前缀，例如 `C-u 3 C-c C-n`。`C-M-a` 使用负前缀时向后面的定义开头移动，例如 `M-- C-M-a`。

“代码块”包括 `算 … 法`、`作 … 为`、`形 … 象`、`若 … 则 … 另 … 然` 和 `循 … 环`；括号移动使用 Emacs 自带命令。

## 缩进与高亮

- 默认每层 4 个空格，不插入 Tab 字符
- 按块与括号 / 方括号层数缩进；结束词、`则` 和 `另` 与对应开头对齐
- 可识别同行紧凑块、形内方法、跨行参数 / 条件、中文全角标点
- `为 数` / `为 句` / `为 阵` 转换、参数 / 字段注解以及完整名称 `为乐` 不会被误当成过程结束
- 支持 `'…'`、`"…"`、`‘…’`、`“…”` 及转义。多行字符串的内容行和结束引号所在行保持原样，避免缩进改动字符串的值
- 支持 `#` 和 `//` 行注释；字符串与注释中的块关键词不参与缩进和跳转
- 关键词、内置名称、类型以及定义名按完整词法名称高亮，不会把 `算法`、`为乐`、`若²` 等名称拆开
- `imenu` 为形内方法加上形名，方便区分同名方法

改成两个空格：

```elisp
(setq ru-lang-indent-offset 2)
```

也可以只为如文件设置其他编辑偏好：

```elisp
(add-hook 'ru-lang-mode-hook
          (lambda ()
            (setq-local ru-lang-indent-offset 2)
            (display-line-numbers-mode 1)))
```

这是容错的轻量编辑模式，不做语义检查、补全或代码执行。未完成的定义尽量延伸到文件末尾，残缺括号或错误源码可能影响后续缩进；请使用 `python3 ru check 文件.ru` 检查真实语言错误。在缩小范围（narrowing）的缓冲区中，仅分析可见范围。

## 测试

在仓库根目录执行：

```sh
make test-emacs
```

等价命令：

```sh
emacs -Q --batch -L emacs \
  --eval '(setq byte-compile-error-on-warn t)' \
  -f batch-byte-compile emacs/ru-lang-mode.el emacs/ru-lang-mode-tests.el
emacs -Q --batch -L emacs \
  -l emacs/ru-lang-mode-tests.el -f ert-run-tests-batch-and-exit
```

也可指定 Emacs 可执行文件：`make test-emacs EMACS=/path/to/emacs`。测试包含模式选择、高亮、两种注释、四种字符串、转义与多行编辑、完整中文名称、缩进幂等性、紧凑块、嵌套方法、转换和注解、Imenu、定义 / 块 / 段落跳转，以及不完整源码的每个输入前缀。
