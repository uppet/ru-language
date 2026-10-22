# 显式源码密编译窄闭环（实验，不是公开语法）

**bs 适配说明：** 本目录从 `d78a29d` 复制，现增加直接 LLVM 14 后端及普通调用桥、两平台标量示例。当前使用、验收和自举／如书尚未接入的边界见 [LLVM 密模式指南](../../docs/mi-llvm.md)。下文保留原型提交的 C/JS 范围说明；其中“尚无真实 Windows 结果”等描述属于原始提交状态，本地复验另见新指南。

基线：`uppet/ru-language@f4ef6be4f5e0ae2ab25820d47e2cf183792b803d`。
本批在现有 frontend AST 上实施**源码→类型/效果检查→通用 IR→C/JS**，并给 C 普通函数调用接入真实 `NativeMemory` 同步只读借用。不是手写扫描 C 热点，也不按函数名识别算法。

## 运行

```sh
# 只生成源码决定的计算内核；不执行用户源码。
python experiments/mi_kernel/generate.py \
  --manifest experiments/mi_source/manifest.json \
  --entry experiments/mi_source/caller.ru

# Windows x64 原生目标。须显式选择 manifest 和原生权限。
python ru build experiments/mi_source/caller.ru --allow-native \
  --experimental-mi-manifest experiments/mi_source/manifest.json \
  --emit-c build/mi-source.c -o build/mi-source.exe

python experiments/mi_source/test_source.py
# Linux：以下仅使用既有 test-only POSIX NativeMemory 平台适配，不是生产 ABI 验收。
MI_UBSAN=1 python experiments/mi_source/test_source.py
```

源码 `ascii.ru` 是普通如言，使用原有算／取／若／循 次／破／得。未选择 manifest 时，仍按普通函数语义编译，可给数阵建立独立 oracle；**不能把 NativeMemory 当普通阵**。普通动态类型注解会在本实验绑定时拒绝，精确类型只来自 manifest；没有添加密关键字、公开视图名或返回类型拼写。

## 清单身份与参数合同

- 清单版本 1。`module` 相对清单目录规范化，与实际加载模块图的规范绝对路径匹配；只绑定唯一顶层具名算的 AST 身份。不按全局函数名匹配。同名其他模块不受影响，重复绑定拒绝。
- `params` 必须按源码参数顺序完整匹配。仅 `u8`、`u32` 与最多一个 `borrow_ro_u8`；返回 `u8` 或 `u32`。参数名、顺序、数量和返回类型不依赖 `data/length/seed/count`。
- 普通 C caller 仍走原有函数描述符、实参求值／绑定。标量只接受整数性、有限性与范围全部通过的普通数，再转换；u32完全可由binary64精确表示。视图参数必须是真实 `RN_MEMORY`，不接受阵、原始整数地址或任意指针。
- `ranges` 可显式绑定 `view/begin/end`，在借用前检查 `0 <= begin <= end <= memory.size`。单位均为字节。内核每次读取仍独立检查 view.length，不能把普通句的码点索引当字节索引。
- 取完整 NativeMemory 数据区为视图，保留其 root/parent/owner 关系。**UTF8 示例适配是一次显式复制，含终止 NUL，拒绝内嵌 NUL**；调用的 end 不含终止 NUL。消费者应测量复制、分配、索引映射和跨界总成本，不称零拷贝。

## 受限源码与效果

- 整数常量从 `Node.token.value` 精确读取，不使用普通 AST 中已转成 float 的 `data.value`。本批仅十进制数字串；类型由参数／返回／运算／清单 locals 提供。条件中的纯数字使用 u32 上下文，0仍为真。
- 支持固定局部整数、检查加减、同类型比较、短路且／或／非、view索引和量、若/另、**有界**循 次、破、标量返回。局部类型推导后固定；第一次纯字面量局部初始化须在清单 `locals` 指定类型。
- 每个可失败IR表达式保留源码行列。编译拒绝指向实际 AST token；运行时bounds/overflow返回状态及源位置，桥释放后才映射到普通运行时错误。
- 所有函数调用（含静态密算调用）、闭包、回调、外部调用、分配语句、普通对象／容器、视图写入、视图保存／返回、无界循环、隐式数值提升及未定案运算均明确拒绝。效果合同必须完整写明 `borrow-read/no-escape/no-callback/no-gc/may-fail`。
- 内核没有运行时分配、GC、装箱、外部调用或非局部退出；检查式失败只返回状态。桥的owner快照**可以分配**，这不是内核零分配承诺。

## 借用与错误

C桥顺序：检查全部普通标量 → 检查线程/重入/NativeMemory/范围 → 分配并保活完整owner快照 → 增借用计数 → 调用效果已验证生成内核 → 释放借用/快照 → 返回普通小整数或报错。单view避免多次acquire中途失败的回滚问题；只读不生成restrict/noalias。

真实runtime既有同根关闭／写入和FFI重入禁止仍生效，保持旧FFI未借用时的行为。内核返回失败与成功均先释放。错误是现有 `ru_fail` 运行错误，**不是可由普通「试/救」恢复的新异常合同**；测试中的C trap只验证现有native宿主错误边界与清理，不宣称语言新增可恢复异常。

## JS 与历史原型的边界

`generated/kernel.js` 是同一已验证IR的纯计算语义模型，入参是内部已类型化的 `Uint8Array`/u32，而不是NativeMemory或地址。它没有普通如言借用桥、没有物理ABI、没有JS零分配承诺。`ranges` 是普通C桥前置合同，不是裸内核自己的参数验证。C／JS差分在合法typed输入上比较结果，并分别验证内核失败条件与短路；不得把这称为跨后端完整S1。

`mi_kernel/generate.py` 的无参数模式和 `*_legacy_fixture` 只保留历史v1行终止符证据。新 `--manifest` 路径及v2 API全部使用 `rulang.mi_source` / `rulang.mi_ir` 通用后端，旧硬编码fixture不参与源码编译，也不计为新闭环证据。

## 本批验收范围

`test_source.py` 覆盖普通caller/import→generated kernel真实调用、GC阈值1、857组C/JS oracle（全部256种字节＋随机区间＋空输入）、名称/参数/常量/条件变更、精确token、u8/u32签名、0真值、短路越界不求值、源码拒绝定位、错误源span、错误后释放/retry、普通输入类型/范围、模块同名隔离、清单坏类型，以及未opt-in不注入任何密桥。旧借用与原生回归另跑。

**仍不算S1整体通过**：尚需真实Windows执行结果、真实消费者端到端成本与性能门槛；JS普通借用路径尚未实现；静态密算调用未纳入。此提交不修改main/wip、不承诺GUI性能，也不擅定公开密语法。
