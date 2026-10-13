# 标准模块导入名统一验证（2026-10-13）

版本：如 0.17.0、如书 0.5.0；配套 VS Code 扩展 0.6.0。

## 变更边界

- 导入名为 `如:观`、`如:竞`；如观、如竞仍是产品名称。
- 精确旧名 `如观`、`如竞`、`如:竞赛` 报明确迁移错误，不作别名，不回退读取本地同名文件。显式相对路径仍遵循原有本地模块规则。
- 规范、提示词导出、现行示例、仓库书本与新建模板、编辑器片段同步；用户已有文件和保存的书本不自动改写。
- 保留导出 API、宿主要求、状态隔离、保护预算与执行语义。VS Code 运行当前文件仍使用普通 CLI，不新增画布宿主。

## 本地验证

环境：Linux、Python 3.12.14、Node.js 24.19.0、GCC 14.2.0。

- `make test`：完整 Python 回归 961 项，957 通过，4 项真实 Windows 控制台测试按平台跳过，0 失败（530.210 秒）。
- `node --test rushu/tests/*.mjs`：160 项，156 通过，4 项需显式真实浏览器开关的测试默认跳过；随后以 `RUN_RUSHU_BROWSER_TESTS=1` 在真实 Chromium 中补跑，4/4 通过、0 跳过。
- `make examples`：29 个 C 目标示例构建通过。
- `make examples-js`：29 个 Node.js 目标示例构建和语法检查通过。
- VS Code `npm run check`：lint、50 项测试与 0.6.0 VSIX 打包通过；`npm run test:ru` 的 34 个真实如片段通过。
- 独立只读复核：Python、C 完整／裁剪、Node.js 完整／裁剪、browser-js ESM 的相同行为输出一致；标准模块缓存身份、9 条旧名错误路径及 7 条浏览器拒绝路径通过。归一化源码绝对路径后，C／JS 产物大小与改名前一致。
- 独立定向回归：模块名、当前示例与提示词共 27 项通过；生成请求使用本机 mock，没有请求付费模型。
- VSIX 包内版本、编译后 hover、新名 snippets 已检查，未包含依赖目录、旧验证记录或凭据文件。

## 真实浏览器验收

- 独立 Chromium 迁移验收 13/13 通过：新模板和画布、browser-js 太阳系保存／加载、两个后端的三种旧名诊断，以及实际生成请求的 system 提示。
- `start-templates-browser.cjs` 的 10 大项通过，0 page errors；针对已有双操作栏，将测试的运行按钮 locator 明确限定在顶部操作栏。
- `generation-animation-browser.cjs` 通过；仅使用本机 mock 模型服务。
- 两个执行后端针对三种旧名的文件读取／网络 `connect`／`urlopen` 硬失败探针 6/6 通过。

## 覆盖限制

本机未安装 Emacs，未运行 ERT／字节编译。真实 VS Code extension-host 测试已尝试，但缺少 X server／DISPLAY，未运行成功；模拟 API／TextMate／真实 CLI 测试不冒充真实扩展宿主验收。未在本机重建 Windows 和 Python 3.10／3.14 矩阵。未重跑远端 CI、修改 workflow 或更改账单设置。
