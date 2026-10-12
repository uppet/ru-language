# 如书 0.4.0／如 0.16.0 验证

日期：2026-10-12。主库基于 `wip` 的 `bd0569f7655af140584dc5b0dd307bc206c80768`，基线 tree `db2a43e1d60e5d0b7a9d7a67c5c6d1008cf53e79` 与本地一致。此次仅更新主库 `wip`；主库 `main` 和独立 VSCode 扩展不变。

## 范围

- 如书代码格默认 Python，显式「JS 加速」使用新建独立 Worker；不共享其他 JS 格或 Python 会话变量。
- browser-js 编译入口和如观宿主允许最高 60 FPS 请求；页面用 RAF 单飞调度。Python 1～30、CLI C／Node.js 拒绝如观规则保持。
- 复制当前源码输入；生成意图另有独立复制按钮。复制失败明确反馈，不读取系统剪贴板。
- 停止、换书、重跑、重启与新运行使旧事件失效。保存／打开只恢复静态画面。
- 生成请求按当前格运行方式选择宿主说明；离线提示导出默认 Python，携带完整规范中的目标区别。

## 自动化

环境：Linux、Python 3.12.14、Node.js 24.19.0、GCC 14.2.0。

- Python 最终全集：950 项，946 通过、4 项 Windows 控制台专属测试跳过，528.186 秒。

- Node 最终全集：150 项，146 通过、4 项可选 renderer 测试跳过；真实浏览器另行验收。
- `make examples examples-js`：全部 C／JavaScript 示例构建和 JavaScript 语法检查通过。
- `compileall`、`git diff --check` 通过。
- JS60 示例书经编译和严格书本保存／打开 roundtrip 验证。

独立审查对本地冻结 `3682c7a` 通过：23 例 Python／browser-js 语义与逐帧画面差分，4 项空回调基线，7 项恶意／能力输入，18 项 HTTP/API 检查及 22 项新编译／宿主测试。后续候选 `78b8e8d` 的源码失效修复经独立 delta 审查及 24 项相关测试复验通过。

浮点差分使用 1e-13／1e-12 容差，stdout 精确比较。覆盖标准数学、闭包、块提升、阵／典及四个如观示例。独立数据格示例在 JS 中须先合并初始化，这是预期的隔离语义。

## 真实浏览器

真实 Chromium 154.0.8037.57：默认 Python 实际执行、Python 30 FPS 接受／60 拒绝、JS 显式开关及跨后端／重跑变量隔离、Unicode／非 BMP 诊断列、源码与意图精确复制及拒绝权限反馈、真实如回调、停止、保存／重开静态快照、切后端和删除均通过，无页面异常。

真实生命周期：根程序／回调循环预算错误会结束旧执行；全局停止可恢复；重跑只留一个 Worker；编辑、重启、换书和删格终止旧 Worker。原生键盘 Ctrl+Z 恢复源码不会复活 Worker；Chromium CDP IME 合成在 compositionend 前的 isComposing=true input 已终止旧 Worker。这两项不是仅用模拟 DOM 事件检查。

真实生产 Worker CSP 阻止 eval、Function、嵌套 Worker、WebSocket、fetch 和网络 module import，只允许生成的 Blob module。脱离如步预算的根死循环约 5000.7 ms、回调死循环约 1000.6 ms 被外层终止，主页面保持响应。无绘图回调正常确认、200 个 frame 请求合并、stdout 洪流、2049 命令、超限帧、旧 token／dispose 后消息、失败后的新 Worker 恢复均通过。

初测发现 clipboard 静态模块未入白名单及源码编辑未结束旧 Worker，已修复并对修复后代码完整复验。

### 同机完整太阳系性能

同一 Chromium 154 进程、Linux x64／AMD EPYC 9V74、viewport 1500×1200、DPR 1，backing 1120×760、CSS 867.984375×589.640625。Python 回归与 C 编译负载结束后采样，每档预热 2 秒、记录 10 秒。完整自然数学太阳系每帧 18 次三角计算，运行画面 42 条命令，悬停画面 44 条；太阳和九个运动天体的介绍、暂停、移开恢复均验证。

首轮顺序为 Ru 20／30／60，然后原生 JS 20／30／60：

| 请求 FPS | 如 browser-js 实测提交 FPS | 原生 JS 同场景实测提交 FPS |
| --- | ---: | ---: |
| 20 | 19.767 | 20.000 |
| 30 | 29.251 | 30.001 |
| 60 | 57.570 | 60.004 |

60 档达到同场景原生提交帧率约 95.94%，可以称接近原生，不能称稳定达到实测 60 FPS。Ru 回调派发到 Canvas 提交完成延迟 p50 2.4 ms／p95 3.8 ms，提交间隔 p95 22.9 ms；原生提交间隔 p95 17.4 ms。

Ru 主线程 Canvas 调用 CPU p50 0.2 ms／p95 0.3 ms，不含 Worker 计算；原生 math+Canvas CPU p50 0.3 ms／p95 0.4 ms。这两项范围不同，不用它们计算提速倍数。所有 FPS 是 Canvas 绘图命令提交完成间隔，不是 GPU 完成、合成器呈现或物理屏幕 FPS。原始样本和完整统计保留于 [性能数据目录](benchmarks/browser-js-2026-10-12/forward-summary.json)。

反向顺序复测只做 60 档，先原生、后 Ru：原生 60.002 FPS，Ru 57.858 FPS；对应提交间隔 p95 为 16.9／20.3 ms。与首轮一起保留，不用最佳样本替代首轮。两轮 Ru 为 57.57～57.86 FPS，约为同场景原生的 95.94%～96.43%。见 [反向复测](benchmarks/browser-js-2026-10-12/reverse-summary.json)。上述八个 FPS 数值均由保留的原始提交时间戳独立重算一致。

## 保护与限制

- 浏览器 Worker 不提供 64 MiB 堆内存硬配额，Python 跟踪行／新增分配预算不适用。快速大分配仍可能影响标签页／浏览器进程。
- 初始化／回调超时依赖浏览器主线程调度，不构成绝对实时保证。编译阶段有并发 2、200000 字符和 20000 AST 节点限制，无独立子进程墙钟硬中断。
- Worker、CSP、编译能力白名单与资源限制不是不可信代码安全沙箱。
- 这是 AST → JavaScript 后端，浏览器引擎决定优化与机器码生成，不是如自研机器码 JIT。
- 本地 Linux 单版本结果不等同 Windows／多 Python 平台 CI；Emacs ERT 未运行（本机缺少 Emacs）。本次未更改 VSCode，不重发扩展版本。
- 没有真实付费模型请求；生成路径只用本地模拟提供方验证。

## 更新使用

关闭旧如书 Python 服务后重新启动，再刷新浏览器。仅刷新页面不会更换已加载的服务端编译器。可打开 `rushu/examples/solar-system-browser-js.rushu.json`，该书明确选择 JS 执行并请求 60 FPS；这是上限，不是任意设备上的性能保证。
