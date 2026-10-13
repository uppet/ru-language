# 如 0.16.2／如书 0.4.2 验证（2026-10-13）

## 改动范围

普通代码格与学习格均在源码末尾、输出之前提供复制输入、运行、停止和 JS 加速。顶部保留原有完整操作，末尾不重复移动、删除及历史操作。两处选择器读取同一个 `cell.execution_backend`，按钮走相同的运行与停止入口，重新渲染时一起替换视图引用。

JS 加速与按钮同一弹性布局行，小屏自然换行；说明不再占据独立整行。提示支持鼠标悬停、键盘聚焦、Escape 关闭、唯一 `aria-describedby` 和 tooltip 角色，保留独立 Worker、不共享 Python 变量及无法强制 64 MiB 内存上限的说明。

复制不标记文档修改；修改运行后端仍标记修改。保留 Python 停止时重置会话、JS 停止时保留输出、编辑失效旧 Worker、历史恢复不自动运行等既有语义。语言后端和 VSCode 扩展未修改。

## 本地验证

- 如书 Node 测试 159 项：155 通过、4 按条件跳过、0 失败。新增 9 项执行真实 UI 函数的 DOM／状态回归，覆盖普通／学习格、上下选择器同步、重复点击单次运行、停止与禁用状态、当前文本复制、不产生脏状态、提示描述及 Escape、重新渲染引用与监听数量、历史不执行、Markdown 单按钮、忙碌时拒绝后端修改、连接和 token 条件。
- `make examples examples-js` 成功，全部 C 示例构建及 CLI JavaScript 示例语法检查通过。
- `node --check --input-type=module < rushu/static/app.js` 和 `git diff --check` 通过。

完整 Python 回归 951 项，四个不重叠分片为 238／238／238／237，全部成功；4 项真实 Windows 控制台测试按平台跳过。集合 SHA-256：`bd612fc38b259f6523fd2d892c27308b244f163c12f03c9c4bbdc9984f345957`。

独立真实 Chromium 浏览器 12 组检查全部通过，无页面错误：420 行源码末尾操作、精确复制且不产生脏状态、Python 等待输入／循环停止及重跑、JS 真实如观 Worker 停止及重跑、编辑／反复切换后端不重复执行、后端保存恢复且不自动执行、学习格长源码、1280／390 像素布局与提示。额外复验四种桌面／窄屏 × 顶部／底部鼠标移入提示均保持可见；按钮中心及上下缘命中正确，聚焦后缩窄窗口不出界。已检查真实截图。不将 Node DOM 模型测试表述为真实浏览器验证；本环境没有 Emacs，也没有真实 Windows 执行环境。


## 远端 CI 边界

本轮候选尚未发布。只读核实基线 `f0693e91bbd6daa120963cc169132e6882d07cf1` 的 [CI run 38245943101](https://github.com/uppet/ru-language/actions/runs/38245943101)：13 个任务均失败，`runner_id=0` 且步骤为空，测试没有开始。

用户在 2026-10-12 提供的此前运行注释为：

> The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings

该历史账户计费阻塞未见解除；未重新取得当前基线运行的相同注释，不能将旧文案当作新运行的独立证据。本轮不重跑工作流，不登录或更改账单。远端 CI 不能记作通过。
