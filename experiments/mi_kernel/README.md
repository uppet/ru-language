# 密模式 S0/S1 有界本地实验（不是语言功能发布）

基线：[ru-language `649d98c399f74f1cf0a6bb89a1989bd44c8a8f4d`](https://github.com/uppet/ru-language/tree/649d98c399f74f1cf0a6bb89a1989bd44c8a8f4d)。在该源码根下应用实验新增文件即可运行；不修改任何既有生产文件。保留仓库根 MIT LICENSE。基线树和校验信息见 [provenance.json](provenance.json)。本实验仅用于独立实验分支 CI，不是正式语言功能或编辑器集成，不合并 wip/main。

核心文件清单：`generate.py`、`scan.ir.json`、`test_kernel.py`、`no_gc_probe.c`、`generated/kernel.h`、`generated/kernel.js`、`generated/metadata.json`。对照文件：`baseline.ru`、`verify_baseline.py`、`benchmark_baseline.py`、`BENCHMARK.md`。测试证据与性能原始样本路径见下文；运行脚本从自身位置定位仓库，可搬迁后重新生成，不依赖固定workspace路径。

## 得到了什么

- JSON 内部 typed IR → C/JS 的最小生成器；不是候选语法定稿，也没有提供 `算 … 密` 的源码入口。
- `非负8/非负32` 对应现有 `native_runtime.PRIMITIVES`，C 名称/ID/签名复用 `native_c.C_TYPES/PRIMITIVE_IDS/NativeCSignature`；没有第二套 FFI 调用器，没有加载库或授予宿主权限。
- 一次同步只读字节 view → 批量终止符计数 → 小型标量结果的桥接**模型**。C 热循环无需普通值运行时；JS 仅是共同语义模型。
- 普通如言数阵扫描对照（同一 649 工具链）及可复现实验。详见 `BENCHMARK.md`、`benchmark-output/results.json`，不报告 notepad 加速倍数。

## 本实验合同

| 项 | 合同 |
|---|---|
| 计数对象 | 行**终止符序列**数量，不是物理行数。CRLF 算一个，孤立 CR/LF 各一个；空串/无终止符为0；末尾换行只计该序列，不另补空行。 |
| 切片 | 任意原始字节；切片独立解释，切断 CRLF 时片内 CR 或 LF 各可计1。不声明文本/Unicode有效性。 |
| 长度/位置 | 字节单位，u32 最大 4,294,967,295；大于范围拒绝，不截断。测试最大边界的拒绝与计数溢出，不曾分配或扫描4GiB实物。 |
| 运算 | u8读取、u32比较/受检加法；无除法、余数、浮点、NaN、提升或隐式缩窄。上下文整数常量精确范围检查。 |
| 真值 | 数值0为真。fixture 使用 `truth(u32 0)` 包住扫描；比较产生的假仍为假，非终止字节不可计数。 |
| 错误 | 内部状态 OK=0/BOUNDS=1/OVERFLOW=2/CLOSED=3/BORROWED=4/RANGE=5。它们不是批准的中文语言错误接口或新C ABI。 |
| 部分效果 | 已完成的**内部标量计数**保留，溢出返回当前计数；另有先+1再load越界夹具。尚无外部输出缓冲，因此不宣称已验证外部部分写入合同。 |
| 作用域 | 只读借用无返回/装箱/全局保存操作；IR拒绝不支持语句和view返回。不是完整控制流借用分析器。 |

### Owner 与错误边界的真实覆盖

C 的 `MiOwner` 是受信任 harness 持有真实存储的内部描述，非允许用户从整数构造任意地址的API。外层调用持有owner，进入后增加borrow计数、所有内核返回后减少；空view不对NULL做指针运算。`mi_scan_checked` 只演示 int64→u32 检查适配，不是普通如言数/盒的适配器。指针/容量真实性与生命周期由内部调用方保证，非裸指针沙箱。

JS `Owner` 显式复制一次输入到私有数据，以排除外部可变alias；scan 创建一次子视图，`finally` 清理。JS无需真实地址，也不保证物理无分配。C输入预存储零拷贝；两者准备成本不等同，已分列。

关闭保护的 C 测试手设借用状态后调用close；本内核无回调，因此**未验证真实回调期间关闭、GC触发保活、既有 FFI NativeMemory 的关闭/扩容协议或Windows重入**。没有并发/异步/长期借用支持。不要把独立owner模型验收冒称现有FFI集成。

## 复现

从仓库根下的 `experiments/mi_kernel` 执行（仅已有 Python/GCC/Node/nm，无安装）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 generate.py
PYTHONDONTWRITEBYTECODE=1 python3 test_kernel.py
PYTHONDONTWRITEBYTECODE=1 python3 verify_baseline.py
PYTHONDONTWRITEBYTECODE=1 python3 benchmark_baseline.py
# 仅检查该C wrapper+kernel自身无外部符号；不是整个应用GC指标：
gcc -std=c11 -O2 -fno-builtin -I generated -c no_gc_probe.c -o generated/no-gc-probe.o
nm -u generated/no-gc-probe.o
```

语义验收包含644组固定/seed649随机/切片/非法参数输入，分别对独立Python CRLF归一化oracle验证 C-O2、Node和C-UBSan；另测主动内核越界、局部命名碰撞/关键字生成、非法/逃逸IR拒绝与旧类型签名一致性。输出见 `semantic-test.log`、`semantic-results.json`。

旧接口专项（从仓库根）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_native_c_plan.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_native_anchors.py' -v
```

分别79/2项通过；**此处列出的历史证据是本地结果；实验分支的 Linux/Windows CI 结果以对应提交运行与上传 artifacts 为准，不代表 GUI 集成**。实验未修改任何生产文件，普通对照还经过72组C/JS正确性测试。

## 阶段状态与下一门槛

| 执行项 | 本地证据 | 状态 |
|---|---|---|
| E-01 共用描述 | u8/u32现有类型、布局/签名对象被复用 | S0最小样本，不是完整公共IR层迁移 |
| E-02 计算核心 | 内部IR检查与双后端测试 | 原型验证；未接AST/parser |
| E-03 借用 | 独立同步只读owner/view模型 | 未集成既有GC根/关闭/回调 |
| E-07 差分/成本 | fixture、UBSan、普通对照、产物大小 | 局部验收；非产品端到端收益 |

下一轮应先确定普通如言→内核桥的实际插入点，将此受限IR接到已知签名路径，并对现有owner/关闭协议做真实集成测试；随后才在**同一工具链、同一输入表示、feature-off/on配对**下衡量ru_notepad热点与p95。另列产品旧pin兼容性，不能把旧编译器→649的差异当密模式收益。行索引输出缓冲、UTF-16、密形/密句、外部写入、真实Windows/Scintilla接入不在本轮。

结论：路线具备继续小步集成的证据；S0/S1整体退出门槛尚未达成，用户语言功能与notepad性能目标均未宣称完成。

## 独立实验 CI

`.github/workflows/mi-kernel-prototype.yml` 仅在 `mi-perf-prototype` 分支 push 时运行。Linux 与 Windows 均执行相同 644 组 C/JS 语义输入、72 组普通 C/JS 对照和同参数成本记录。Linux 额外强制 UBSan；Windows MinGW 不宣称 UBSan 覆盖。Windows 定时使用 QueryPerformanceCounter，Linux 使用 CLOCK_MONOTONIC；可执行文件使用平台后缀。旧正式 CI 文件保持不变，会照常响应 push。

上传 artifacts 含原始结果、平台/工具版本与源码 SHA。性能记录没有通过倍数门槛，不把不同数据表示的差距归因于单一优化，更不代表 ru_notepad 提速。
