# Windows x64 本地 Python：ru run --allow-native examples/native/native_values.ru
# 可先使用 ru check --target python 验证；本例不加载 DLL。
密 取 外言 '如:密'.
长值 取 (密 其 u64) 其 值 '18446744073709551615'.
显 长值 其 句.
显 长值 其 位段 0 16.
有号值 取 (密 其 intptr) 其 重释 长值.
显 有号值 其 句.
点型 取 密 其 结构 [['x',密 其 i32],['y',密 其 i32]].
点 取 点型 其 新建.
点 其 写 'x' 12.
点 其 写 'y' (-3).
显 (点 其 读 'x') 其 数.
显 点型 其 大小.
点 其 关闭.
标题 取 密 其 UTF16 '你好，如 😀'.
显 标题 其 解UTF16.
标题 其 关闭.
