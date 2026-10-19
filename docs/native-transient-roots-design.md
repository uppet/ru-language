# Native 同步回调的瞬时根索引

## 范围与成本（2026-10-19，先于实现）

基线为公开 `95ee638f705f0fd75292da7eda150559dbe8fc3a`、树 `f4c871d89e26c8eef03fd901f8f9aa0ad4d7e354`。本批仅优化已显式启用 Windows x64 native 的 C 运行时；包语法、解释器、JavaScript、普通 C 运行时和应用 compiler pin 不变；后续 0.22.1 版本更新只改变普通 C 的生成标头版本号。

已有独立 POSIX owned-fixture 机制实验的 81 次样本表明：约 10673 个 heap、5 个瞬时根、六参数转发回调时，两次全堆入口扫描约 40.98 µs，而排序约 0.11 µs。该实验不是 Windows ABI 或完整编辑器性能验收。实际应用仍需相同 PE 路径／fixture 的前后测量；不把微基准收益换算成应用完成时间。

最小方案保留原快照排序和错误恢复，仅用瞬时根索引替代入口的两次全堆枚举。两个侵入式指针预计令 x64 native `RuHeap` 从 32 字节增至 48 字节，即每个 heap 增加 16 字节（10673 个约 167 KiB，尚不计 allocator rounding）；须用实际编译布局验证。所有 native-enabled heap 承担此代价，因此另测没有回调的普通根操作开销。没有新全局根数量或跨回调快照缓存。

## 不变量和修改点

- 总根数 R、永久根数 P；正常状态 `R >= P`，链恰好包含 `R > P` 的已分配 heap，且每个只出现一次。未入链节点的两个链接都为空。
- `rn_transient_link`／`rn_transient_unlink` 只改指针，不分配、不调用 Ru、不收集、不触发回调或失败。
- `v_copy`／`v_drop` 仅在瞬时根零与非零间转换时更新链；保留已有溢出／下溢诊断。
- `v_pin`／`v_unpin` 成对变更总根和永久根，使瞬时数及链成员身份不变，不经过会产生假转换的 copy／drop 中间状态。
- `ru_new_heap` 完整初始化并发布后、返回前入链；managed `env_free` 的直接减根同样处理。static/module Env 并非 heap，不入链。
- 中央 `ru_heap_dispose` 在释放前脱链，兼顾 GC 与最后 shutdown 仍有根的对象。fatal 全堆 roots=0 时清链及节点链接，不能只清 head 遗留 backlinks。
- 仅在 `native_c_runtime.py` 的严格集成锚点注入基础运行时变更，普通 `runtime.h` 不改；全量与裁剪 native 输出都要验。

## 回调快照与恢复

每次 `rn_trap_new` 都独立分配快照。第一遍遍历 `ru_transient_roots` 计数，第二遍复制 heap 指针与 `R-P`，仍使用原 `qsort`、原 raw calloc/malloc 失败返回及 dispatcher 清理。不得改为可能跳入外层 trap 的 `ru_alloc`。索引只缩小枚举范围，不给快照额外持根；入口外层帧的瞬时根仍是存活依据。

错误恢复仍先 `ru_panic_clear`，然后遍历全部 heap，通过原 `bsearch` 恢复“当前永久根 + 入口瞬时根”，并清每个 heap 的 mark；同一次遍历清链接并重建索引。保留 scratch、调用深度、source、LastError、嵌套 trap、活动关闭和失败钩子的既有顺序。恢复过程中不得增加分配／GC／新的失败点。

mark 还用于转文本的循环探测，OOM/longjmp 可留下 graph-only 容器的 mark=2；只清索引节点会造成下一次 GC 前误报循环。因此错误路径仍保留全堆清 mark，GC 仍从全部非零总根与完整图边开始，不能改用此瞬时索引代替 GC root source。

## 分阶段验收

1. 先加红回归：完整 heap 扫描作独立链不变量 oracle；membership 转换、pin/unpin、managed env、头中尾删除、GC/dispose/fatal；实际布局；固定 R 增加 graph-only／permanent-only heap 时入口访问数不增。
2. 语义差分：旧基线与新候选同程序、同输入、同 GC 阈值，对比返回／输出／错误及最终 live=0；覆盖成功、卒、普通错误、嵌套 longjmp、永久根变化、新生／销毁对象、重复 restore、活动关闭、失败钩子、graph-only mark 清零及 OOM fallback。
3. 在 owned POSIX fixture 下运行地址／未定义行为 sanitizer；明确 LeakSanitizer 的可用性，不把 fixture 当 Windows ABI 验收。验证 full/pruned、无回调 native 和普通 C 逐字不变。
4. 完整语言、包、Node、示例与提示词回归；独立审查所有计数写点和最终文件摘要。最终由统一 publisher 发布 wip，验真实 Windows/Emacs CI 后，应用才能切换受验 compiler pin 并做同图 2 路由 × 2 compiler × 2 次实际对照。
