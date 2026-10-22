# 密模式在 bs 的 LLVM 适配（实验）

本地从 `origin/mi-perf-prototype` 的 `d78a29d51844acf23ee0a49129d0211c006ac737` 复制原型，适配基线为已推送的 `bs@e8ce196543ef16c81e06adf1f0ae6aa98dfd2db5`。原始 v1 固定扫描器、v2 源码清单及真实 owner 借用实验均保留；版本来源见 [adaptation.json](../experiments/mi_source/adaptation.json)。本改动没有合入 wip/main，没有增加公开关键字。

后续 [ru_notepad 双撤销实验](notepad-mi-undo-2026-10-22.md)增加 `borrow_ro_utf8` 不可变句输入和 C 调用方＋直接 LLVM 密核的构建 API，允许安全的同步回调消费者。下文原 NativeMemory 桥及先前验证保持其快照含义；新候选的校验值和边界另记在该报告。

显式清单选择模块内唯一顶层算，沿用现有如言源码，经 AST、精确整数类型／效果检查、通用密 IR，直接生成 LLVM 14 IR。密函数使用机器整数，检查加减溢出和字节索引边界；没有普通 Val 运算、装箱、GC、分配或外部调用。LLVM 的 O2 管线负责后续优化，没有按函数名识别算法或替换成手写 C 热点。

## 使用

WSL/Linux 和 Windows x64 均可运行标量示例，需要本项目的 LLVM 14：

```sh
python3 ru build experiments/mi_source/scalar.ru --target llvm --experimental-mi-manifest experiments/mi_source/scalar-manifest.json -o bin/mi-scalar.exe --emit-llvm dist/mi-scalar.ll
```

运行 `bin/mi-scalar.exe`，输出 `10000`。未选择清单时，示例仍按普通如言数语义编译。清单参数严格匹配源码的名字及顺序；只接受有限、整数性和范围检查全部通过的普通数，随后才转换为 u8/u32，数值零仍为真。

Windows 的真实 NativeMemory 只读视图示例须额外授予原生权限：

```sh
python3 ru build experiments/mi_source/caller.ru --target llvm --allow-native --experimental-mi-manifest experiments/mi_source/manifest.json -o bin/mi-ascii.exe --emit-llvm dist/mi-ascii.ll
```

运行输出 `3`。示例的 UTF8 适配明确复制一次并附带 NUL；范围以字节计，不是句的码点索引。密内核借用已有 NativeMemory 数据区，不再次复制输入。C 目标仍可用同一清单，JS 只有独立计算语义模型。

Linux 的产品 CLI 拒绝 NativeMemory 桥；Linux 测试使用既有 POSIX owner 平台夹具，只验证状态／生命周期，不能当作 Linux DLL FFI 支持。Windows 测试执行真实 MSVC ABI 产物及生产 owner 实现。

## LLVM 边界与生命周期

内核私有 ABI 为 `void kernel(uint32_t *out, ...)`。只读视图展开为指针和 u32 长度，标量经 u32 传入，u8 在内核入口缩窄；结果写入四个 u32 槽：状态、值、行、列。LLVM 不依赖 Val／Env 布局或 C 聚合返回约定。C 只保留运行时、描述符、参数检查与 ABI／owner 适配，计算体直接发射为 LLVM。

普通调用先检查全部标量、线程／重入、内存状态和范围，再分配并保活完整 owner 快照，然后增加只读借用计数。内核以普通状态返回；桥在成功和失败时均先释放计数及快照，随后返回普通数或报告源位置错误。借用期间禁止同根关闭／受控写入及未知效果 FFI 调用。禁止内核回调、外部调用、视图写入／逃逸；不生成 noalias/restrict。错误沿用退出式 `ru_fail`，不是新加的可恢复异常。

## 尚未接入的部分

- `bootstrap/compiler.ru` 尚未实现清单读取、密类型检查和密 IR 发射；目前密编译的构建前端仍是 Python。三代自举回归通过只代表既有编译链保持正确，不能代表密编译已自举。
- 如书原生解释内核尚未提供调用预编译密模块的入口，代码格不会自动变成机器码；动态格编译／缓存／代码寿命没有实施。
- 现有清单子集为 u8/u32、最多一个同步只读字节视图、受检加减／比较／短路、有界循环、破、标量返回。仍要求末尾显式返回，静态密算互调、浮点／SIMD 语言接口及公开语法尚未实现。
- 这次 Windows LLVM opt-in 验证的是密算及 owner 桥，不是完整 DLL／如见／回调后端验收；默认 LLVM 构建仍拒绝原生导入。
- 本次没有新的消费者端到端性能测量，不能用此前手写特化探针的数据冒称本生成器的收益，也不宣称已对齐 Dart。

下一步应先把同一清单／类型／效果合同移植到如言前端，验证密程序和编译器的逐代一致性，再为如书增加有生命周期约束的预编译模块调用入口。

## 复验

```sh
python3 experiments/mi_kernel/generate.py
python3 experiments/mi_kernel/generate.py --manifest experiments/mi_source/manifest.json --entry experiments/mi_source/caller.ru
python3 -m unittest discover -s tests -p test_mi_llvm.py -v
python3 experiments/mi_source/test_source.py
python3 experiments/mi_borrow/test_bridge.py
python3 experiments/mi_kernel/test_kernel.py
python3 tools/bootstrap.py verify
```

新 LLVM 套件复用源清单的普通 caller／GC／释放／错误合同，并覆盖三后端差分、全部 256 种字节、固定 seed 随机区间、u8 溢出、另若、嵌套循环／破／返回、默认无注入、权限及失败产物保护。冻结结果见 [本次验证记录](mi-llvm-2026-10-22/summary.json)。

2026-10-22 本地验收：Windows 新 LLVM 套件 22/22，WSL 21 通过、1 项 Windows 专测跳过；C/JS 源码套件两平台各 16/16，真实 owner 套件各 7/7，历史核套件各 6/6。三后端核对相同 857 组合法输入，LLVM 另测两组受检失败。普通 LLVM 各 30 通过、1 项平台／ASan 条件跳过；相关旧 FFI 分析／owner 回归通过，Windows 的一个既有 GCC 专测因缺 GCC 跳过。Linux 的 C 源码桥及 owner UBSan 均通过，未宣称 Windows ASan 或 LLVM 密核本体插桩。

两平台重新构建三代自举并各通过 105/105，全部八项门限为真，报告分别见 [Linux](mi-llvm-2026-10-22/bootstrap-linux.json)／[Windows](mi-llvm-2026-10-22/bootstrap-win32.json)。当前 [90 份输入校验值](mi-llvm-2026-10-22/source-checksums.json)均匹配；8 份生成文件经过 Windows 重新生成后字节一致。未选清单的普通平方样例，与 e8ce196 基线的 LLVM／运行时文本哈希相同。此次没有执行远端 CI，也未重复如书浏览器验收。
