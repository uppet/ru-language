# 真实 NativeMemory 同步只读借用：本地内部原型

## 已做到什么

这个增量把 `mi_kernel` 的固定只读字节扫描器接到已有 NativeMemory / RuNative owner graph，而不是原实验的独立 MiOwner。读取叶子 view 的相对范围，复用 `_retain` / `rn_owners` 快照，使父/根缓冲、字段 pins 和描述符保持存活；借用锁记在根上，因此父、子、同根其他 view 不能关闭或写入。嵌套同步只读借用允许，计数逐层恢复。

内部调用接口：Python `scan(memory, offset, length, seed=0, *, context)`；C `rn_mi_scan(Val memory, int64_t offset, int64_t length, int64_t seed, int line)`。结果仍是数行界，不是 Markdown 解析器。C直接调用此前由限制IR生成的 `mi_kernel`，不通过 MiOwner、不建另一套FFI。

**无新公开语法、无公开密成员、无编译器自动 lowering。** C桥由测试在真实编译器生成的完整 native runtime 后包含；它是可供后续 lowering 使用的内部集成能力，不是已发布语言功能。只在已授权 native runtime 中存在；不改变 `--allow-native`、平台拒绝或16MiB上限。

## 生命周期及错误合同

1. 所属线程/能力（Python）和重入检查；确认真实拥有型内存、未关闭、u32范围及view内边界。
2. 构建现有 owner 快照；所有可能分配、`ru_fail` 的操作放在增加计数之前。
3. 根计数及运行时active计数增加，形成私有同步只读借用。
4. C只运行固定纯 `mi_kernel`：无分配、GC、回调、任意FFI、`ru_fail` 或longjmp；只返回status。Python是分配行为不同的参考实现，用finally保证异常释放；私有token严格LIFO，获取前预存旧计数对象，释放直接恢复旧对象，不做整数运算分配。错误顺序或重复释放在改动计数前拒绝。这不是任意异步异常或恶意宿主对象下的原子事务保证；仅限可信固定同步scan协议。
5. 先减少计数及释放快照，再把status转普通错误或结果。范围失败不借用；内核溢出不残留借用。空view允许在末端，C不会对NULL做指针算术。

`rn_trap_restore`只恢复临时roots、scratch和调用深度，不会恢复借用计数。此原型**没有修改trap unwind，也不支持借用中回调/longjmp**；明确拒绝从已有native调用/回调重入借用入口。测试使用的私有acquire/release只用于观察生命周期，不能作为任意用户代码around-hook。测试trap在借用之外建立/捕获被拒绝操作，绝不是支持任意内核longjmp的证据。以后允许回调必须先设计带所有权的unwind记录，不能只在正常返回处减计数。

## 所有写入口核对及受信任边界

| 当前路径 | 处理 |
|---|---|
| C `rn_memory_write` 标量 `rn_store`、结构 `memmove`及pin替换 | 在写前检查根借用计数 |
| Python NativeMemory `写`：标量setattr、结构复制及pins替换 | 在写前检查根借用计数 |
| 任意同根NativeMemory `关闭` | 在closed/pins改变前拒绝 |
| UTF8/UTF16构造、rn_memory零初始化 | 只写新分配对象，不是已借用alias |
| 读U32LE阵、解码、字段读取 | 只读；不新加写入口 |
| 旧任意原生调用，包括静态签名分派 | active借用存在时一律拒绝未知effect；无借用时保持原行为 |

写入验证优先级统一为：关闭检查 → 字段解析 → 借用冲突 → value转换/真正写入。无借用时保留公开入口原有校验语义。

静态链为 `RN_FUNCTION 调用 → rn_invoke → ru_native_generated_call → ru_native_call_N`，并非跳过检查的新快通道。旧callback失败hook同样经rn_invoke。

没有公开原生数组/批量写或任意外部指针解引用写方法。内部 `rn_store`/data和Python ctypes storage仍是受信任实现细节。**事先泄露的raw pointer、外部线程/异步DLL写、宿主直接ctypes/data写不受计数自动保护。** 本合同只适用于所属线程、同步、无外部并发修改的可信内核，不是完整alias分析、安全沙箱或并发内存模型。未知effect调用的全局保守拒绝有意比仅检查参数同根更严格，因为外部代码可能已缓存地址。

## 测试及运行

```sh
python experiments/mi_borrow/test_bridge.py
MI_UBSAN=1 python experiments/mi_borrow/test_bridge.py  # Linux GCC
PYTHONPATH=.:tests python -m unittest test_native_c_runtime test_native_anchors test_native_c_plan test_native_memory_batch test_native_transient_roots
```

覆盖真实三层结构、非零root偏移nested view、移除其他引用强制GC、根/parent/view close、标量/结构写冲突、未知effect拒绝、只读嵌套、范围/溢出后恢复、关闭后拒绝、无借用正常写及view局部关闭、Python快照失败/内核异常cleanup、原生/回调重入和Python能力拒绝。C运行检查最终 `RU_GC live=0`；保活观察用真实ru_gc，不是独立模拟owner。

Linux使用仓库已有POSIX test platform adapter，仅替换平台/DLL部分，不替换真实owner、GC、trap和native runtime。**不能据此宣称Windows DLL ABI验证。** 测试有Windows原平台分支；本地仅执行Linux，Windows CI待结果。实验workflow分别运行Windows原平台和Linux测试适配器，Linux额外运行UBSan。固定密核不调用外部DLL，unknownFFI只测拒绝路径；即使Windows探针通过，也不代表本探针验证了外部DLL ABI。

## JS映射（设计，未实现）

纯compute JS用拥有型TypedArray包装 + root对象 + `{root, byteOffset, byteLength}`嵌套view，同步readonly计数和try/finally；所有受控写/close检查root。禁止泄漏可写原始TypedArray/ArrayBuffer alias、SharedArrayBuffer及detach/transfer，否则只能复制或拒绝。JS的owner只是对象引用保活，不是C地址、FFI指针、C结构ABI或真实NativeMemory支持。语义可一致，存储布局和GC不能伪装相同。

## 明确未完成

公开密语法/源码入口、共享typed IR lowering、密形/密阵和可变输出、全文Markdown扫描、24槽状态/外部array alias身份合同、跨chunk CRLF/UTF8状态、性能端到端收益、callback/longjmp unwind、异步/长期borrow均不在此增量。后续Markdown替换必须保留现有普通如言oracle和24-state alias契约；不能把这里的计数器标成编辑器瓶颈已解决。
