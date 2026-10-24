# bootstrap LLVM：如言语法着色性能验收

日期：2026-10-24。范围是生成程序的运行时间，限于 `ru_notepad` 的六项语法着色指标；不是编译速度、Markdown Undo 或所有如言程序的性能结论。

**修复前历史记录：** 以下数字来自 `3eb27e0` 的本地测量。Review 确认汇总计算，但该版本在 Windows LLVM 回调失败恢复时缺少生成函数的 `uwtable`，普通 CI 崩溃；不能据此宣布产品验收通过。原提交也未包含完整 stdout/stderr 和构建证明。补齐展开属性后的结论须使用新构建、新测量；新的 `BS optimization review acceptance` 工作流保留预先固定的六对顺序、每次完整输出、失败/超时记录和构建证明，不沿用这里的胜出结论。

## 输入与比较方法

- 普通后端基线：`0b7adcb14f5039ea7ffa9892982877d0e83bc4bc`，已有槽复用和入口槽地址缓存。
- 原生适配层固定为 `6840d99e027221a2772e1b15d8c6be6b0a28a3f5`，应用固定为 `d964ea9f7e27065aa5bbcced8d6c7526a6224dd1`。主线自举前端尚未合入这个实验分支的 FFI 能力；复现脚本仅借用固定适配层，覆盖本次普通发射器、ABI、LLVM 运行时和工具链。没有将整个实验分支合入主线。
- 应用入口是原样的 `tests/ru_syntax_native.ru`。两边读取同一依赖图、调用同一组 Scintilla/Lexilla/RuSyntax DLL，未启用密模式特化，没有改应用、检查点算法或149项断言。
- 引导依次执行 Python→stage1、如言stage1→stage2、stage2→stage3，再由stage3处理应用源码并直接生成LLVM IR。宿主准备C运行时和描述符、调用LLVM；不代替如言前端解析应用。最终测量产物没有用探索阶段的IR替换脚本加工。
- C对照由同源生成C，再走相同LLVM14 bitcode/link/opt/llc流水线。双方均为O2，禁止fast-math和浮点收缩。
- Windows 11 26100，AMD Ryzen 7 7800X3D（8核16线程），Clang/LLVM 14.0.6，MSVC x64 ABI；构建驱动Python 3.14.8。Python不参与测试程序运行。
- 所有构建和回归进程退出后，六轮交替执行 C→bootstrap、bootstrap→C。每次启动新进程，无预热轮或删样本。整套时间包含进程启动、149项断言、GUI对象建立/销毁和输出；扫描子项使用应用内置计时。
- 每次必须退出0、通过149项断言。100KB/1MB初扫读量分别为100000/1000000字节，两个增量更新都重读32768字节；Unicode同步扫描为1000000字节、636370字符，保留默认修改通知。这不测完整窗口消息循环的输入延迟。

## 最终结果

六轮同机交替配对，**六项在每一轮均更快**。时间为各自六次中位数；快幅度按逐轮配对比值的中位数计算，范围保留所有轮次。

| 指标 | C→LLVM（ms） | bootstrap→LLVM（ms） | 快幅度 | 各轮快幅度范围 |
| --- | ---: | ---: | ---: | ---: |
| 100KB单行初扫 | 602.60 | 475.39 | 21.27% | 17.32%–23.20% |
| 100KB开头编辑 | 189.65 | 149.26 | 21.57% | 16.97%–23.62% |
| 1MB短行初扫 | 7890.01 | 6327.56 | 19.74% | 15.76%–20.47% |
| 1MB开头编辑 | 277.41 | 230.13 | 17.09% | 15.10%–18.44% |
| 1MB Unicode同步扫描 | 6011.38 | 5355.94 | 10.84% | 8.00%–11.80% |
| 整套149断言测试 | 24923.15 | 22041.68 | 11.56% | 8.12%–12.11% |

共12次程序执行，逐份stdout均有149条PASS，合计1788条断言通过。两个增量用例每次都重读32768字节。第四轮bootstrap整套耗时较其他轮高，仍领先8.12%；该轮原样保留。

最终PE大小：bootstrap 4,194,816字节，C→LLVM 6,422,016字节。程序运行不依赖Python。

数据：[逐轮原始记录](benchmarks/bootstrap-syntax-2026-10-24/raw.json)、[汇总与逐轮数组](benchmarks/bootstrap-syntax-2026-10-24/summary.json)、[400份输入哈希和工具链](benchmarks/bootstrap-syntax-2026-10-24/inputs.json)、[硬件](benchmarks/bootstrap-syntax-2026-10-24/machine.json)、[验证摘要](benchmarks/bootstrap-syntax-2026-10-24/validation.json)。这些是本次最终程序的新测量，未混入旧版或探索轮。

## 实现

1. **复用已有参数结果槽。** 所有实参仍按源序求值。单参数，或每个表达式恰好占一个连续槽时，直接使用原有已持根的结果；其余使用原复制路径。不提前释放、不借用无根值。
2. **按正常边界的实际槽数清理。** 普通语句边界清理已使用的前缀，避免每条简单语句扫描整个函数最大帧。异常转移继续清理全帧，且不重置仍影响父表达式的编译游标。持久解释内核的active-list帧也支持相同前缀语义。
3. **每次调用独立的局部绑定缓存。** 缓存函数根环境中的 `RuBinding*`，不缓存可变值；闭包修改后仍读取最新值。祖先命中不缓存，允许后续局部遮蔽；块/救环境不缓存。写入保留保留名称检查，并回退到原捕获更新规则。环境持根期间绑定不会移动或删除，缓存不跨调用存活。
4. **对齐LLVM函数目标属性。** 用选定Clang探测CPU、features和tune属性，给直接生成的函数补齐相同目标。LLVM14此前会因属性不兼容拒绝内联小运行时桥。没有从C复制浮点假设，也没有强制所有桥内联。机制参见 [LLVM14 InlineCost](https://github.com/llvm/llvm-project/blob/llvmorg-14.0.6/llvm/lib/Analysis/InlineCost.cpp) 和 [X86目标兼容判断](https://github.com/llvm/llvm-project/blob/llvmorg-14.0.6/llvm/lib/Target/X86/X86TargetTransformInfo.cpp)。

上述普通发射改动同时用于Python LLVM前端和如言自举前端。栈帧、固定字面量缓存、强制内联全部桥的探索方案均未保留。函数值表示、动态类型检查、共享环境、GC及原生回调协议保留。

## 正确性验证

- WSL与Windows各自重新构建三代：各105项同组回归全部通过，八项M4门限全部成立；自身IR/ABI精确固定点，Linux精确二进制固定点，Windows仅归一既定PE时间戳后固定点。
- WSL相关专项：119通过、3项Windows平台跳过。包括真实ASan/UBSan、两套前端GC阈值1下的闭包/递归/所有权、31项required槽复用检查及故意错误的异常游标负向对照、Mi共存、目标属性实际内联和解释宿主帧。
- Windows相关专项合并去重：93通过、1项因缺ASan运行库跳过。包括真实DLL嵌套回调、卒恢复与重试、回调前后来源/深度恢复、GC回收、两套前端缓存与参数所有权、31项required槽复用检查。
- Windows早期测试运行暴露了隔离工作树的工具发现与Git Bash头文件环境问题：C测试辅助程序未读取`RU_LLVM_CLANG`，显式C编译又收到POSIX形式的INCLUDE。设置测试进程的CC/PATH并清理该进程的POSIX头文件搜索变量后，原失败项及缺失执行项通过；失败日志保留，没有修改生产C后端来隐藏问题。
- 这是与本次编译器改动相关的回归集合，未据此声称全仓全部测试或远端CI通过。

## 复现

在Windows x64准备LLVM14，以及固定notepad版本所用的三份DLL。Git对象库需要含上列两个固定提交；脚本不联网、不修改两个输入仓库。输出目录必须不存在。

```powershell
python tools/benchmark_bootstrap_syntax.py prepare `
  --compiler-repository S:/bld/ru-toy `
  --notepad-repository S:/bld/ru-notepad `
  --dll-directory S:/bld/ru-notepad/dist/ru_notepad `
  --llvm-clang S:/bld/ru-toy/.build_tools/llvm-14/bin/clang.exe `
  --output S:/bld/syntax-comparison

# 等其他构建/测试任务结束，保留默认GC设置，再测量。
python tools/benchmark_bootstrap_syntax.py measure --output S:/bld/syntax-comparison
```

`prepare`保存三代产物、前端IR、独立优化IR、描述符、构建proof及400份输入哈希。`measure`先核对这些哈希，保存每个进程stdout/stderr、逐轮原始JSON及汇总；任何断言、读量、输入哈希或逐轮性能门限失败都会报错，不覆盖已有测量目录。

本次本地产物位于主仓库 `.git/bs-local/codegen-perf/final/`，日志位于 `.git/bs-local/` 与 `.git/bs-local/codegen-perf/`。构建产物和机器日志不纳入提交。
