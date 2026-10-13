# 如 0.18.2／如书 0.7.1 生成预算与未完成诊断验证

日期：2026-10-13。开发基线为 `27ee488`（如 0.18.1／如书 0.7.0）。本批属于 `wip` 开发；此记录描述本地验收，不表示已发布到 `main`。

## 变更范围

- 默认省略请求中的 `max_output_tokens`，不再固定为 16,384；省略表示使用提供方／模型默认值，具体限制可能未知，不表示无限。
- 1 至 2147483647 的整数预算支持 JSON 的两种拼法、环境变量及 CLI／如书启动参数（文本入口仅接受最多 10 位 ASCII 十进制数字），优先级为 CLI／启动参数 > 环境变量 > JSON > 省略。超时秒数独立。
- CLI `--verbose` 与如书 trace 显示请求预算、提供方返回的数值用量（含返回时的 reasoning 用量）、输出项类型摘要以及没有可见助手文本的情况；缺失数据不编造为零。
- 未完成响应的预算耗尽、内容过滤与未知原因分别诊断，不笼统归因于权限或额度。已返回的可见部分文本仅保留为诊断，不作为完整源码保存、写入模型版本或执行。
- 不记录隐藏推理正文，不自动重试，不改变现有书本持久化与语言执行语义。

## 最终检查状态

本次实现完成后，使用本地假令牌与模拟 Responses 服务检查以下范围：

- [x] 默认请求省略预算；CLI／启动参数、环境变量、JSON 的覆盖顺序及正整数校验。
- [x] `incomplete` 预算耗尽、内容过滤、未知原因、reasoning-only 与部分助手文本的模拟 Responses 回归。
- [x] CLI stderr／stdout 分离、失败不生成或覆盖产物、不运行与不自动重试。
- [x] 如书预算贯通、无可见助手文本说明、trace 用量／类型摘要、部分文本不污染草稿／历史。
- [x] 诊断字段的数值筛选、有界输出与凭据脱敏，不包含隐藏推理正文。
- [x] 包版本、完整规范注入、文档链接、全量 Python／Node 回归及最终 `git diff --check`。

## 检查命令与结果

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest test_generation_budget -v`：新增 40 项通过，包含如书与提供方双回环 HTTP 的 reasoning-only 未完成响应及 CLI 端到端测试。
- `python3 -m unittest discover -s tests -p 'test_generation*.py'`：独立复审运行 166 项通过；额外 82 项攻击性断言、7 项预算配置失败探针及数字／枚举形状假密钥脱敏检查通过。
- `node --test rushu/tests/*.mjs`：223 项中 219 项通过，4 项需真实 Chromium／Playwright 的可选浏览器测试跳过，0 失败。新增 trace 摘要阶段保留与隐藏字段剔除测试。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`：1053 项，0 失败，4 项 Windows 控制台专属测试在 Linux 跳过；耗时 603.642 秒。
- `git diff --check`：通过。

## 验证限制

本批不使用真实提供方凭据，不进行真实付费模型验证。模拟协议测试不证明真实端点、账号权限、模型支持范围或省略预算时的服务端默认值。本批未进行真实浏览器视觉检查，未在 Windows／macOS 执行，也未运行发布后的远端 CI；不沿用前一版本的通过记录。
