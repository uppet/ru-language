# C 密模式底座（显式实验）

本批从 `mi-perf-prototype@d78a29d` 的受检 IR、源码清单和真实 NativeMemory 只读 owner 桥，以及 `bs@826995a` 的不可变 UTF8 桥分拆移植到 `ae1a994` 基线。它不是整分支合并，也不包含 LLVM、自举、如书原生内核、记事本补丁或折叠优化。

仅 `ru build --experimental-mi-manifest FILE` 显式选择的顶层算进入密编译。普通 C、JS、Python 路径不自动启用；没有新增公开密语法。C 内核支持 u8/u32、受检加减和索引、有界循环、短路、标量返回；精确类型和受限效果由清单声明。JS 仅保留独立计算模型，没有普通借用桥。

## 两种输入

- `borrow_ro_u8`：真实 NativeMemory 同步只读借用，需要原生权限和 Windows x64。保活 owner，禁止同根写入／关闭及未知效果重入；成功或检查失败都先释放再返回或报告错误。Linux 测试平台夹具不是生产 Linux FFI。
- `borrow_ro_utf8`：普通不可变句的 UTF8 字节视图，无额外复制，不是码点索引。同步调用期间保活句，受检内核不分配、不 GC、不回调；这一路可以用于受控同步原生回调，不放宽 NativeMemory 的独立限制。

最多一个视图，不能逃逸、写入、返回或在内核中调用外部函数。错误仍是现有退出式 `ru_fail`，不是新增可恢复异常。原生回调错误边界沿用现有实现。

CLI 将清单列为输入保护，程序输出及 `--emit-c` 均不得覆盖清单。默认 CLI 仍只提供 C/JS，不增加 LLVM 工具发现、安装或缓存。对照基线的普通输出由 `tests/fixtures/mi-default-ae1a994.json` 固定；正常回归矩阵保持不变。

## 独立验证门

```sh
python experiments/mi_source/test_source.py
python experiments/mi_borrow/test_bridge.py
python experiments/mi_kernel/test_kernel.py
python -m unittest discover -s tests -p test_mi_utf8_c.py -v
python -m unittest discover -s tests -p test_mi_integration.py -v
python -m unittest discover -s tests -v
```

CI 在 Linux、Windows 分别显式运行实验测试，每个原生命令单独一步，失败不能被后续成功命令覆盖。Windows 使用生产原生平台及真实 DLL／回调，Linux 使用测试夹具并额外运行 UBSan；两类证据不能互相替代。原完整 Python 矩阵、Node、Emacs 和示例构建保留。

本文件说明实现与验证方法，不宣称尚未执行的 CI、Windows 验收或消费者性能已通过。尚未达到完整 S1：没有公开密语法、密算静态互调、JS 普通借用、自举密编译、如书密模块加载或 GUI 性能承诺。
