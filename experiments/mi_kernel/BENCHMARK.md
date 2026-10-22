# 行终止符扫描：局部基线与成本实验

这是内部 IR 原型的本地实验，不是如言语法实现、FFI 集成、S1 全验收或 ru_notepad 优化完成证明。

## 可复现命令

从本复制源码根目录执行（现有 Python 3、GCC、Node，无第三方安装）：

```sh
python3 experiments/mi_kernel/verify_baseline.py
python3 experiments/mi_kernel/benchmark_baseline.py
```

需要先由主实验生成 `generated/kernel.h` 和 `generated/kernel.js`。基线也可独立跑：

```sh
python3 experiments/mi_kernel/benchmark_baseline.py --ordinary-only
```

结果和完整样本存于 `benchmark-output/results.json`；原始生成源码、计时包装后的源码及可执行文件都保留在同目录。

## 比较内容

- `baseline.ru` 用现行普通如言 `数 阵`、条件、循环、索引及局部变量统计行终止符，未添加密语法。CRLF 计 1，单独 CR/LF 各计 1；空输入为 0，未终止末行不额外计数。
- 72 个普通基线 fixture 在真实 C 与 JS 后端执行；8 个固定输入覆盖空、CR、LF、CRLF、CRCRLF、LFCR、内部零和非文本字节，另 64 个 seed=649 随机输入。独立 oracle 先按字节替换 CRLF→LF、CR→LF，再计 LF。
- 默认性能语料为 `[65,13,10,66,10,67,13,68]` 重复至 65,536 字节，扫描 4 次，预期校验和 98,304。各路径 1 次不记录预热，9 次独立进程内计时；不包含编译或进程创建。p95 是样本 nearest-rank。
- C/JS 普通基线的计时插在生成物入口，包含普通运行时初始化、数阵构建、扫描、输出和退出清理；不会把数组准备成本隐去。
- Typed C 记录构建、扫描、整体时间，分别运行直接内核与带 bounds/owner 检查的 wrapper。主程序与调用函数分开编译，GCC `-O2`、不启用 LTO，防止优化器将重复纯扫描提升成一次。每次扫描校验状态、累计结果；输入来自真实分配并填充的字节区。
- JS owner 建立时复制一次 65,536 字节，单独记录 `BM_OWNER_COPY`；每次调用仍有受管理视图/结果对象成本，不宣称 JS 无 GC 或 native 速度。

## 不能推导的结论

1. 普通动态数阵（C 中数字内联于 `Val`，不是每个数分别堆装箱）和 contiguous `u8` 视图不是同一物理表示；差值同时包含动态派发、逐值存储、数组构建和运行时成本，**不能归结成某一条优化的独立收益**。
2. 这是合成语料，不是真实编辑器文本或 Windows/Scintilla 消息流；没有 ru_notepad 接入、GUI p95、全文重扫/增量重扫对照，也没有产品加速倍数结论。
3. C 内核和桥接由可信 C harness 直接调用，尚未通过普通如言编译器的调用表达式接入；不能称为完成普通如言→密算的语言端到端闭环。
4. Typed C 无输入复制，JS owner 做一次显式复制；这不是两后端相同分配成本。C 的显式 close/free 与 JS 的可回收状态也不等于强制执行了 JS GC。
5. 体积是生成文件及本机测试可执行文件字节数，不是峰值内存；未对普通运行时装箱/分配次数、复制次数、GC 次数做计数，也未测 Unicode 文本验证或真实缓冲适配成本。
6. direct/wrapper 差值受本机噪声影响，不能从该样本准确分离调用开销；扫描子区间未包含 owner 建立成本。不得单用 `BM_SCAN` 对比普通路径整体时间而不说明范围不同。

这是“原生表示＋批量扫描有值得继续研究的空间”的证据；下一步应在实际热点和现有 owner 适配边界中验证，而不是扩大类型范围或宣称已优化 notepad。

文字勘误：将旧结果说明中的 `boxed number array` 更正为 `dynamic-number array (inline Val numbers in C)`；仅修正表示术语，测量样本、数值和内核未改变，未因此重跑性能。
