# 如书 0.3.3／如 0.15.0 验证

日期：2026-10-12。主库基于 `wip` 的 `50ce603d7beb4769aaa6222aca67916b30931075`，基线 tree `b00389d3cb6aeb02c900310da533c59a5d3e77d5` 与本地完全一致。独立 VSCode 0.5.1 基于 `f69d3ace09a6b33cccba2c7afdcc309ed8da1aaf`，tree `ae1aa42149581b791d4dc6dfa7e831302b810af8` 同样核对一致。

## 范围与契约

- Python CLI、C／JavaScript 生成程序采用 `file:line[:column]: error:` 标题；C 普通运行错误只有行，不虚构列。Unicode 列按码点计数。
- 如书错误事件携带不可变执行来源元数据与源码摘要。旧格函数、闭包和如观回调保留定义来源；只有仍匹配执行快照时才高亮／跳转，宿主错误不猜测位置。
- 浏览器提供错误行背景、行号和列标记；如观回调失败同步代码格错误状态。代码编辑、旧事件、停止、删除和历史恢复不污染当前执行状态。
- 新增离线 `rushu-prompt`、`ruguan-prompt`，支持 stdout 及 `-o`／`--output` UTF-8 文件输出，不请求模型。
- VSCode Tasks problem matcher 兼容有／无列的标准及旧诊断格式；按文件行定位，避免将码点列误当 UTF-16。Emacs comint 接入 compilation-shell-minor-mode，保留输入交互。

未引入浏览器 JavaScript 执行后端，未改如观 1 秒／500000 跟踪行／64 MiB／10 秒硬看门狗阈值。本轮未修改语言语法规则。

## 最终自动化验证

环境：Linux、Python 3.12.14、Node.js 24.19.0、GCC 14.2.0。

- Python 最终全集：926 项，922 通过、4 项 Windows 控制台专属测试跳过，494.817 秒。
- Node 最终全集：127 项，123 通过、4 项可选 renderer 测试跳过；真实浏览器另行验收如下。
- `make examples examples-js`：全部 C／JavaScript 示例构建和 JavaScript 语法检查通过。
- `compileall`、`git diff --check` 通过。
- 独立 VSCode 0.5.1：lint、49 项单测、VSIX 打包以及真实 Ru 工具链 snippets／stdin／图形宿主 smoke 通过。

初轮全集发现两项旧诊断字符串断言未包含新增 `error:` severity；仅更新其预期格式，并在上述最终全集中重新通过。

独立审查：33 项 Python 诊断／原生后端／prompt 测试、9 项 Node 来源标记／回调／执行身份测试、4 项 VSCode matcher 测试通过。另检查匿名／嵌套闭包旧来源及坏参数调用的新来源。发现的 C 行级诊断不匹配已修复并独立复验。

固定短路径下生成 C：P1010 49,863 字节、frequency 60,540 字节；保留原有体积门槛。来源路径转义仅影响含控制符的路径，普通路径没有新增诊断运行时代码。文件名长度会改变源码字符串的字节量，不混用不同路径的体积数据。

## 真实浏览器验证

云端真实 Chromium 主线 14 项通过，无页面异常：模块加载；语法／运行错误格式及键盘跳转；中文与非 BMP 码点到 UTF-16 转换；修改清理与成功重跑；同格及跨格函数来源；修改旧定义后禁止过期跳转；长行横向滚动；stdout／stderr 伪诊断与 XSS 文本保持惰性；如观回调真实错误定位及状态；保存历史恢复不带实时跳转；删除清理；主动停止正常画布不误标失败。

额外使用含真实换行及 bidi 控制符的文件名，经真实外言导入触发错误：格式化来源以单行转义文本显示，结构化原始文件名保真，外部文件不误跳到当前代码格。此项通过。

## 明确限制

- 本机缺少 Emacs、X server／DISPLAY 与 xvfb-run，未运行 Emacs ERT 或真实 VSCode Extension Host；测试代码已补充，不能用正则和任务单元测试冒称真实宿主通过。
- Windows 专属与多 Python 版本需精确发布提交的 CI，不能由 Linux 单版本结果替代。
- 不改变程序 stdout 语义；无换行 stdout 与 stderr 在终端合流时，基于行首的 matcher 不保证识别。独立 stderr 和如书结构化事件不受此混流影响。
- Python／如书格式化诊断转义控制符，原始结构化值保留；C／JavaScript 本轮只保证来源路径转义，动态错误说明中的控制符仍可能影响终端显示。详见 [诊断格式](diagnostics.md)。
- 不运行真实付费模型；prompt 导出通过离线字节一致性、写入安全及模拟生成请求测试验证。

## 使用

关闭旧如书 Python 服务再启动，刷新浏览器加载新前端。仅刷新页面不会替换旧的 Python 解释器。VSCode 安装 `ru-vscode-0.5.1.vsix` 后重载扩展；主仓库与扩展仍分开发布。
