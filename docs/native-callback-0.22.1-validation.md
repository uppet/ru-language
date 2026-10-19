# Native 同步回调瞬时根索引：0.22.1 wip 验证

本批是 Windows x64 C 原生后端内部性能修复，不改变语言语义、0.22.0 包合同、锁格式、DLL ABI 或显式启用边界。如书保持 0.8.8；`main` 稳定版仍为 0.22.0。本报告不把 POSIX 测试适配器当 Windows ABI 或完整应用验收。

## 冻结输入与实现

- 公开基线：`95ee638f705f0fd75292da7eda150559dbe8fc3a`，树 `f4c871d89e26c8eef03fd901f8f9aa0ad4d7e354`。
- 生产实现：`6df416d7547bdc294a70f9a2a48c635c7507e25d`。后续提交只增加回归、版本与文档；完整门禁输入为 `b5a54e0c0dd382d43803ba71be2bc3e6d85129b8`，树 `67a66fc0ab04590d8680f2aaea38960b862d73d5`。
- `rulang/native_c_runtime.py` SHA-256：`88fe0b6c99a3a5fee6b543c3cad68d86768716d7803eff09824c7f68a61d0bd3`。
- `rulang/native_runtime.h` SHA-256：`83ef25f69dd33682fa0bc20e33da575500c134d673cb977eb8ed5226f92e0309`。

仅维护瞬时根非零 heap 的双向链，替换入口的两次全堆枚举。每个回调仍分配自己的快照并排序；失败仍完整遍历 heap、使用原 bsearch 恢复根、清全部 mark，并在该遍历中重建链。没有快照缓存、全局根数量、排序后移或改变 GC 根集合。设计与全部写点见[设计记录](native-transient-roots-design.md)。

## 回归与独立复核

新增 10 项 `test_native_transient_roots` 回归先红后绿，完整堆扫描作为独立不变量 oracle，覆盖零／非零转换、永久根、managed env、头中尾删除、GC、正常及 fatal shutdown、空／嵌套／重复快照、永久根修改、新生和销毁对象、卒与普通错误、两处快照 OOM、实际转文本 OOM 后先于 GC 重试。固定 1 个瞬时根时，heap 从 10 增至 4106，两次枚举的访问总数仍为 2。

专项普通运行 10／10 通过，ASan＋UBSan 10／10 通过；6 组直接 C 场景原新返回码、stdout、完整 stderr 一致。既有 10 项 owned-fixture 如程序原新返回码、stdout、原始 stderr（含 GC 统计）也逐字一致。

独立只读复核无未关闭实现问题：96,000 次确定性随机操作、137,811 次全堆不变量核对、18,568 个快照、14,768 次恢复、8,414 次 GC，原新语义输出相同。17 次真实分配失败中 10 次留下 graph-only mark=2，全部在恢复后、下一次 GC 前正常转文本。另验嵌套 longjmp、永久根变化、失败钩子、活动关闭、错误线程先拒、331 次普通分配器地址复用，以及 10 项 full／pruned 语言程序逐操作 oracle。原新独立 probe 与正常 shutdown 均通过 ASan＋UBSan。

本机 LeakSanitizer 因 ptrace 环境限制不能运行；ASan／UBSan 的本地命令显式使用 `detect_leaks=0`。这不是泄漏检测通过；没有修改正式 CI 或测试默认设置以禁用 LSan。

## 完整门禁

冻结输入的完整 Python／C／JS 回归 1702 项：1656 通过、46 项真实 Windows 平台限定测试跳过；新增 10 项全部实际通过。Node 342 项：329 通过、13 项显式可选浏览器测试跳过，无失败。32 个 C 与 32 个 JS 示例构建、包示例三端逐字输出、compileall、四份完整提示词实导出全部通过。

首轮 `6aa2661` 的 1702 项仅稳定入口的开发版本说明断言失败，1655 通过、46 跳过；已补齐 0.22.1 wip 与 main 0.22.0 的区分，保留原测试和红日志。上面的结果来自修订后的整套重跑，不把首轮计为绿色。

规范 SHA-256 为 `9efa400296cd40c5159fab13d5efccacf97c077c9c1dd07b3cfc5deeb3cdd92a`。四份导出均标明语言／规范 0.22.1，且各自只嵌入一次逐字相同的完整规范：

| 导出 | SHA-256 |
| --- | --- |
| rushu／Python | `745892189e6cf3987478afd41795215d1aabc9640ce9e38167e88fbbe8931416` |
| rushu／browser-js | `1e29d104fdaa935a8939c8c3b6abea76852a78ae7eca9f88fbafa6d8bc2e5611` |
| ruguan／Python | `896069febb884278fce0491edac9e127d262200c32d429b6f92c2067f7d435d5` |
| ruguan／browser-js | `fd38c7ef39bb849ecf3ff6bac4c71baffef36fab292f21b9b9a4f8f0cadb258a` |

本地宿主为 Linux x86-64、Python 3.12.14、GCC 14.2.0；Emacs 未安装。真实 Windows、Emacs CI 与完整应用原新对照仍待验，不能由本地结果代替。

## 普通 C 与配套影响

- 30 个普通示例 × full／pruned：同版本的公开基线与生产实现输出 60 份 C 全部逐字一致。最终 0.22.1 的 60 份 C 唯一差异是首行版本 banner `0.22.0` → `0.22.1`，其余字节完全一致；源码诊断路径通过已有 prefix-map 参数统一，没有事后改写 C。
- 普通 `runtime.h` 未改。仅启用 native runtime 才增加链字段与维护逻辑；普通 C 无此内存或执行开销。
- 完整规范只有版本标头／适用实现标识变更，无规则变化。两个提示词入口各自的 Python／browser-js 四份导出都使用新版本与同一完整规范摘要。
- 如书保持 0.8.8，版本说明随核心更新，编辑器执行与语法能力不变。Emacs 和独立 VS Code 扩展无需新 token、hover、解析或权限行为；本批没有扩展代码／发布或应用 compiler pin 变更。

## 成本与 host 机制测量

独立静默测量窗口中，238 次最终执行全部成功，原新结果、错误与 GC 计数相同，最终 `live=0`。使用自有 POSIX fixture、同一输入和交替原新顺序；计数插桩与计时控制分别编译，pilot 不计入结果。

快照始终只有 5 个瞬时根。增加 10,000 个 graph-only heap 时，host no-forward／forward 中位数分别改善 20.55×／8.87×；增加同量 permanent-only heap 时分别为 15.65×／7.10×。新版两次枚举总访问恒为 10，旧版随全部 heap 数量增长。这证明枚举机制，不预测 GUI 实际收益。

代价没有省略：x64 实测 `sizeof(RuHeap)` 从 32 到 48 字节，每个 native heap +16 字节，10,000 个增加 160,000 字节头部 payload，未计分配器 rounding。无回调原生微基准五次交替测量中，newheap/drop 中位数 +3.3%，managed env new/free +7.3%；copy/drop 与 pin/unpin 的抖动区间重叠，不能宣称零维护开销。

同源码生成 native C 增加 1,627 字节；未插桩 host ELF 从 296,488 到 292,432 字节，差异伴随 GCC 内联变化，不是另一个平台的体积承诺。PE 尚未测量。完整应用仍须相同图／fixture 的两路由 × 两 compiler × 两次真实 Windows 对照，以及原有产品门禁。
