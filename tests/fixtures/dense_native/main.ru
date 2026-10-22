密 取 外言 '如:密'.
核 取 外言 'kernel.ru'.
作 断言 条件 说明:
    若 非 条件 则 卒 说明. 然
为
文本 取 'A'+'😀'.
断言 ((核 其 读字 文本 0) == 65) 'prewarm byte'.
断言 ((核 其 加法 文本 1 2) == 3) 'prewarm sum'.
断言 ((核 其 范围 文本 0 5) == 5) 'prewarm range'.
库 取 密 其 动态库 @DLL@.
调用 取 库 其 绑定 'dense_invoke' (密 其 签名 (密 其 i64) ([密 其 指针,密 其 u32]) 'win64').
计数 取 库 其 绑定 'dense_returns' (密 其 签名 (密 其 u32) ([]) 'win64').
签 取 密 其 签名 (密 其 i64) ([密 其 u32]) 'win64'.
算 处理 模式:
    断言 (密 其 回调中) 'callback depth missing'.
    模 取 模式 其 数.
    若 模 == 1 则 得 核 其 读字 文本 99. 然
    若 模 == 2 则 得 核 其 加法 文本 4294967295 1. 然
    若 模 == 3 则 得 核 其 读字 文本 (-1). 然
    若 模 == 4 则 得 核 其 范围 文本 4 1. 然
    得 核 其 读字 文本 0.
法
回 取 密 其 回调 签 (算 处理) (-701).
序列 取 [0,1,0,2,0,3,0,4,0].
序 取 0.
循 (序列 其 量) 次
    模 取 序列[序].
    果 取 调用 其 调用 [回,模].
    断言 (非 (密 其 回调中)) 'callback depth leaked'.
    若 模 == 0 则
        断言 ((果 其 回调错误) == 空) 'stale callback error'.
        断言 (((果 其 值) 其 数) == 65) 'retry result'.
    另
        断言 (((果 其 值) 其 数) == -701) 'callback fallback'.
        错 取 果 其 回调错误.
        断言 (错 != 空) 'missing callback diagnostic'.
        若 模 == 1 则 断言 (错 其 含 'status=1') 'bounds status'. 然
        若 模 == 2 则 断言 (错 其 含 'status=2') 'overflow status'. 然
        若 模 == 3 则 断言 (错 其 含 '密整数参数') 'scalar rejection'. 然
        若 模 == 4 则 断言 (错 其 含 '密视图起止范围越界') 'range rejection'. 然
        显 错.
    然
    断言 ((((计数 其 调用 []) 其 值) 其 数) == 序+1) 'DLL did not resume'.
    序 取 序+1.
环
回 其 关闭.
显 'dense-native-retry-ok'.
