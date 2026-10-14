# 透明度小批验证：Ru 0.19.1／如书 0.8.1

日期：2026-10-14。基线提交 `8b6dc11358bdeba55d1bf0d615a33371df30a30d`，树 `94e4128b827f0cc954438c101e85211cd096a209`。本批生产代码、示例和测试冻结为 `fcd476f045cbf07c0eca3c763fa83096e5a8e761`，树 `a43a96321c264415423fa037c4a27134c1d6354b`。本报告是冻结验证后的文档补充，不改变生产代码。

## 本批范围

- 保持六位 `#RRGGBB` 的不透明颜色，新增八位 `#RRGGBBAA`。`AA` 是不透明度：`00` 全透明，`ff` 不透明。
- `观 其 颜色 红 绿 蓝 不透明度` 四个必需参数均为 0～255 有限整数，返回小写八位色值；支持普通位置／命名调用及函数引用。拒绝小数、越界、事实、空、非有限数和错误参数，不钳位、不舍入。
- Python、browser-js、Python IPC、主线程 scene 与静态历史都按严格完整 ASCII 六／八位色值校验；填色、描边的 `空` 继续有效。零不透明度仍保留为颜色命令并计入资源预算。
- 背景先清除整幅画布为透明，再绘背景色；历史中的中途／多个背景也必须替换此前像素。背景忽略矩阵／裁剪，保留绘制状态。每帧完整重绘，没有上一帧像素累积或半透明背景拖尾。
- 权威规范、两个提示词入口、指南、版本、如书／Emacs 上下文提示、同源透明叠色示例同步。文字排版、时间、渐变、混合模式、HSB 不属于本批。

## 冻结后的完整回归

环境：Python 3.12.14、Node.js 24.19.0、GCC 14.2.0，Linux。

- 全量 unittest 发现 1098 项，四个不重叠分片为 275／275／274／274 项；1094 项通过，4 项 Windows 控制台专属测试在 Linux 跳过，无失败。集合 SHA-256：`139bf13993c64afbe4a066ac4e3090c3f9d8f9d33572bc5f802efe8037855e72`。覆盖 Python、原生 C、Node.js、browser-js、内核和 HTTP 集成。
- 如书 Node 全套 240 项：232 通过、8 项显式可选真实浏览器测试跳过，无失败。跳过项不计作通过；新增四项的真实 Chrome 执行方式见下节。
- `make examples examples-js` 完成全部 C／JavaScript 示例构建与 Node 语法检查。
- `python3 -m compileall -q rulang rushu`、`git diff --check` 通过。当前如与规范版本 0.19.1，如书版本 0.8.1。
- 新增自动回归包含全部 256 个字节值、逐通道非法值、精确参数绑定、所有图元的透明／空样式、保存恢复、背景替换、连续回调、严格色值及真实 spawn 的 IPC 路径。示例 Python 与 browser-js 的一帧 75 个命令逐字段一致。
- 独立只读审查另执行 628 组断言（不是 628 个 unittest）：132 组随机／边界 RGBA 双后端对照、非法通道与参数、四帧快照一致性、IPC 拒绝时保留原 metadata、24 类不安全颜色的所有槽位、历史冻结、零不透明度预算、清除／填色顺序和异常恢复。最终冻结的五个产品文件与审查时 SHA-256 一致，未发现阻断问题。

## 真实 Chrome 验收

针对同一冻结提交，在实际云 Chrome 中完成：

- 独立像素／历史 JSON 检查 31／31 通过。
- Python 与 browser-js 真实如书 UI 的构色器精确输出及保存的 scene 在去掉随机画布身份后相同。
- 保存／恢复与裁剪组合、透明／半透明背景替换、连续四帧无拖尾、新增透明叠色示例通过。
- 14 次非法值错误均未发布部分画布；后续合法代码格能恢复。
- 从 `rushu/tests/scene-browser.test.mjs` 原样提取四个新增 alpha 测试的浏览器回调及预期断言，在真实 Chrome 按钮页执行，4／4 通过：透明／不透明／source-over 像素、连续帧不累积、中途／多个历史背景替换、椭圆／多边形／描边／文字透明度与空样式。

原 Node opt-in runner 的 Chromium 启动受到当前执行环境的 `socket() EPERM` 限制，未完成该 runner；不能把 Node 统计中的 8 个跳过项改记通过。其余四个既有 input／lifecycle opt-in 用例未在本批逐一原样重跑；上述真实 UI 流程与新增 alpha 的原样断言分别记录，避免混淆覆盖范围。

## 四种完整提示词导出

实际运行 `rushu-prompt`／`ruguan-prompt`，各选 `--target python`／`--target browser-js`。四种 CLI 输出逐字等于提示词构建器，并逐字包含唯一完整规范与实际 SHA-256；未调用真实模型。

权威规范 UTF-8 为 141445 字节，SHA-256：`91f9999f3f2cc2d2b4974d8c33e7fcd900c06c3d32322712d8f54cd2a7cf536a`。

| 导出 | 字节数 | SHA-256 |
| --- | ---: | --- |
| rushu／python | 143633 | `36c7420757805f82ae46eacfbea937af06dac0e2d0c41c3ed848360360757b0c` |
| rushu／browser-js | 143754 | `c820177ceb12d5c0136b267fa58710a98b51fac9a8e1eced8a02f9d27834cd69` |
| ruguan／python | 144282 | `eb1f6696670d7e70814815c4c68cce6451ac1eace5869367aa8ec89382d343f9` |
| ruguan／browser-js | 144403 | `69e176613038e8fa156a2f547e32568689bf4c7f3d3f91aa0e01039878059073` |

## 边界与未覆盖项

- 未在本地运行 Windows 控制台或 Windows GUI；未安装 Emacs，新增 ERT 与严格字节编译等待相应环境验证。真实浏览器覆盖限于本次 Linux Chrome。
- 未调用真实付费 LLM；生成相关测试只用本地模拟提供方，不代表模型生成质量评估。
- 原有资源和主线程校验保留，图形保护不构成不可信代码安全沙箱。
- C／Node.js 编译目标仍拒绝如观模块；普通 Python CLI 可纯构色，但不能创建画布。
- VS Code 0.8.0 的字符串及普通成员语法可继续使用；其新成员工具提示与颜色说明安排和后续文字／时间小批合并更新，本批未重发 VSIX。
- 本报告只记本地冻结树；远端发布与 CI 须检查对应精确远端提交，不据此声明已通过。

复验入口：`tools/run_test_shard.py --shard 0..3 --count 4`（分别运行四次）、`node --test rushu/tests/*.mjs`、`make examples examples-js`。示例见 [透明叠色如书](../rushu/examples/alpha-colors.rushu.json) 与 [同源程序](../rushu/examples/ruguan/alpha-colors.ru)，契约见 [如观指南](ruguan-guide.md)。
