# 第三方算法与许可说明

本项目自有代码与文档采用根目录 [MIT License](../LICENSE)。本授权不改变任何第三方代码、数据或文档的许可，也不替其作者授予新权利。下列 PCG32 派生部分继续适用 Apache-2.0，不能仅凭本项目 MIT 许可分发。

`rulang/thirdparty/如见/` 是本项目自有的内置实验库，采用项目 MIT 许可；目录名表示它不属于语言核心或标准库，不表示其代码来自其他权利人。

## PCG32

`rulang/practical_runtime.py`、`rulang/practical_runtime.h`、`rulang/runtime.js` 中的 PCG32 XSH-RR 初始化、状态更新及有界拒绝采样遵循 Melissa O'Neill 的 PCG 参考实现。

Copyright 2014 Melissa O'Neill <oneill@pcg-random.org>

参考源码以 Apache License 2.0 授权。许可全文见 [PCG-Apache-2.0.txt](licenses/PCG-Apache-2.0.txt)。算法说明与出处：

- https://www.pcg-random.org/using-pcg-c-basic.html
- https://github.com/imneme/pcg-c-basic

如的接口固定序列选择值为54，并单独处理单点及完整32位区间；这些接口选择不构成密码学安全保证。
