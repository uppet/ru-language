# 如的文档导航

第一次来，沿着这条路走就好：

**[首页的小程序](../README.md) → [打开如书](stable-entry.md#取得同一套工具链) → [入门小路](first-steps.md) → 选一个小作品。**

本目录随所在分支更新，当前 `main` 对应如 0.20.0。使用接口前先核对[版本与执行目标](stable-entry.md)；`wip` 正在开发如／规范 0.21.7；本目录中的 C 原生新增接口不能用于 0.20.0 稳定版。

## 学习与小作品

- [入门小路](first-steps.md)：显示、赋值、循环、判断、函数和阵
- [七个离线小练习](getting-started.md)：调用、作用域、共享状态与保存
- [如书使用说明](../rushu/README.md)：代码格、输入、保存、重启和书本历史
- [文本、数学与随机](practical-libraries.md)：从整理名单到可复现的骰子
- [如观](ruguan-guide.md)：先画柱状图，再试动画、鼠标和键盘
- [如竞](contest-library.md)：四道完整练习，以及生成 C 的提交流程
- [源码例子](../examples/) · [如书示例](../rushu/examples/)

## 写到哪里，查到哪里

- [调用与作用域速查](calls-and-scope.md)：括号、参数和名字的可见范围
- [语言用法参考](language-guide.md)：语句、集合、闭包、对象、模块、文件与错误恢复
- [阵的排序、另成和遍历](array-sort-map.md)
- [显式作用域块](scoped-blocks.md)
- [完整语言规范](../rulang/language-spec.md)：当前实现的权威契约
- [错误位置与诊断](diagnostics.md)

## 工具与进阶

- [安装、安全更新与环境](stable-entry.md)
- [命令行、REPL 与独立程序](command-line.md)
- [Emacs 编辑支持](../emacs/README.md) · [如言 VS Code 扩展](https://github.com/uppet/ru-vscode)
- [浏览器 JS 执行](browser-js.md)：与默认 Python 会话的区别和保护边界
- [如是我言](generation.md)：可选生成、凭据配置、审阅与输出保护
- [生成诊断](generation-diagnostics.md) · [离线提示词导出](prompt-export.md)
- [原生库与随附如见](native-library.md)：Windows x64 Python，以及自 0.21.0 引入的独立 C 目标；先读权限、静态签名与生命周期边界

## 更新旧程序

先备份自己的源码和书本，再按需要阅读：

- [全量导入连写迁移](import-all-migration.md)：如 0.20.0 的 `尽取 外言`
- [标准模块导入名](standard-module-imports-migration.md)：`如:观` 与 `如:竞`
- [事实与典](maps-facts-migration.md)：真值、目与相、成员调用
- [阵与典遍历](array-sort-map.md)：`逐位` 与 `逐目`
- [变更记录](../CHANGELOG.md)：其余版本差异

## 实现与验证

- [开发、构建与同步清单](development.md)
- [已知问题与设计审查](language-review-tracker.md)
- [实际验证记录](../VALIDATION.md)：历史实测与平台范围
- [0.18.1 稳定化验证](stabilization-generation-validation.md)（历史记录）
- 分项记录：[如观 0.19.8 验证](ruguan-0.19.8-validation.md) · [原生库 0.20.0 验证](native-0.20.0-validation.md)
- [第三方算法与许可说明](third-party-notices.md)

[返回首页](../README.md)
